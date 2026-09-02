"""Responsibility-aware, budget-enforcing model routing."""

from collections.abc import Mapping
from dataclasses import dataclass

from src.core.exceptions import QuestionnaireProviderRequestRejected, QuestionnaireProviderUnavailable
from src.core.model_profiles import ModelProfile, ModelResponsibility
from src.shared.llm.contracts import GeneratedText, TextGenerator
from src.shared.llm.quota import ModelQuotaGuard, estimate_input_tokens


class ModelRouter:
    """Apply a profile before a model call and use an explicit fallback only."""

    def __init__(
        self,
        profiles: Mapping[ModelResponsibility, ModelProfile],
        generators: Mapping[ModelResponsibility, TextGenerator],
        fallback_profiles: Mapping[ModelResponsibility, ModelProfile] | None = None,
        fallback_generators: Mapping[ModelResponsibility, TextGenerator] | None = None,
        quota_guard: ModelQuotaGuard | None = None,
    ) -> None:
        self._profiles = dict(profiles)
        self._generators = dict(generators)
        self._fallback_profiles = dict(fallback_profiles or {})
        self._fallback_generators = dict(fallback_generators or {})
        self._quota_guard = quota_guard

    async def generate(self, responsibility: ModelResponsibility, prompt: str) -> GeneratedText:
        profile = self._profiles[responsibility]
        generator = self._generators.get(responsibility)
        if generator is None:
            raise QuestionnaireProviderUnavailable(
                "No provider is configured for %s." % responsibility
            )
        try:
            return await self._generate_with_profile(profile, generator, prompt)
        except QuestionnaireProviderUnavailable as primary_error:
            fallback_profile = self._fallback_profiles.get(responsibility)
            fallback_generator = self._fallback_generators.get(responsibility)
            if fallback_profile is None or fallback_generator is None:
                raise primary_error
            fallback_requires_compaction = (
                isinstance(primary_error, QuestionnaireProviderRequestRejected)
                or len(prompt.encode("utf-8")) > fallback_profile.source_byte_cap
            )
            fallback_prompt = (
                self._compact_for_fallback(prompt, fallback_profile.source_byte_cap)
                if fallback_requires_compaction
                else prompt
            )
            return await self._generate_with_profile(
                fallback_profile, fallback_generator, fallback_prompt,
            )

    @staticmethod
    def _compact_for_fallback(prompt: str, byte_cap: int) -> str:
        """Keep instructions and recent context after a provider rejects size."""
        encoded = prompt.encode("utf-8")
        marker = "\n\n[Context compacted after provider payload rejection.]\n\n"
        marker_bytes = len(marker.encode("utf-8"))
        target = min(
            int(len(encoded) * 0.75),
            int(byte_cap * 0.9),
            max(byte_cap - marker_bytes, 0),
        )
        if target >= len(encoded):
            return prompt
        head_size = int(target * 0.6)
        tail_size = target - head_size
        head = encoded[:head_size].decode("utf-8", errors="ignore")
        tail = encoded[-tail_size:].decode("utf-8", errors="ignore")
        return head + marker + tail

    def bind(self, responsibility: ModelResponsibility) -> "RoutedTextGenerator":
        """Expose one responsibility through the ordinary TextGenerator API."""
        return RoutedTextGenerator(self, responsibility)

    async def _generate_with_profile(
        self,
        profile: ModelProfile,
        generator: TextGenerator,
        prompt: str,
    ) -> GeneratedText:
        if not profile.is_selectable:
            raise QuestionnaireProviderUnavailable(
                "The %s model profile is not enabled with a complete budget." % profile.responsibility
            )
        request_bytes = len(prompt.encode("utf-8"))
        if request_bytes > profile.source_byte_cap:
            raise QuestionnaireProviderRequestRejected(
                "The %s request exceeds its configured source-byte budget." % profile.responsibility
            )
        # UTF-8/2 is intentionally conservative for Arabic text. It prevents a
        # request from reaching a provider when the local token budget is known
        # to be insufficient, without making another billable API call.
        estimated_input_tokens = estimate_input_tokens(prompt)
        if estimated_input_tokens > profile.max_input_tokens:
            raise QuestionnaireProviderRequestRejected(
                "The %s request exceeds its configured input-token budget." % profile.responsibility
            )
        if self._quota_guard is not None:
            await self._quota_guard.acquire(profile, estimated_input_tokens)
        return await generator.generate(prompt)


@dataclass(frozen=True)
class RoutedTextGenerator:
    """TextGenerator adapter that cannot be used without a responsibility."""

    router: ModelRouter
    responsibility: ModelResponsibility

    async def generate(self, prompt: str) -> GeneratedText:
        return await self.router.generate(self.responsibility, prompt)

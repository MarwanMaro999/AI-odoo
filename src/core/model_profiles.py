"""Per-responsibility AI budgets established during Phase 0.

The profiles describe policy only.  They are not a provider router and do not
make network requests; routing begins in the later security/model-router phase.
"""

from dataclasses import dataclass
from enum import StrEnum

from src.core.config import Settings


class ModelResponsibility(StrEnum):
    INJECTION_SCAN = "injection_scan"
    ENGLISH_GENERATION = "english_generation"
    ARABIC_GENERATION = "arabic_generation"
    STRUCTURED_REVIEW = "structured_review"
    SESSION_SUMMARY = "session_summary"


@dataclass(frozen=True)
class ModelProfile:
    """A bounded configuration for one distinct AI responsibility."""

    responsibility: ModelResponsibility
    provider: str
    model: str
    source_byte_cap: int
    max_input_tokens: int
    reserve_output_tokens: int
    requests_per_minute: int
    tokens_per_minute: int
    requests_per_day: int
    enabled: bool
    timeout_seconds: float
    max_retries: int
    provider_input_token_limit: int | None = None
    provider_output_token_limit: int | None = None

    @property
    def has_complete_budget(self) -> bool:
        return all((
            self.source_byte_cap > 0,
            self.max_input_tokens > 0,
            self.reserve_output_tokens > 0,
            self.requests_per_minute > 0,
            self.tokens_per_minute > 0,
            self.requests_per_day > 0,
        ))

    @property
    def is_selectable(self) -> bool:
        """Only a deliberately enabled, fully measured profile may be routed."""
        return self.enabled and self.has_complete_budget


def build_model_profiles(settings: Settings) -> dict[ModelResponsibility, ModelProfile]:
    """Build the Phase 0 profile catalogue used by the runtime router."""
    generation_profile = dict(
        provider="groq",
        model=settings.ai_generation_model,
        source_byte_cap=settings.ai_generation_source_bytes,
        max_input_tokens=settings.ai_generation_max_input_tokens,
        reserve_output_tokens=settings.ai_generation_max_output_tokens,
        requests_per_minute=settings.ai_generation_rpm,
        tokens_per_minute=settings.ai_generation_tpm,
        requests_per_day=settings.ai_generation_rpd,
        enabled=settings.ai_generation_enabled,
        timeout_seconds=settings.ai_generation_timeout_seconds,
        max_retries=settings.ai_generation_max_retries,
    )
    return {
        ModelResponsibility.INJECTION_SCAN: ModelProfile(
            responsibility=ModelResponsibility.INJECTION_SCAN,
            provider="groq",
            model=settings.ai_prompt_guard_model,
            source_byte_cap=settings.ai_prompt_guard_source_bytes,
            max_input_tokens=settings.ai_prompt_guard_max_input_tokens,
            reserve_output_tokens=settings.ai_prompt_guard_max_output_tokens,
            requests_per_minute=settings.ai_prompt_guard_rpm,
            tokens_per_minute=settings.ai_prompt_guard_tpm,
            requests_per_day=settings.ai_prompt_guard_rpd,
            enabled=True,
            timeout_seconds=settings.ai_prompt_guard_timeout_seconds,
            max_retries=settings.ai_prompt_guard_max_retries,
        ),
        ModelResponsibility.ENGLISH_GENERATION: ModelProfile(
            responsibility=ModelResponsibility.ENGLISH_GENERATION,
            **generation_profile,
        ),
        ModelResponsibility.ARABIC_GENERATION: ModelProfile(
            responsibility=ModelResponsibility.ARABIC_GENERATION,
            **generation_profile,
        ),
        ModelResponsibility.STRUCTURED_REVIEW: ModelProfile(
            responsibility=ModelResponsibility.STRUCTURED_REVIEW,
            provider="groq",
            model=settings.ai_review_model,
            source_byte_cap=settings.ai_review_source_bytes,
            max_input_tokens=settings.ai_review_max_input_tokens,
            reserve_output_tokens=settings.ai_review_max_output_tokens,
            requests_per_minute=settings.ai_review_rpm,
            tokens_per_minute=settings.ai_review_tpm,
            requests_per_day=settings.ai_review_rpd,
            enabled=True,
            timeout_seconds=settings.ai_review_timeout_seconds,
            max_retries=settings.ai_review_max_retries,
        ),
        ModelResponsibility.SESSION_SUMMARY: ModelProfile(
            responsibility=ModelResponsibility.SESSION_SUMMARY,
            provider="groq",
            model=settings.ai_summary_model,
            source_byte_cap=settings.ai_summary_source_bytes,
            max_input_tokens=settings.ai_summary_max_input_tokens,
            reserve_output_tokens=settings.ai_summary_max_output_tokens,
            requests_per_minute=settings.ai_summary_rpm,
            tokens_per_minute=settings.ai_summary_tpm,
            requests_per_day=settings.ai_summary_rpd,
            enabled=True,
            timeout_seconds=settings.ai_summary_timeout_seconds,
            max_retries=settings.ai_summary_max_retries,
        ),
    }


def build_hf_fallback_profile(
    settings: Settings,
    responsibility: ModelResponsibility,
) -> ModelProfile:
    """Return the explicitly capped HF Llama fallback profile.

    Hugging Face's ``auto`` provider can change upstream providers, so these
    values are application circuit-breaker caps rather than provider claims.
    """
    if responsibility not in {
        ModelResponsibility.ENGLISH_GENERATION,
        ModelResponsibility.ARABIC_GENERATION,
    }:
        raise ValueError("Hugging Face fallback is only configured for generation")
    return ModelProfile(
        responsibility=responsibility,
        provider="huggingface",
        model=settings.hf_model,
        source_byte_cap=settings.hf_fallback_source_bytes,
        max_input_tokens=settings.hf_fallback_max_input_tokens,
        reserve_output_tokens=settings.hf_max_completion_tokens,
        requests_per_minute=settings.hf_fallback_rpm,
        tokens_per_minute=settings.hf_fallback_tpm,
        requests_per_day=settings.hf_fallback_rpd,
        enabled=settings.hf_automatic_fallback_enabled,
        timeout_seconds=settings.hf_timeout_seconds,
        max_retries=settings.hf_fallback_max_retries,
    )


def build_compound_fallback_profile(
    settings: Settings,
    responsibility: ModelResponsibility,
) -> ModelProfile:
    """Build the independently budgeted Compound fallback profile."""
    if responsibility == ModelResponsibility.STRUCTURED_REVIEW:
        return ModelProfile(
            responsibility=responsibility,
            provider="groq_fallback",
            model=settings.ai_review_fallback_model,
            source_byte_cap=settings.ai_review_fallback_source_bytes,
            max_input_tokens=settings.ai_review_fallback_max_input_tokens,
            reserve_output_tokens=settings.ai_review_fallback_max_output_tokens,
            requests_per_minute=settings.ai_review_fallback_rpm,
            tokens_per_minute=settings.ai_review_fallback_tpm,
            requests_per_day=settings.ai_review_fallback_rpd,
            enabled=settings.ai_review_fallback_enabled,
            timeout_seconds=settings.ai_review_fallback_timeout_seconds,
            max_retries=settings.ai_review_fallback_max_retries,
        )
    if responsibility not in {
        ModelResponsibility.ENGLISH_GENERATION,
        ModelResponsibility.ARABIC_GENERATION,
    }:
        raise ValueError("Compound fallback is only configured for generation and review")
    return ModelProfile(
        responsibility=responsibility,
        provider="groq_fallback",
        model=settings.ai_generation_fallback_model,
        source_byte_cap=settings.ai_generation_fallback_source_bytes,
        max_input_tokens=settings.ai_generation_fallback_max_input_tokens,
        reserve_output_tokens=settings.ai_generation_fallback_max_output_tokens,
        requests_per_minute=settings.ai_generation_fallback_rpm,
        tokens_per_minute=settings.ai_generation_fallback_tpm,
        requests_per_day=settings.ai_generation_fallback_rpd,
        enabled=settings.ai_generation_fallback_enabled,
        timeout_seconds=settings.ai_generation_fallback_timeout_seconds,
        max_retries=settings.ai_generation_fallback_max_retries,
    )

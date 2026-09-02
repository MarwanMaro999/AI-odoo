"""Construct the only production model router used by application wiring."""

from src.core.config import Settings
from src.core.model_profiles import (
    ModelResponsibility,
    build_compound_fallback_profile,
    build_model_profiles,
)
from src.shared.llm.providers import GroqTextGenerator
from src.shared.llm.router import ModelRouter
from src.shared.llm.quota import ModelQuotaGuard


def build_runtime_model_router(
    settings: Settings,
    *,
    structured_generation: bool = False,
    quota_guard: ModelQuotaGuard | None = None,
) -> ModelRouter:
    """Build Qwen 3.8 primary routes with an independently capped Qwen 3.6 fallback."""
    profiles = build_model_profiles(settings)

    fallback_api_key = settings.groq_fallback_api_key
    if fallback_api_key is None or not fallback_api_key.get_secret_value().strip():
        fallback_api_key = settings.groq_api_key

    def groq_generator(responsibility: ModelResponsibility, structured: bool) -> GroqTextGenerator:
        profile = profiles[responsibility]
        return GroqTextGenerator(
            settings,
            structured_output=structured,
            model_name=profile.model,
            max_completion_tokens=profile.reserve_output_tokens,
            timeout_seconds=profile.timeout_seconds,
            max_generation_attempts=profile.max_retries + 1,
        )

    primary = {
        ModelResponsibility.ENGLISH_GENERATION: groq_generator(
            ModelResponsibility.ENGLISH_GENERATION, structured_generation,
        ),
        ModelResponsibility.ARABIC_GENERATION: groq_generator(
            ModelResponsibility.ARABIC_GENERATION, structured_generation,
        ),
        ModelResponsibility.STRUCTURED_REVIEW: groq_generator(
            ModelResponsibility.STRUCTURED_REVIEW, True,
        ),
        ModelResponsibility.SESSION_SUMMARY: groq_generator(
            ModelResponsibility.SESSION_SUMMARY, False,
        ),
    }
    fallback_profiles = {}
    fallback_generators = {}
    for responsibility in (
        ModelResponsibility.ENGLISH_GENERATION,
        ModelResponsibility.ARABIC_GENERATION,
        ModelResponsibility.STRUCTURED_REVIEW,
    ):
        profile = build_compound_fallback_profile(settings, responsibility)
        if profile.enabled:
            fallback_profiles[responsibility] = profile
            fallback_generators[responsibility] = GroqTextGenerator(
                settings,
                structured_output=(structured_generation or responsibility == ModelResponsibility.STRUCTURED_REVIEW),
                model_name=profile.model,
                max_completion_tokens=profile.reserve_output_tokens,
                timeout_seconds=profile.timeout_seconds,
                max_generation_attempts=profile.max_retries + 1,
                api_key=fallback_api_key,
                provider_label="groq_qwen_fallback",
            )
    return ModelRouter(
        profiles, primary, fallback_profiles, fallback_generators, quota_guard=quota_guard,
    )

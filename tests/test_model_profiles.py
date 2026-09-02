from src.core.config import Settings
from src.core.model_profiles import (
    ModelResponsibility,
    build_compound_fallback_profile,
    build_model_profiles,
)
from src.shared.llm.quota import NeonModelQuotaGuard


def test_phase_zero_profiles_are_separate_and_bounded() -> None:
    profiles = build_model_profiles(Settings())

    assert set(profiles) == set(ModelResponsibility)
    assert profiles[ModelResponsibility.INJECTION_SCAN].has_complete_budget
    assert profiles[ModelResponsibility.STRUCTURED_REVIEW].has_complete_budget
    assert profiles[ModelResponsibility.SESSION_SUMMARY].has_complete_budget
    assert profiles[ModelResponsibility.ENGLISH_GENERATION].provider == "groq"
    assert profiles[ModelResponsibility.ARABIC_GENERATION].model == "qwen/qwen3.8-27b"
    assert profiles[ModelResponsibility.ENGLISH_GENERATION].tokens_per_minute > 0
    assert profiles[ModelResponsibility.ENGLISH_GENERATION].is_selectable
    assert profiles[ModelResponsibility.ENGLISH_GENERATION].timeout_seconds == 90.0
    assert profiles[ModelResponsibility.ENGLISH_GENERATION].max_retries == 2
    assert profiles[ModelResponsibility.STRUCTURED_REVIEW].max_retries == 1


def test_generation_can_be_explicitly_disabled() -> None:
    profiles = build_model_profiles(Settings(
        ai_generation_enabled=False,
    ))

    assert not profiles[ModelResponsibility.ENGLISH_GENERATION].is_selectable


def test_quota_window_is_shared_by_model_across_responsibilities_and_fallback() -> None:
    settings = Settings()
    profiles = build_model_profiles(settings)
    summary = profiles[ModelResponsibility.SESSION_SUMMARY]
    fallback = build_compound_fallback_profile(
        settings, ModelResponsibility.ENGLISH_GENERATION,
    )

    assert summary.model == fallback.model
    assert NeonModelQuotaGuard._profile_key(summary) == NeonModelQuotaGuard._profile_key(fallback)

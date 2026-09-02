from types import SimpleNamespace

from src.core.config import Settings
from src.core.exceptions import QuestionnaireProviderUnavailable
from src.core.model_profiles import ModelResponsibility
from src.shared.llm.contracts import GeneratedText
from src.shared.llm.providers import FallbackTextGenerator, GroqTextGenerator
from src.shared.llm.runtime import build_runtime_model_router


def test_provider_failure_diagnostics_include_safe_tpm_numbers() -> None:
    error = SimpleNamespace(
        status_code=413,
        response=SimpleNamespace(
            headers={"x-request-id": "req_123"},
            json=lambda: {"error": {"message": "TPM limit 8000, requested 12441 tokens."}},
        ),
    )
    diagnostics = GroqTextGenerator._provider_error_diagnostics(error)
    assert diagnostics["http_status"] == 413
    assert diagnostics["provider_request_id"] == "req_123"
    assert diagnostics["provider_limit"] == 8000
    assert diagnostics["provider_requested"] == 12441
    assert diagnostics["provider_limit_kind"] == "tpm"


def test_json_mode_is_a_provider_level_contract() -> None:
    """Structured engine outputs must not rely on prompt compliance alone."""
    source = __import__("inspect").getsource(GroqTextGenerator.generate)
    assert 'request_arguments["response_format"] = {"type": "json_object"}' in source
    assert 'raise QuestionnaireProviderUnavailable("Groq is rate limited")' in source


def test_fallback_uses_second_provider_after_primary_failure() -> None:
    class Unavailable:
        async def generate(self, _: str) -> GeneratedText:
            raise QuestionnaireProviderUnavailable("unavailable")

    class Available:
        async def generate(self, _: str) -> GeneratedText:
            return GeneratedText(text="{}", provider="huggingface", model="test")

    result = __import__("asyncio").run(FallbackTextGenerator([Unavailable(), Available()]).generate("test"))
    assert result.provider == "huggingface"


def test_hugging_face_automatic_fallback_is_disabled() -> None:
    settings = Settings()

    assert not settings.hf_automatic_fallback_enabled
    assert settings.hf_model == "meta-llama/Llama-3.3-70B-Instruct"
    assert "qwen" not in settings.hf_model.lower()


def test_generation_wiring_uses_qwen_38_then_qwen_36() -> None:
    router = build_runtime_model_router(Settings(), structured_generation=True)

    assert isinstance(router._generators[ModelResponsibility.ENGLISH_GENERATION], GroqTextGenerator)
    assert router._profiles[ModelResponsibility.ENGLISH_GENERATION].model == "qwen/qwen3.8-27b"
    assert isinstance(router._fallback_generators[ModelResponsibility.ENGLISH_GENERATION], GroqTextGenerator)
    assert router._fallback_profiles[ModelResponsibility.ENGLISH_GENERATION].model == "qwen/qwen3.6-27b"
    assert router._fallback_profiles[ModelResponsibility.STRUCTURED_REVIEW].model == "qwen/qwen3.6-27b"


def test_generation_wiring_can_disable_the_fallback_explicitly() -> None:
    router = build_runtime_model_router(Settings(
        ai_generation_fallback_enabled=False,
        ai_review_fallback_enabled=False,
    ))

    assert router._fallback_generators == {}

from types import SimpleNamespace

from src.core.config import Settings
from src.core.exceptions import QuestionnaireProviderUnavailable
from src.shared.llm.contracts import GeneratedText
from src.shared.llm.providers import FallbackTextGenerator, GroqTextGenerator, OpenAITextGenerator


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


def test_openai_unconfigured_provider_yields_to_a_fallback() -> None:
    class Available:
        async def generate(self, _: str) -> GeneratedText:
            return GeneratedText(text="{}", provider="fallback", model="test")

    generator = FallbackTextGenerator([
        OpenAITextGenerator(Settings(openai_api_key=None)),
        Available(),
    ])
    result = __import__("asyncio").run(generator.generate("test"))
    assert result.provider == "fallback"

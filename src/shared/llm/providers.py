"""Groq adapter. Provider SDK details stop here."""

import asyncio
import re
from pydantic import SecretStr

from src.core.config import Settings
from src.core.exceptions import QuestionnaireProviderRequestRejected, QuestionnaireProviderUnavailable
from src.core.logging import get_logger
from src.shared.llm.contracts import GeneratedText, TextGenerator


class GroqTextGenerator:
    """Generate questionnaire content with Groq GPT-OSS."""

    def __init__(
        self,
        settings: Settings,
        structured_output: bool = False,
        max_completion_tokens: int | None = None,
        model_name: str | None = None,
        timeout_seconds: float | None = None,
        max_generation_attempts: int | None = None,
        api_key: SecretStr | None = None,
        provider_label: str = "groq",
    ) -> None:
        self._api_key = api_key or settings.groq_api_key
        self._provider_label = provider_label
        self._model_name = model_name or settings.groq_model
        self._max_completion_tokens = max_completion_tokens or settings.groq_max_completion_tokens
        self._timeout_seconds = timeout_seconds or settings.groq_timeout_seconds
        self._max_generation_attempts = max_generation_attempts or 3
        self._structured_output = structured_output
        self._logger = get_logger()

    async def generate(self, prompt: str) -> GeneratedText:
        """Call Groq with a hard timeout and safe diagnostics."""
        if self._api_key is None:
            raise QuestionnaireProviderUnavailable("Groq is not configured")
        request_bytes = len(prompt.encode("utf-8"))

        def request() -> tuple[str, str | None, int | None, int | None]:
            from groq import Groq

            client = Groq(
                api_key=self._api_key.get_secret_value(),
                timeout=self._timeout_seconds,
                max_retries=0,
            )

            def create_completion(use_json_mode: bool):
                request_arguments = {
                    "model": self._model_name,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": self._max_completion_tokens,
                }
                # These controls are specific to Groq's GPT-OSS models.
                # Compound rejects them, so send only portable chat settings.
                if self._model_name.startswith("openai/gpt-oss"):
                    request_arguments["extra_body"] = {
                        "reasoning_effort": "low",
                        "include_reasoning": False,
                    }
                elif self._model_name.startswith("qwen/qwen3"):
                    request_arguments["extra_body"] = {
                        "reasoning_effort": "none",
                        "include_reasoning": False,
                    }
                if use_json_mode:
                    request_arguments["response_format"] = {"type": "json_object"}
                return client.chat.completions.create(**request_arguments)

            try:
                response = create_completion(self._structured_output)
            except Exception as error:
                # GPT-OSS can occasionally reject otherwise valid constrained JSON
                # generations. The prompt still demands JSON and downstream quality
                # gates validate it, so retry once without constrained decoding.
                if self._structured_output and "json_validate_failed" in str(error):
                    response = create_completion(False)
                else:
                    raise
            choice = response.choices[0]
            usage = response.usage
            return (
                choice.message.content or "",
                choice.finish_reason,
                getattr(usage, "prompt_tokens", None),
                getattr(usage, "completion_tokens", None),
            )

        last_error: Exception | None = None
        for attempt in range(1, self._max_generation_attempts + 1):
            try:
                text, finish_reason, input_tokens, output_tokens = await asyncio.wait_for(
                    asyncio.to_thread(request), timeout=self._timeout_seconds + 5
                )
            except Exception as error:
                last_error = error
                diagnostics = self._provider_error_diagnostics(error)
                retry_after_seconds = self._retry_after_seconds(error) if diagnostics["http_status"] == 429 else None
                self._logger.warning(
                    "llm_generation_attempt_failed",
                    provider=self._provider_label,
                    attempt=attempt,
                    error_type=type(error).__name__,
                    **diagnostics,
                    request_bytes=request_bytes,
                    retry_after_seconds=retry_after_seconds,
                )
                if diagnostics["http_status"] == 413:
                    raise QuestionnaireProviderRequestRejected("Groq request exceeds its current token limit") from error
                if diagnostics["http_status"] == 429:
                    if retry_after_seconds and retry_after_seconds <= 3 and attempt < self._max_generation_attempts:
                        await asyncio.sleep(retry_after_seconds)
                        continue
                    raise QuestionnaireProviderUnavailable("Groq is rate limited") from error
                if diagnostics["http_status"] in {401, 402, 403}:
                    raise QuestionnaireProviderUnavailable("Groq account is not available") from error
                continue

            if finish_reason != "length" and text.strip():
                return GeneratedText(
                    text=text.strip(), provider=self._provider_label, model=self._model_name,
                    input_tokens=input_tokens, output_tokens=output_tokens,
                )

            last_error = ValueError(
                "Groq returned no text"
                if not text.strip()
                else "Groq response reached the completion limit"
            )
            self._logger.warning(
                "llm_generation_attempt_incomplete",
                provider=self._provider_label,
                attempt=attempt,
                finish_reason=finish_reason,
                content_received=bool(text.strip()),
            )

        raise QuestionnaireProviderUnavailable("Groq generation failed") from last_error

    @staticmethod
    def _provider_error_diagnostics(error: Exception) -> dict[str, object | None]:
        """Expose provider limit numbers without ever logging source material."""
        response = getattr(error, "response", None)
        message = ""
        if response is not None:
            try:
                payload = response.json()
                if isinstance(payload, dict):
                    error_payload = payload.get("error", payload)
                    if isinstance(error_payload, dict):
                        message = str(error_payload.get("message", ""))
            except Exception:
                pass
        limit = re.search(r"\blimit\D{0,20}(\d[\d,]*)", message, flags=re.IGNORECASE)
        requested = re.search(r"\brequested\D{0,20}(\d[\d,]*)", message, flags=re.IGNORECASE)
        lowered = message.lower()
        return {
            "http_status": getattr(error, "status_code", None),
            "provider_request_id": (
                response.headers.get("x-request-id")
                if response is not None and getattr(response, "headers", None)
                else None
            ),
            "provider_limit": int(limit.group(1).replace(",", "")) if limit else None,
            "provider_requested": int(requested.group(1).replace(",", "")) if requested else None,
            "provider_limit_kind": "tpm" if "tpm" in lowered or ("token" in lowered and "minute" in lowered) else None,
        }

    @staticmethod
    def _retry_after_seconds(error: Exception) -> int | None:
        response = getattr(error, "response", None)
        headers = getattr(response, "headers", None)
        if not headers:
            return None
        value = headers.get("retry-after") or headers.get("x-ratelimit-reset-tokens")
        if not value:
            return None
        match = re.search(r"\d+", str(value))
        return min(60, max(1, int(match.group()))) if match else None


class HuggingFaceTextGenerator:
    """Hugging Face Inference Providers fallback with structured-output support."""

    def __init__(
        self,
        settings: Settings,
        structured_output: bool = False,
        model_name: str | None = None,
        max_completion_tokens: int | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        self._token = settings.hf_token
        self._model = model_name or settings.hf_model
        self._provider = settings.hf_provider
        self._max_tokens = max_completion_tokens or settings.hf_max_completion_tokens
        self._timeout_seconds = timeout_seconds or settings.hf_timeout_seconds
        self._structured_output = structured_output
        self._logger = get_logger()

    async def generate(self, prompt: str) -> GeneratedText:
        if self._token is None:
            self._logger.warning(
                "llm_generation_attempt_failed",
                provider="huggingface",
                error_type="ProviderNotConfigured",
            )
            raise QuestionnaireProviderUnavailable("Hugging Face is not configured")

        def request() -> tuple[str, int | None, int | None]:
            from huggingface_hub import InferenceClient

            response_format = {"type": "json_object"} if self._structured_output else None
            response = InferenceClient(
                provider=self._provider,
                api_key=self._token.get_secret_value(),
                timeout=self._timeout_seconds,
            ).chat_completion(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=self._max_tokens,
                response_format=response_format,
            )
            usage = getattr(response, "usage", None)
            return (
                response.choices[0].message.content or "",
                getattr(usage, "prompt_tokens", None),
                getattr(usage, "completion_tokens", None),
            )

        try:
            text, input_tokens, output_tokens = await asyncio.wait_for(
                asyncio.to_thread(request), timeout=self._timeout_seconds + 5
            )
        except Exception as error:
            self._logger.warning("llm_generation_attempt_failed", provider="huggingface", error_type=type(error).__name__)
            raise QuestionnaireProviderUnavailable("Hugging Face generation failed") from error
        if not text.strip():
            raise QuestionnaireProviderUnavailable("Hugging Face returned no text")
        return GeneratedText(
            text=text.strip(), provider="huggingface", model=self._model,
            input_tokens=input_tokens, output_tokens=output_tokens,
        )


class FallbackTextGenerator:
    """Try independent providers in order without leaking provider internals."""

    def __init__(self, generators: list[TextGenerator]) -> None:
        self._generators = generators
        self._logger = get_logger()

    async def generate(self, prompt: str) -> GeneratedText:
        last_error: Exception | None = None
        for generator in self._generators:
            try:
                result = await generator.generate(prompt)
                self._logger.info(
                    "llm_generation_succeeded",
                    provider=result.provider,
                    model=result.model,
                )
                return result
            except QuestionnaireProviderUnavailable as error:
                last_error = error
                self._logger.warning(
                    "llm_fallback_provider_unavailable",
                    failed_provider=type(generator).__name__,
                    error_type=type(error).__name__,
                )
        raise QuestionnaireProviderUnavailable("All configured generation providers failed") from last_error

"""Groq adapter. Provider SDK details stop here."""

import asyncio
import re

from src.core.config import Settings
from src.core.exceptions import QuestionnaireProviderRequestRejected, QuestionnaireProviderUnavailable
from src.core.logging import get_logger
from src.shared.llm.contracts import GeneratedText


class GroqTextGenerator:
    """Generate questionnaire content with Groq GPT-OSS."""

    _max_generation_attempts = 3

    def __init__(self, settings: Settings) -> None:
        self._api_key = settings.groq_api_key
        self._model_name = settings.groq_model
        self._max_completion_tokens = settings.groq_max_completion_tokens
        self._timeout_seconds = settings.groq_timeout_seconds
        self._logger = get_logger()

    async def generate(self, prompt: str) -> GeneratedText:
        """Call Groq with a hard timeout and safe diagnostics."""
        if self._api_key is None:
            raise QuestionnaireProviderUnavailable("Groq is not configured")
        request_bytes = len(prompt.encode("utf-8"))

        def request() -> tuple[str, str | None]:
            from groq import Groq

            response = Groq(
                api_key=self._api_key.get_secret_value(),
                timeout=self._timeout_seconds,
                max_retries=0,
            ).chat.completions.create(
                model=self._model_name,
                messages=[{"role": "user", "content": prompt}],
                # Groq SDK 0.13.1 is used by the local Uvicorn environment.
                # It accepts the legacy max_tokens argument and forwards newer
                # GPT-OSS options through extra_body.
                max_tokens=self._max_completion_tokens,
                extra_body={
                    "reasoning_effort": "low",
                    "include_reasoning": False,
                },
            )
            choice = response.choices[0]
            return choice.message.content or "", choice.finish_reason

        last_error: Exception | None = None
        for attempt in range(1, self._max_generation_attempts + 1):
            try:
                text, finish_reason = await asyncio.wait_for(
                    asyncio.to_thread(request), timeout=self._timeout_seconds + 5
                )
            except Exception as error:
                last_error = error
                diagnostics = self._provider_error_diagnostics(error)
                self._logger.warning(
                    "llm_generation_attempt_failed",
                    provider="groq",
                    attempt=attempt,
                    error_type=type(error).__name__,
                    **diagnostics,
                    request_bytes=request_bytes,
                )
                if diagnostics["http_status"] == 413:
                    raise QuestionnaireProviderRequestRejected("groq_tpm_limit_exceeded") from error
                continue

            if finish_reason != "length" and text.strip():
                return GeneratedText(
                    text=text.strip(), provider="groq", model=self._model_name
                )

            last_error = ValueError(
                "Groq returned no text"
                if not text.strip()
                else "Groq response reached the completion limit"
            )
            self._logger.warning(
                "llm_generation_attempt_incomplete",
                provider="groq",
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

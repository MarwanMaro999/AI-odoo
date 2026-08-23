"""Groq adapter. Provider SDK details stop here."""

import asyncio

from src.core.config import Settings
from src.core.exceptions import QuestionnaireProviderUnavailable
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

        def request() -> tuple[str, str | None]:
            from groq import Groq

            response = Groq(
                api_key=self._api_key.get_secret_value(),
                timeout=self._timeout_seconds,
                max_retries=2,
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
                self._logger.warning(
                    "llm_generation_attempt_failed",
                    provider="groq",
                    attempt=attempt,
                    error_type=type(error).__name__,
                )
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

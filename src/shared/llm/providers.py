"""Groq adapter. Provider SDK details stop here."""

import asyncio

from src.core.config import Settings
from src.core.exceptions import QuestionnaireProviderUnavailable
from src.core.logging import get_logger
from src.shared.llm.contracts import GeneratedText


class GroqTextGenerator:
    """Generate questionnaire content with Groq GPT-OSS."""

    def __init__(self, settings: Settings) -> None:
        self._api_key = settings.groq_api_key
        self._model_name = settings.groq_model
        self._logger = get_logger()

    async def generate(self, prompt: str) -> GeneratedText:
        """Call Groq with a hard timeout and safe diagnostics."""
        if self._api_key is None:
            raise QuestionnaireProviderUnavailable("Groq is not configured")

        def request() -> str:
            from groq import Groq

            response = Groq(
                api_key=self._api_key.get_secret_value(), timeout=30.0, max_retries=0
            ).chat.completions.create(
                model=self._model_name,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.choices[0].message.content or ""

        try:
            text = await asyncio.wait_for(asyncio.to_thread(request), timeout=30)
        except Exception as error:
            self._logger.warning(
                "llm_generation_failed",
                provider="groq",
                error_type=type(error).__name__,
            )
            raise QuestionnaireProviderUnavailable("Groq generation failed") from error
        if not text.strip():
            raise QuestionnaireProviderUnavailable("Groq returned no text")
        return GeneratedText(text=text.strip(), provider="groq", model=self._model_name)

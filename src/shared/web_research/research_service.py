"""Optional company research through Groq Compound."""

import asyncio
from dataclasses import dataclass

from src.core.config import Settings
from src.core.logging import get_logger


@dataclass(frozen=True)
class ResearchResult:
    """Safe factual snippets used as supplementary questionnaire context."""

    text: str
    provider: str


class CompanyResearchService:
    """Research public company context with Groq Compound's built-in web search."""

    def __init__(self, settings: Settings) -> None:
        self._api_key = settings.groq_api_key
        self._model_name = settings.groq_research_model
        self._logger = get_logger()

    async def research(self, query: str) -> ResearchResult | None:
        """Return research when available; generation continues if it fails."""
        if self._api_key is None:
            return None

        def request() -> str:
            from groq import Groq

            response = Groq(
                api_key=self._api_key.get_secret_value(), timeout=30.0, max_retries=0
            ).chat.completions.create(
                model=self._model_name,
                messages=[
                    {
                        "role": "user",
                        "content": (
                            "Research this company for a discovery questionnaire. "
                            "Return concise, factual public context with sources: " + query
                        ),
                    }
                ],
            )
            return response.choices[0].message.content or ""

        try:
            text = await asyncio.wait_for(asyncio.to_thread(request), timeout=30)
        except Exception as error:
            self._logger.warning(
                "company_research_failed",
                provider="groq_compound",
                error_type=type(error).__name__,
            )
            return None
        return ResearchResult(text=text.strip(), provider="groq_compound") if text.strip() else None

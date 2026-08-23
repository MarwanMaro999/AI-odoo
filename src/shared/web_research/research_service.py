"""Optional company research through Groq Compound."""

import asyncio
from dataclasses import dataclass
import json
from urllib.request import Request, urlopen

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
        self._tavily_api_key = settings.tavily_api_key
        self._logger = get_logger()

    async def research(self, query: str) -> ResearchResult | None:
        """Return research when available; generation continues if it fails."""
        if self._api_key is None:
            return await self._research_with_tavily(query)

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
            return await self._research_with_tavily(query)
        return ResearchResult(text=text.strip(), provider="groq_compound") if text.strip() else await self._research_with_tavily(query)

    async def _research_with_tavily(self, query: str) -> ResearchResult | None:
        """Use an independent web-search fallback when the model research tool is unavailable."""
        if self._tavily_api_key is None:
            return None

        def request() -> str:
            payload = json.dumps({
                "api_key": self._tavily_api_key.get_secret_value(),
                "query": query,
                "search_depth": "basic",
                "max_results": 5,
                "include_answer": True,
            }).encode("utf-8")
            response = urlopen(Request(
                "https://api.tavily.com/search",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            ), timeout=20)
            result = json.loads(response.read().decode("utf-8"))
            answer = str(result.get("answer", "")).strip()
            sources = [
                f"{item.get('title', 'Source')}: {item.get('url', '')}"
                for item in result.get("results", [])[:5]
                if item.get("url")
            ]
            return "\n".join(([answer] if answer else []) + sources)

        try:
            text = await asyncio.wait_for(asyncio.to_thread(request), timeout=25)
        except Exception as error:
            self._logger.warning(
                "company_research_failed",
                provider="tavily",
                error_type=type(error).__name__,
            )
            return None
        return ResearchResult(text=text.strip(), provider="tavily") if text.strip() else None

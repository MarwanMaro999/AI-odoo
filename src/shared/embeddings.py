"""Bounded multilingual embedding adapter for durable context retrieval."""

import asyncio
from collections.abc import Sequence
from typing import Protocol

from src.core.config import Settings


class EmbeddingProvider(Protocol):
    model: str

    async def embed(self, text: str) -> list[float] | None: ...


class HuggingFaceEmbeddingProvider:
    """Use HF only for multilingual retrieval embeddings, never generation."""

    def __init__(self, settings: Settings) -> None:
        self._token = settings.hf_token
        self._provider = settings.hf_provider
        self.model = settings.ai_embedding_model
        self._timeout_seconds = settings.ai_embedding_timeout_seconds

    async def embed(self, text: str) -> list[float] | None:
        if self._token is None or not text.strip():
            return None

        def request() -> Sequence[float]:
            from huggingface_hub import InferenceClient

            return InferenceClient(
                provider=self._provider,
                api_key=self._token.get_secret_value(),
                timeout=self._timeout_seconds,
            ).feature_extraction(text, model=self.model)

        try:
            values = await asyncio.wait_for(
                asyncio.to_thread(request), timeout=self._timeout_seconds + 5,
            )
        except Exception:
            return None
        return [float(value) for value in values]

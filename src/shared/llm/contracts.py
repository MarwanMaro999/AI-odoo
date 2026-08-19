"""Provider-neutral contracts for text generation."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class GeneratedText:
    """Text returned by a configured model provider."""

    text: str
    provider: str
    model: str


class TextGenerator(Protocol):
    """The one interface used by questionnaire business logic."""

    async def generate(self, prompt: str) -> GeneratedText: ...

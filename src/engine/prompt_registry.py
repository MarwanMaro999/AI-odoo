"""Private prompt resolution for registered Datum Engine skills."""

from pathlib import Path
from urllib.parse import urlparse

from src.engine.registry import SkillRegistryError


class PromptRegistry:
    """Resolve an opaque prompt reference without exposing instruction text."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def resolve(self, reference: str | None) -> str:
        if not reference:
            raise SkillRegistryError("skill_instruction_missing")
        parsed = urlparse(reference)
        if parsed.scheme != "prompt-registry" or not parsed.netloc or not parsed.path:
            raise SkillRegistryError("skill_instruction_reference_invalid")
        version = parsed.path.strip("/")
        if "/" in version or ".." in parsed.netloc or ".." in version:
            raise SkillRegistryError("skill_instruction_reference_invalid")
        path = self._root / parsed.netloc / f"{version}.txt"
        if not path.is_file():
            raise SkillRegistryError("skill_instruction_not_found")
        instruction = path.read_text(encoding="utf-8").strip()
        if not instruction:
            raise SkillRegistryError("skill_instruction_invalid")
        return instruction

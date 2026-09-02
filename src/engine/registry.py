"""External opaque skill registry.  Prompt payloads never leave this service."""

import logging
from pathlib import Path
from typing import Any

import yaml

from src.engine.schemas import PublicSkillDefinition, SkillKind


_logger = logging.getLogger(__name__)


class SkillRegistryError(ValueError):
    pass


class SkillRegistry:
    def __init__(self, registry_path: Path) -> None:
        self._registry_path = registry_path
        # Log skill discovery at startup for diagnostics
        if registry_path.is_dir():
            discovered = []
            for path in sorted(registry_path.glob("*.yaml")):
                try:
                    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
                    if isinstance(raw, dict) and "identifier" in raw:
                        discovered.append(f"{raw['identifier']} v{raw.get('version', '?')}")
                except Exception:
                    pass
            _logger.info(
                "datum_skill_registry_initialized registry_path=%s discovered_skills=%s",
                registry_path,
                ", ".join(discovered) or "(none)"
            )

    def load(self, identifier: str, version: str) -> tuple[PublicSkillDefinition, dict[str, Any]]:
        path = self._registry_path / f"{identifier}.yaml"
        if not path.is_file():
            _logger.error(
                "datum_skill_not_found identifier=%s version=%s registry_path=%s",
                identifier, version, self._registry_path
            )
            raise SkillRegistryError("skill_not_found")
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise SkillRegistryError("skill_registry_invalid")
        if raw.get("version") != version:
            raise SkillRegistryError("skill_version_not_found")
        if "consumes" in raw:
            return self._load_architecture_schema(raw)
        public = PublicSkillDefinition.model_validate({
            key: raw[key]
            for key in ("identifier", "version", "kind", "accepted_source_material", "outputs")
        } | {
            "prerequisite_document_types": raw.get("prerequisite_document_types", []),
            "issues_verdict": raw.get("issues_verdict", raw.get("kind") == SkillKind.AUDITOR),
        })
        # The opaque payload may contain an instruction and tool settings; no caller receives it.
        return public, dict(raw.get("payload", {}))

    @staticmethod
    def _load_architecture_schema(raw: dict[str, Any]) -> tuple[PublicSkillDefinition, dict[str, Any]]:
        """Adapt the Architecture Rules registry shape to the local engine contract.

        The adapter keeps prompt text out of YAML. A real prompt resolver can later
        resolve ``instruction_ref`` without changing the Odoo-facing API.
        """
        consumes = raw.get("consumes", [])
        if not isinstance(consumes, list):
            raise SkillRegistryError("skill_registry_invalid")
        accepted = [str(item["type"]) for item in consumes if isinstance(item, dict) and item.get("type")]
        mandatory = [
            str(item["type"])
            for item in consumes
            if isinstance(item, dict) and item.get("type") and item.get("mandatory", False)
        ]
        outputs = []
        for item in raw.get("produces", []):
            if not isinstance(item, dict) or not item.get("document_type"):
                continue
            document_type = str(item["document_type"])
            # Odoo's stable document key remains scope_of_work; the architecture
            # shorthand "sow" is only an external registry label.
            if document_type == "sow":
                document_type = "scope_of_work"
            outputs.append({
                "document_type": document_type,
                "distribution_class": item.get("distribution_class", "internal_only"),
            })
        public = PublicSkillDefinition.model_validate({
            "identifier": raw["identifier"],
            "version": raw["version"],
            "kind": raw["kind"],
            "accepted_source_material": accepted,
            "outputs": outputs,
            "prerequisite_document_types": [
                "scope_of_work" if item.get("document_type") == "sow" else item.get("document_type")
                for item in raw.get("prerequisites", [])
                if isinstance(item, dict) and item.get("document_type")
            ],
            "issues_verdict": raw.get("issues_verdict", raw.get("kind") == SkillKind.AUDITOR),
        })
        placeholder = raw.get("placeholder_instruction", {})
        payload = {
            "instruction_ref": raw.get("instruction_ref"),
            "mandatory_source_material": mandatory,
            "prerequisites": raw.get("prerequisites", []),
            "reviewer": raw.get("reviewer"),
            "raw_registry_metadata": {
                key: raw.get(key)
                for key in ("guards", "resolution_routes", "finding_attributes", "lineage", "versioning", "reviewer")
                if key in raw
            },
        }
        if isinstance(placeholder, dict) and placeholder.get("active"):
            payload["placeholder_active"] = True
        return public, payload

    def list_public(self) -> list[PublicSkillDefinition]:
        """Return safe metadata without exposing instructions or provider settings."""
        definitions: list[PublicSkillDefinition] = []
        for path in self._registry_path.glob("*.yaml"):
            try:
                raw = yaml.safe_load(path.read_text(encoding="utf-8"))
                if not isinstance(raw, dict):
                    continue
                definition, _ = self.load(str(raw["identifier"]), str(raw["version"]))
                definitions.append(definition)
            except (KeyError, SkillRegistryError, ValueError):
                continue
        return definitions

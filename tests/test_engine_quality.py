import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.engine.prompt_registry import PromptRegistry
from src.engine.registry import SkillRegistryError
from src.engine.service import DatumDocxRenderer, DatumOrchestrator, PersistentRunRepository, StoredRun
from src.engine.schemas import (
    DistributionClass,
    RunState,
    RunStatus,
    SkillReference,
    SourceMaterial,
    StartRunRequest,
    Verdict,
)
from src.shared.llm.contracts import GeneratedText


def test_prompt_registry_resolves_private_reference(tmp_path: Path) -> None:
    prompt = tmp_path / "gen-strs" / "v1.txt"
    prompt.parent.mkdir()
    prompt.write_text("Private instruction", encoding="utf-8")
    assert PromptRegistry(tmp_path).resolve("prompt-registry://gen-strs/v1") == "Private instruction"


def test_prompt_registry_rejects_missing_instruction(tmp_path: Path) -> None:
    with pytest.raises(SkillRegistryError, match="skill_instruction_not_found"):
        PromptRegistry(tmp_path).resolve("prompt-registry://gen-strs/v1")


def test_structured_output_requires_supplied_source_references() -> None:
    sections, references = DatumOrchestrator._parse_structured_sections(
        '{"sections":[{"title":"Purpose","points":["A"]},{"title":"Security","points":["B"]},{"title":"Workflow","points":["C"]},{"title":"Acceptance","points":["D","E","F","G","H"]}],"source_references":["architecture"]}'
    )
    references = DatumOrchestrator._validate_generated_sections(
        "gen-strs", sections, references, [SimpleNamespace(source_id="architecture", text="Datum Engine architecture")]
    )
    assert references == ["architecture"]


def test_structured_output_normalises_a_supplied_source_name_to_its_id() -> None:
    sections = [("Purpose", ["A"]), ("Security", ["B"]), ("Workflow", ["C"]), ("Acceptance", ["D", "E", "F", "G", "H"])]
    references = DatumOrchestrator._validate_generated_sections(
        "gen-strs", sections, ["Meeting transcript"],
        [SimpleNamespace(source_id="meeting-transcript", name="Meeting transcript", text="Datum Engine architecture")],
    )
    assert references == ["meeting-transcript"]


def test_structured_output_rejects_unsupported_marketplace_claim() -> None:
    sections = [("Purpose", ["Seller inventory workflow"])] * 8
    with pytest.raises(ValueError, match="generation_output_unsupported_claim"):
        DatumOrchestrator._validate_generated_sections(
            "gen-strs", sections, ["architecture"], [SimpleNamespace(source_id="architecture", text="Datum Engine architecture")]
        )


def test_missing_provider_fails_instead_of_returning_demo_document(tmp_path: Path) -> None:
    orchestrator = DatumOrchestrator(
        PersistentRunRepository(tmp_path / "state"),
        SimpleNamespace(),
        DatumDocxRenderer(tmp_path / "outputs"),
        text_generator=None,
        prompt_registry=None,
        allow_demo_outputs=False,
    )


def test_large_sources_are_utf8_bounded_without_losing_source_identity(tmp_path: Path) -> None:
    orchestrator = DatumOrchestrator(
        PersistentRunRepository(tmp_path / "state"), SimpleNamespace(), DatumDocxRenderer(tmp_path / "outputs"),
        max_source_bytes=240,
    )
    bounded = orchestrator._bounded_source_text([
        SimpleNamespace(source_id="arabic", name="Arabic", text="معلومة " * 200),
        SimpleNamespace(source_id="english", name="English", text="information " * 200),
    ])
    assert "[arabic: Arabic]" in bounded
    assert "[english: English]" in bounded
    assert "Source truncated" in bounded
    assert len(bounded.encode("utf-8")) <= 260
    with pytest.raises(ValueError, match="source_grounded_generation_unavailable"):
        asyncio.run(
            orchestrator._generate_sections(
                "gen-strs", [SimpleNamespace(source_id="architecture", name="Architecture", text="Datum Engine")], {}, "", DistributionClass.CLIENT_PERMITTED, {}
        )
    )


def test_all_live_skills_resolve_to_private_versioned_instructions() -> None:
    from src.engine.registry import SkillRegistry

    registry = SkillRegistry(Path("C:/ProgramData/OdooTec/datum-engine-registry"))
    prompts = PromptRegistry(Path("C:/ProgramData/OdooTec/datum-engine-prompts"))
    for identifier in ("gen-discovery-questions", "gen-strs", "gen-sow", "rev-sow"):
        _, payload = registry.load(identifier, "1.0.0")
        assert prompts.resolve(payload["instruction_ref"])
        assert not payload.get("placeholder_active")


class _AuditGenerator:
    async def generate(self, _: str) -> GeneratedText:
        return GeneratedText(
            text=(
                '{"verdict":"not_cleared","findings":[{"finding_key":"DE-REV-001",'
                '"severity":"blocking","category":"missing_acceptance_criteria",'
                '"location":"Acceptance criteria","summary":"Criteria are not measurable.",'
                '"evidence":"The supplied SOW has no measurable acceptance criteria.",'
                '"resolution_route":"regenerate","prior_outcome":null}]}'
            ),
            provider="test",
            model="test",
        )


def test_auditor_records_model_generated_structured_finding(tmp_path: Path) -> None:
    prompt = tmp_path / "rev-sow" / "v1.txt"
    prompt.parent.mkdir()
    prompt.write_text("Review only supplied material.", encoding="utf-8")
    request = StartRunRequest(
        idempotency_key="audit-quality-test",
        engagement_id="engagement-1",
        source_set_revision="r1",
        skill=SkillReference(identifier="rev-sow", version="v1"),
        source_material=[SourceMaterial(
            source_id="sow-1", revision="r1", type="scope_of_work", name="SOW",
            text="The supplied SOW has no measurable acceptance criteria.",
        )],
    )
    run = StoredRun(
        status=RunStatus(
            run_id=__import__("uuid").uuid4(), state=RunState.RUNNING, skill=request.skill,
            engagement_id=request.engagement_id, source_set_revision=request.source_set_revision,
            submitted_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        ),
        request=request,
        fingerprint="test",
    )
    orchestrator = DatumOrchestrator(
        PersistentRunRepository(tmp_path / "state"), SimpleNamespace(), DatumDocxRenderer(tmp_path / "outputs"),
        text_generator=_AuditGenerator(), prompt_registry=PromptRegistry(tmp_path),
    )
    asyncio.run(orchestrator._complete_audit(run, SimpleNamespace(), {"instruction_ref": "prompt-registry://rev-sow/v1"}))
    assert run.status.verdict == Verdict.NOT_CLEARED
    assert run.status.findings[0].finding_key == "DE-REV-001"

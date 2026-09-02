"""Regression coverage for durable workflow identities."""

from uuid import uuid4

from src.engine.sessions import EngineSessionStore
from src.engine.schemas import SourceMaterial, StartRunRequest, SkillReference


def _request(*, skill: str, workflow: str | None = None) -> StartRunRequest:
    return StartRunRequest(
        idempotency_key=str(uuid4()),
        engagement_id="42",
        record_id=42,
        workflow=workflow,
        source_set_revision="1",
        skill=SkillReference(identifier=skill, version="1.0.0"),
        source_material=[
            SourceMaterial(
                source_id="approved-strs",
                revision="1",
                type="approved_requirements_specification",
                name="Approved StRS",
                text="Approved requirements.",
            )
        ],
    )


def test_document_workflow_is_optional_and_validated() -> None:
    request = _request(skill="gen-sow", workflow="sow_workflow")

    assert request.workflow == "sow_workflow"
    assert EngineSessionStore._workflow_identity(request) == "sow_workflow"


def test_document_workflow_accepts_existing_hyphenated_skill_identifier() -> None:
    request = _request(
        skill="gen-discovery-questions",
        workflow="gen-discovery-questions",
    )

    assert request.workflow == "gen-discovery-questions"
    assert EngineSessionStore._workflow_identity(request) == "gen-discovery-questions"


def test_legacy_document_request_keeps_skill_based_workflow_fallback() -> None:
    request = _request(skill="gen-sow")

    assert request.workflow is None
    assert EngineSessionStore._workflow_identity(request) == "gen-sow"

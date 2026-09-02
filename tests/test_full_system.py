"""End-to-end HTTP coverage for the Odoo Chatter AI workflow.

These tests exercise the real FastAPI router, service, JSON repository and
document renderer.  Only the durable database/session boundary and LLM provider
are replaced, keeping the suite deterministic and independent of paid services.
"""

import asyncio
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from pydantic import SecretStr

from src.chatter_ai.schemas import ChatCommand, ChatterAIStartRequest, ContextUnit
from src.chatter_ai.service import ChatProvider, ChatterAIOrchestrator
from src.chatter_ai.sessions import PreparedChatterSession
from src.core.config import Settings
from src.core.exceptions import QuestionnaireProviderUnavailable
from src.core.prompt_security import PromptSecurityRejected
from src.discovery_questionnaire.services.questionnaire_processor import QuestionnaireProcessor
from src.discovery_questionnaire.services.questionnaire_registry import QuestionnaireRegistry
from src.engine.prompt_registry import PromptRegistry
from src.engine.registry import SkillRegistry
from src.engine.schemas import SkillReference, SourceMaterial, StartRunRequest
from src.engine.service import DatumDocxRenderer, DatumOrchestrator
from src.engine.sessions import PreparedEngineSession
from src.main import create_application
from src.shared.llm.contracts import GeneratedText
from src.shared.rendering.questionnaire_pdf_renderer import QuestionnairePdfRenderer


class QueueStub:
    """Records asynchronous dispatches without starting an external worker."""

    def __init__(self) -> None:
        self.run_ids: list[UUID] = []

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def enqueue(self, run_id: UUID) -> None:
        self.run_ids.append(run_id)

    async def ensure_enqueued(self, run_id: UUID) -> None:
        if run_id not in self.run_ids:
            self.run_ids.append(run_id)


class SessionStub:
    def __init__(self) -> None:
        self.session_id = uuid4()
        self.calls = 0

    async def prepare(self, request: ChatterAIStartRequest) -> PreparedChatterSession:
        self.calls += 1
        return PreparedChatterSession(self.session_id, self.calls == 1, request.context)


class RejectingSessionStub:
    async def prepare(self, _: ChatterAIStartRequest) -> PreparedChatterSession:
        raise PromptSecurityRejected(())


class EngineSessionStub:
    def __init__(self) -> None:
        self.session_id = uuid4()

    async def prepare(self, request: StartRunRequest) -> PreparedEngineSession:
        return PreparedEngineSession(self.session_id, request.source_material)


class QuestionnaireProvider:
    async def generate(self, prompt: str) -> GeneratedText:
        assert "Nile Delta Distribution" in prompt
        return GeneratedText(
            "1. Which sales-order approvals are required?\n"
            "2. Who owns the pilot acceptance decision?\n"
            "3. What is the confirmed go-live date?",
            "test-provider",
            "test-model",
            120,
            42,
        )


class UnavailableProvider:
    async def generate(self, _: str) -> GeneratedText:
        raise QuestionnaireProviderUnavailable("provider unavailable")


class StructuredDocumentProvider:
    async def generate(self, prompt: str) -> GeneratedText:
        assert "Approved StRS" in prompt
        return GeneratedText(
            '{"sections":['
            '{"title":"Objective","points":["Deliver the approved Odoo scope.","Measure pilot acceptance."]},'
            '{"title":"Scope","points":["Configure Sales.","Configure Inventory."]},'
            '{"title":"Responsibilities","points":["Client supplies decisions.","OdooTec configures workflows."]},'
            '{"title":"Acceptance","points":["Run UAT.","Approve pilot results."]}'
            '],'
            '"source_references":["approved-strs"]}',
            "test-provider",
            "test-model",
        )


class BilingualQuestionnaireProvider:
    async def generate(self, prompt: str) -> GeneratedText:
        assert "Nile Delta Distribution" in prompt
        return GeneratedText(
            "# Business objectives\n1. What is the measurable pilot outcome?\n\n"
            "# \\u0623\\u0647\\u062f\\u0627\\u0641 \\u0627\\u0644\\u0639\\u0645\\u0644\n"
            "1. \\u0645\\u0627 \\u0647\\u064a \\u0646\\u062a\\u064a\\u062c\\u0629 \\u0627\\u0644\\u0645\\u0631\\u062d\\u0644\\u0629 \\u0627\\u0644\\u062a\\u062c\\u0631\\u064a\\u0628\\u064a\\u0629 \\u0627\\u0644\\u0642\\u0627\\u0628\\u0644\\u0629 \\u0644\\u0644\\u0642\\u064a\\u0627\\u0633\\u061f",
            "test-provider",
            "test-model",
        )


def request(*, key: str | None = None, command: ChatCommand = ChatCommand.QUESTION) -> ChatterAIStartRequest:
    return ChatterAIStartRequest(
        idempotency_key=key or f"full-system-{uuid4()}",
        record_model="datum.engagement",
        record_id=42,
        requester_id=7,
        command=command,
        user_message="Create the discovery questions for the engagement.",
        context=[ContextUnit(
            source_id="record-42",
            kind="record",
            title="Nile Delta Distribution",
            text="The customer needs Odoo sales, inventory, and accounting. Go-live is 1 January 2027.",
        )],
    )


def application(
    tmp_path: Path,
    sessions: object | None = None,
    *,
    engine_sessions: object | None = None,
    registry_path: Path | None = None,
):
    app = create_application(Settings(
        datum_engine_api_auth_token=SecretStr("test-token"),
        chatter_ai_state_dir=tmp_path / "chatter-state",
        engine_state_dir=tmp_path / "engine-state",
        engine_output_dir=tmp_path / "outputs",
        dev_output_dir=tmp_path / "questionnaire-output",
        registry_path=registry_path,
    ))
    queue = QueueStub()
    chatter_container = app.state.chatter_ai_container
    app.state.chatter_ai_container = replace(chatter_container, queue=queue)
    chatter_container.service._queue = queue
    chatter_container.service._sessions = sessions or SessionStub()
    engine_container = app.state.engine_container
    engine_queue = QueueStub()
    app.state.engine_container = replace(engine_container, queue=engine_queue)
    engine_container.service._queue = engine_queue
    if engine_sessions is not None:
        engine_container.service._sessions = engine_sessions
    return app, queue


def auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


def write_engine_registry(root: Path) -> tuple[Path, Path]:
    registry = root / "engine-registry"
    prompts = root / "prompts"
    registry.mkdir()
    prompts.joinpath("test-document").mkdir(parents=True)
    registry.joinpath("test-document.yaml").write_text(
        """identifier: test-document
version: \"1.0.0\"
kind: generator
accepted_source_material:
  - approved_requirements_specification
outputs:
  - document_type: test_document
    distribution_class: client_permitted
payload:
  instruction_ref: prompt-registry://test-document/v1
""",
        encoding="utf-8",
    )
    prompts.joinpath("test-document", "v1.txt").write_text(
        "Generate only from the supplied source material.", encoding="utf-8",
    )
    return registry, prompts


def write_questionnaire_registry(root: Path) -> Path:
    registry = root / "questionnaire-registry"
    registry.mkdir()
    registry.joinpath("discovery-questionnaire.yaml").write_text(
        """identifier: discovery-questionnaire
version: \"1.0.0\"
kind: generator
accepted_source_material:
  - type: prospect_context
    required: true
outputs:
  - document_type: discovery_questionnaire
    distribution_class: client_permitted
questions_per_section: 2
instruction: Keep the response source-grounded.
""",
        encoding="utf-8",
    )
    return registry


def test_p0_odoo_chatter_request_reaches_document_output(tmp_path: Path) -> None:
    app, queue = application(tmp_path)
    payload = request()

    with TestClient(app) as client:
        accepted = client.post("/api/v1/chatter-ai/runs", json=payload.model_dump(mode="json"), headers=auth_headers())
        assert accepted.status_code == 202
        run_id = UUID(accepted.json()["run_id"])
        assert queue.run_ids == [run_id]

        repository = app.state.chatter_ai_container.service._repository
        orchestrator = ChatterAIOrchestrator(
            repository,
            [ChatProvider("primary", QuestionnaireProvider(), 100_000)],
            DatumDocxRenderer(tmp_path / "outputs"),
        )
        asyncio.run(orchestrator.process(run_id))

        completed = client.get(f"/api/v1/chatter-ai/runs/{run_id}", headers=auth_headers())
        assert completed.status_code == 200
        status = completed.json()
        assert status["state"] == "succeeded"
        assert status["session_id"] == accepted.json()["session_id"]
        assert status["context_source_count"] == 1
        assert status["provider"] == "test-provider"
        assert status["artifact_document_type"] == "discovery_questionnaire"
        assert status["artifact_filename"].endswith(".docx")

        artifact = client.get(status["artifact_download_url"], headers=auth_headers())
        assert artifact.status_code == 200
        assert artifact.headers["content-type"].startswith(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
        assert artifact.content.startswith(b"PK")


def test_p0_duplicate_delivery_reuses_one_run_and_session(tmp_path: Path) -> None:
    sessions = SessionStub()
    app, queue = application(tmp_path, sessions)
    payload = request(key="odoo-chatter-idempotency")

    with TestClient(app) as client:
        first = client.post("/api/v1/chatter-ai/runs", json=payload.model_dump(mode="json"), headers=auth_headers())
        second = client.post("/api/v1/chatter-ai/runs", json=payload.model_dump(mode="json"), headers=auth_headers())

    assert first.status_code == second.status_code == 202
    assert first.json()["run_id"] == second.json()["run_id"]
    assert first.json()["session_id"] == second.json()["session_id"]
    assert sessions.calls == 1
    assert len(queue.run_ids) == 1


def test_p1_provider_failure_falls_back_after_api_acceptance(tmp_path: Path) -> None:
    app, _ = application(tmp_path)
    payload = request(command=ChatCommand.CHAT)

    with TestClient(app) as client:
        accepted = client.post("/api/v1/chatter-ai/runs", json=payload.model_dump(mode="json"), headers=auth_headers())
        run_id = UUID(accepted.json()["run_id"])
        repository = app.state.chatter_ai_container.service._repository
        orchestrator = ChatterAIOrchestrator(
            repository,
            [
                ChatProvider("unavailable", UnavailableProvider(), 100_000),
                ChatProvider("fallback", QuestionnaireProvider(), 100_000),
            ],
            DatumDocxRenderer(tmp_path / "outputs"),
        )
        asyncio.run(orchestrator.process(run_id))
        response = client.get(f"/api/v1/chatter-ai/runs/{run_id}", headers=auth_headers())

    assert response.status_code == 200
    status = response.json()
    assert status["state"] == "succeeded"
    assert [attempt["outcome"] for attempt in status["provider_attempts"]] == ["failed", "succeeded"]


def test_p1_authentication_and_invalid_payloads_are_rejected(tmp_path: Path) -> None:
    app, _ = application(tmp_path)
    payload = request().model_dump(mode="json")

    with TestClient(app) as client:
        unauthorized = client.post("/api/v1/chatter-ai/runs", json=payload)
        invalid = client.post(
            "/api/v1/chatter-ai/runs",
            json={**payload, "record_id": 0, "unexpected": "field"},
            headers=auth_headers(),
        )
        malformed = client.post(
            "/api/v1/chatter-ai/runs",
            content="{not-json",
            headers={**auth_headers(), "Content-Type": "application/json"},
        )

    assert unauthorized.status_code == 401
    assert invalid.status_code == 422
    assert malformed.status_code == 422


def test_p1_injection_rejection_returns_no_internal_details(tmp_path: Path) -> None:
    app, _ = application(tmp_path, RejectingSessionStub())

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/chatter-ai/runs",
            json=request().model_dump(mode="json"),
            headers=auth_headers(),
        )

    assert response.status_code == 422
    assert response.json()["detail"] == "Unsafe AI instructions were rejected"
    assert "traceback" not in response.text.lower()


def test_p0_document_engine_request_reaches_versioned_docx_output(tmp_path: Path) -> None:
    registry_path, prompt_path = write_engine_registry(tmp_path)
    app, _ = application(
        tmp_path,
        engine_sessions=EngineSessionStub(),
        registry_path=registry_path,
    )
    payload = StartRunRequest(
        idempotency_key="document-engine-happy-path",
        engagement_id="42",
        record_id=42,
        source_set_revision="1",
        skill=SkillReference(identifier="test-document", version="1.0.0"),
        source_material=[SourceMaterial(
            source_id="approved-strs",
            revision="1",
            type="approved_requirements_specification",
            name="Approved StRS",
            text="The approved scope covers Odoo Sales and Inventory.",
        )],
    )

    with TestClient(app) as client:
        accepted = client.post("/api/v1/runs", json=payload.model_dump(mode="json"), headers=auth_headers())
        assert accepted.status_code == 202
        run_id = UUID(accepted.json()["run_id"])

        repository = app.state.engine_container.service._repository
        processor = DatumOrchestrator(
            repository,
            SkillRegistry(registry_path),
            DatumDocxRenderer(tmp_path / "outputs"),
            text_generator=StructuredDocumentProvider(),
            prompt_registry=PromptRegistry(prompt_path),
        )
        asyncio.run(processor.process(run_id))

        completed = client.get(f"/api/v1/runs/{run_id}", headers=auth_headers())
        assert completed.status_code == 200
        status = completed.json()
        assert status["state"] == "succeeded"
        assert status["session_id"]
        assert len(status["outputs"]) == 1
        output = status["outputs"][0]
        assert output["filename"].endswith("_En_test_document_v1.docx")
        assert output["source_references"] == ["approved-strs"]

        artifact = client.get(output["download_url"], headers=auth_headers())
        assert artifact.status_code == 200
        assert artifact.content.startswith(b"PK")
        missing = client.get(f"/api/v1/runs/{run_id}/outputs/not-created.docx", headers=auth_headers())
        assert missing.status_code == 404


def test_p1_document_engine_rejects_empty_baseline_before_dispatch(tmp_path: Path) -> None:
    app, queue = application(tmp_path, engine_sessions=EngineSessionStub())
    payload = {
        "idempotency_key": "empty-baseline",
        "engagement_id": "42",
        "source_set_revision": "1",
        "skill": {"identifier": "gen-sow", "version": "1.0.0"},
        "source_material": [],
    }

    with TestClient(app) as client:
        response = client.post("/api/v1/runs", json=payload, headers=auth_headers())

    assert response.status_code == 422
    assert "baseline_source_material_required" in response.text
    assert queue.run_ids == []


def test_p0_questionnaire_request_reaches_pdf_and_hides_private_instruction(tmp_path: Path) -> None:
    registry_path = write_questionnaire_registry(tmp_path)
    app, _ = application(tmp_path, registry_path=registry_path)
    queue = QueueStub()
    container = app.state.questionnaire_container
    app.state.questionnaire_container = replace(container, queue=queue)
    container.service._queue = queue
    payload = {
        "questionnaire_identifier": "discovery-questionnaire",
        "idempotency_key": "questionnaire-happy-path",
        "customer": {"name": "Nile Delta Distribution", "country": "Egypt"},
        "source_material": [{
            "source_id": "prospect-context",
            "type": "prospect_context",
            "text": "The customer needs an Odoo rollout and a measurable pilot.",
        }],
        "options": {"languages": ["ar", "en"], "web_research_enabled": False},
    }

    with TestClient(app) as client:
        accepted = client.post("/api/v1/discovery-questionnaire/runs", json=payload)
        assert accepted.status_code == 202
        run_id = UUID(accepted.json()["questionnaire_run_id"])
        assert queue.run_ids == [run_id]

        processor = QuestionnaireProcessor(
            container.service._repository,
            QuestionnaireRegistry(registry_path),
            BilingualQuestionnaireProvider(),
            SimpleNamespace(),
            QuestionnairePdfRenderer(tmp_path / "questionnaire-output"),
            security_gate=None,
        )
        asyncio.run(processor.process(run_id))

        status = client.get(f"/api/v1/discovery-questionnaire/runs/{run_id}")
        assert status.status_code == 200
        result = status.json()
        assert result["state"] == "succeeded"
        assert result["outputs"][0]["media_type"] == "application/pdf"
        document = client.get(result["outputs"][0]["download_url"])
        assert document.status_code == 200
        assert document.content.startswith(b"%PDF")

        configuration = client.get("/api/v1/discovery-questionnaire/configuration/discovery-questionnaire")
        assert configuration.status_code == 200
        assert "instruction" not in configuration.json()
        assert "source-grounded" not in configuration.text


def test_p1_upload_handles_arabic_text_and_rejects_empty_or_unsupported_files(tmp_path: Path) -> None:
    app, _ = application(tmp_path)
    arabic_text = "\\u0645\\u0644\\u062e\\u0635 \\u0627\\u0644\\u0645\\u0634\\u0631\\u0648\\u0639".encode("utf-8")

    with TestClient(app) as client:
        extracted = client.post(
            "/api/v1/discovery-questionnaire/source-files/extract",
            files={"file": ("brief.txt", arabic_text, "text/plain")},
            headers=auth_headers(),
        )
        empty = client.post(
            "/api/v1/discovery-questionnaire/source-files/extract",
            files={"file": ("empty.txt", b"", "text/plain")},
            headers=auth_headers(),
        )
        unsupported = client.post(
            "/api/v1/discovery-questionnaire/source-files/extract",
            files={"file": ("payload.exe", b"not a document", "application/octet-stream")},
            headers=auth_headers(),
        )

    assert extracted.status_code == 200
    assert extracted.json()["text"] == arabic_text.decode("utf-8")
    assert empty.status_code == 422
    assert unsupported.status_code == 422

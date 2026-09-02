"""Focused tests for the Odoo chatter AI FastAPI contract."""

from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import SecretStr

from src.chatter_ai.schemas import ChatCommand, ChatterAIStartRequest, ContextUnit
from src.chatter_ai.service import ChatProvider, ChatRunRepository, ChatterAIOrchestrator
from src.chatter_ai.sessions import PreparedChatterSession, ReservedChatterSession
from src.core.config import Settings
from src.core.prompt_security import PromptSecurityRejected
from src.engine.service import DatumDocxRenderer
from src.main import create_application
from src.shared.llm.contracts import GeneratedText


def _request(command: ChatCommand = ChatCommand.CHAT) -> ChatterAIStartRequest:
    return ChatterAIStartRequest(
        idempotency_key="chat-test-1",
        record_model="crm.lead",
        record_id=42,
        requester_id=7,
        command=command,
        user_message="Please help.",
        context=[ContextUnit(source_id="record-42", kind="record", title="Test lead", text="Known context")],
    )


class _Available:
    async def generate(self, prompt: str) -> GeneratedText:
        assert "Known context" in prompt
        text = (
            "1. What is the current process?\n"
            "2. Who approves the work?\n"
            "3. What does success look like?"
            if "discovery questionnaire" in prompt.lower()
            else "A structured document response."
        )
        return GeneratedText(text=text, provider="test", model="test-model")


class _Unavailable:
    async def generate(self, _: str) -> GeneratedText:
        from src.core.exceptions import QuestionnaireProviderUnavailable

        raise QuestionnaireProviderUnavailable("rate limit reached")


class _SessionStoreStub:
    def __init__(self) -> None:
        self.calls = 0
        self.session_id = __import__("uuid").uuid4()

    async def reserve(self, _request: ChatterAIStartRequest) -> ReservedChatterSession:
        self.calls += 1
        return ReservedChatterSession(self.session_id, self.calls == 1)

    async def prepare(self, request: ChatterAIStartRequest) -> PreparedChatterSession:
        return PreparedChatterSession(self.session_id, False, request.context)


class _UsageStoreStub:
    def __init__(self) -> None:
        self.calls = []

    async def record_assistant_turn(self, *args) -> None:
        self.calls.append(args)


class _BrokenUsageStoreStub:
    async def record_assistant_turn(self, *_args) -> None:
        raise ValueError("telemetry failure")


class _RejectingSessionStoreStub:
    async def reserve(self, _: ChatterAIStartRequest) -> ReservedChatterSession:
        raise PromptSecurityRejected(())

    async def prepare(self, _: ChatterAIStartRequest) -> PreparedChatterSession:
        raise PromptSecurityRejected(())


class _QueueStub:
    def __init__(self) -> None:
        self.run_ids = []

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def enqueue(self, run_id) -> None:
        self.run_ids.append(run_id)


def _replace_chatter_queue(app) -> _QueueStub:
    queue = _QueueStub()
    container = app.state.chatter_ai_container
    app.state.chatter_ai_container = replace(container, queue=queue)
    container.service._queue = queue
    return queue


def _replace_engine_queue(app) -> _QueueStub:
    queue = _QueueStub()
    app.state.engine_container = replace(app.state.engine_container, queue=queue)
    return queue


def test_chatter_run_falls_back_to_next_provider(tmp_path: Path) -> None:
    repository = ChatRunRepository(tmp_path)
    run, _ = repository.create_or_get(_request())
    orchestrator = ChatterAIOrchestrator(
        repository,
        [ChatProvider("first", _Unavailable(), 100_000), ChatProvider("second", _Available(), 100_000)],
        DatumDocxRenderer(tmp_path / "outputs"),
    )

    import asyncio

    asyncio.run(orchestrator.process(run.status.run_id))
    status = repository.get(run.status.run_id).status
    assert status.state == "succeeded"
    assert status.provider == "test"
    assert [item.outcome for item in status.provider_attempts] == ["failed", "succeeded"]


def test_chatter_run_records_provider_token_usage_when_a_session_is_available(tmp_path: Path) -> None:
    import asyncio

    class _UsageAvailable(_Available):
        async def generate(self, prompt: str) -> GeneratedText:
            response = await super().generate(prompt)
            return GeneratedText(response.text, response.provider, response.model, 123, 45)

    repository = ChatRunRepository(tmp_path)
    run, _ = repository.create_or_get(_request(ChatCommand.QUESTION), __import__("uuid").uuid4())
    usage_store = _UsageStoreStub()
    orchestrator = ChatterAIOrchestrator(
        repository,
        [ChatProvider("test", _UsageAvailable(), 100_000)],
        DatumDocxRenderer(tmp_path / "outputs"),
        sessions=usage_store,
    )

    asyncio.run(orchestrator.process(run.status.run_id))

    status = repository.get(run.status.run_id).status
    assert (status.input_tokens, status.output_tokens) == (123, 45)
    assert len(usage_store.calls) == 1
    assert usage_store.calls[0][-1] == 1


def test_chatter_run_completes_when_session_telemetry_fails(tmp_path: Path) -> None:
    import asyncio

    repository = ChatRunRepository(tmp_path)
    run, _ = repository.create_or_get(_request(ChatCommand.QUESTION), __import__("uuid").uuid4())
    orchestrator = ChatterAIOrchestrator(
        repository,
        [ChatProvider("test", _Available(), 100_000)],
        DatumDocxRenderer(tmp_path / "outputs"),
        sessions=_BrokenUsageStoreStub(),
    )

    asyncio.run(orchestrator.process(run.status.run_id))

    status = repository.get(run.status.run_id).status
    assert status.state == "succeeded"
    assert status.artifact_filename


def test_chatter_api_requires_bearer_token() -> None:
    app = create_application(Settings(datum_engine_api_auth_token=SecretStr("test-token")))
    session_store = _SessionStoreStub()
    app.state.chatter_ai_container.service._sessions = session_store
    _replace_chatter_queue(app)
    _replace_engine_queue(app)
    idempotency_key = "api-session-test-%s" % __import__("uuid").uuid4()
    with TestClient(app) as client:
        unauthorized = client.post("/api/v1/chatter-ai/runs", json=_request().model_dump(mode="json"))
        authorized = client.post(
            "/api/v1/chatter-ai/runs",
            json=_request().model_copy(update={"idempotency_key": idempotency_key}).model_dump(mode="json"),
            headers={"Authorization": "Bearer test-token"},
        )
    assert unauthorized.status_code == 401
    assert authorized.status_code == 202
    assert authorized.json()["session_id"] == str(session_store.session_id)


def test_chatter_api_returns_safe_validation_error_for_rejected_instructions() -> None:
    app = create_application(Settings(datum_engine_api_auth_token=SecretStr("test-token")))
    app.state.chatter_ai_container.service._sessions = _RejectingSessionStoreStub()
    _replace_chatter_queue(app)
    _replace_engine_queue(app)
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/chatter-ai/runs",
            json=_request().model_copy(update={
                "idempotency_key": "security-reject-%s" % __import__("uuid").uuid4(),
            }).model_dump(mode="json"),
            headers={"Authorization": "Bearer test-token"},
        )

    assert response.status_code == 422
    assert response.json()["detail"] == "Unsafe AI instructions were rejected"


def test_fallback_context_mentions_every_source() -> None:
    request = _request()
    request.context.append(ContextUnit(source_id="attachment-1", kind="attachment", title="Evidence", text="x" * 50_000))
    rendered = ChatterAIOrchestrator._render_context(request, 1_000)
    assert "record-42" in rendered
    assert "attachment-1" in rendered
    assert "Source reduced for fallback context limit" in rendered


def test_attachment_requests_prefer_the_full_context_provider(tmp_path: Path) -> None:
    request = _request()
    request.context.append(
        ContextUnit(source_id="attachment-1", kind="attachment", title="Brief", text="Document evidence")
    )
    orchestrator = ChatterAIOrchestrator(
        ChatRunRepository(tmp_path),
        [ChatProvider("compact", _Available(), 256), ChatProvider("full", _Available(), 28_000)],
        DatumDocxRenderer(tmp_path / "outputs"),
    )

    assert [provider.name for provider in orchestrator._providers_for(request)] == ["full", "compact"]


def test_document_commands_generate_the_correct_downloadable_word_file(tmp_path: Path) -> None:
    import asyncio

    expected = {
        ChatCommand.QUESTION: "discovery_questionnaire",
        ChatCommand.STRS: "strs",
        ChatCommand.SOW: "scope_of_work",
    }
    for command, document_type in expected.items():
        repository = ChatRunRepository(tmp_path / command.value)
        run, _ = repository.create_or_get(_request(command).model_copy(update={
            "idempotency_key": f"chat-file-{command.value}",
        }))
        orchestrator = ChatterAIOrchestrator(
            repository,
            [ChatProvider("test", _Available(), 100_000)],
            DatumDocxRenderer(tmp_path / "outputs"),
        )
        asyncio.run(orchestrator.process(run.status.run_id))
        status = repository.get(run.status.run_id).status
        assert status.state == "succeeded"
        assert status.artifact_document_type == document_type
        assert status.artifact_filename and status.artifact_filename.endswith(".docx")
        assert status.artifact_download_url and status.artifact_filename in status.artifact_download_url
        assert orchestrator._renderer._output_directory.joinpath(status.artifact_filename).is_file()


def test_document_command_prompts_prohibit_the_other_document_types(tmp_path: Path) -> None:
    renderer = DatumDocxRenderer(tmp_path / "outputs")
    orchestrator = ChatterAIOrchestrator(ChatRunRepository(tmp_path / "state"), [], renderer)
    strs_prompt = orchestrator._build_prompt(_request(ChatCommand.STRS), 100_000)
    sow_prompt = orchestrator._build_prompt(_request(ChatCommand.SOW), 100_000)
    assert "Do not return discovery questions" in strs_prompt
    assert "Do not return discovery questions or an StRS" in sow_prompt


def test_strs_and_sow_reject_questionnaire_style_responses() -> None:
    import pytest

    questionnaire = "\n".join(f"{index}. What do you need?" for index in range(1, 6))
    with pytest.raises(ValueError, match="looks_like_questionnaire"):
        ChatterAIOrchestrator._validate_document_reply(ChatCommand.STRS, questionnaire)
    with pytest.raises(ValueError, match="looks_like_questionnaire"):
        ChatterAIOrchestrator._validate_document_reply(ChatCommand.SOW, questionnaire)


def test_chatter_word_renderer_removes_markdown_markers_and_table_syntax(tmp_path: Path) -> None:
    path = DatumDocxRenderer(tmp_path).render_markdown(
        __import__("uuid").uuid4(),
        "scope_of_work",
        "**Scope of Work**\n\n| Section | Description |\n|---|---|\n| **Objectives** | Deliver a **CRM** pilot.<br>Train users. |",
        "test",
    )
    from docx import Document

    text = "\n".join(paragraph.text for paragraph in Document(path).paragraphs)
    assert "**" not in text
    assert "|" not in text
    assert "Objectives" in text


def test_second_chatter_server_loads_a_run_created_after_it_started(tmp_path: Path) -> None:
    first_server = ChatRunRepository(tmp_path)
    second_server = ChatRunRepository(tmp_path)
    created, _ = first_server.create_or_get(_request())

    loaded = second_server.get(created.status.run_id)

    assert loaded.status.run_id == created.status.run_id
    assert loaded.request.command == ChatCommand.CHAT

"""Focused tests for the Odoo chatter AI FastAPI contract."""

from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import SecretStr

from src.chatter_ai.schemas import ChatCommand, ChatterAIStartRequest, ContextUnit
from src.chatter_ai.service import ChatProvider, ChatRunRepository, ChatterAIOrchestrator
from src.core.config import Settings
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


def test_chatter_api_requires_bearer_token() -> None:
    app = create_application(Settings(datum_engine_api_auth_token=SecretStr("test-token")))
    with TestClient(app) as client:
        unauthorized = client.post("/api/v1/chatter-ai/runs", json=_request().model_dump(mode="json"))
        authorized = client.post(
            "/api/v1/chatter-ai/runs",
            json=_request().model_dump(mode="json"),
            headers={"Authorization": "Bearer test-token"},
        )
    assert unauthorized.status_code == 401
    assert authorized.status_code == 202


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

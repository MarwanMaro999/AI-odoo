"""Unit tests for durable Chatter session/run coordination."""

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from src.chatter_ai.schemas import ChatterAIStartRequest, ContextMode, ContextUnit
from src.chatter_ai.service import ChatRunRepository, ChatterAIService
from src.chatter_ai.sessions import (
    ChatterSessionStore,
    PreparedChatterSession,
    ReservedChatterSession,
    _query_terms,
)


class SessionStoreStub:
    def __init__(self, session_id=None) -> None:
        self.session_id = session_id or uuid4()
        self.reserved_requests: list[ChatterAIStartRequest] = []
        self.prepared_requests: list[ChatterAIStartRequest] = []
        self.retrieved_context: list[ContextUnit] | None = None

    async def reserve(self, request: ChatterAIStartRequest) -> ReservedChatterSession:
        self.reserved_requests.append(request)
        return ReservedChatterSession(self.session_id, len(self.reserved_requests) == 1)

    async def prepare(self, request: ChatterAIStartRequest) -> PreparedChatterSession:
        self.prepared_requests.append(request)
        return PreparedChatterSession(
            self.session_id,
            len(self.prepared_requests) == 1,
            self.retrieved_context if self.retrieved_context is not None else request.context,
        )


class QueueStub:
    def __init__(self) -> None:
        self.run_ids = []

    async def enqueue(self, run_id) -> None:
        self.run_ids.append(run_id)


class RecoverableQueueStub(QueueStub):
    def __init__(self) -> None:
        super().__init__()
        self.recovered = []

    async def ensure_enqueued(self, run_id) -> None:
        self.recovered.append(run_id)


def request(idempotency_key: str, session_id=None) -> ChatterAIStartRequest:
    return ChatterAIStartRequest(
        idempotency_key=idempotency_key,
        record_model="crm.lead",
        record_id=42,
        requester_id=7,
        session_id=session_id,
        user_message="Please prepare the next document.",
        context=[ContextUnit(source_id="record-42", kind="record", title="Lead", text="Known context")],
    )


def test_first_and_follow_up_runs_share_the_same_session(tmp_path: Path) -> None:
    sessions = SessionStoreStub()
    queue = QueueStub()
    service = ChatterAIService(ChatRunRepository(tmp_path), queue, sessions)

    first = asyncio.run(service.start(request("session-first")))
    follow_up = asyncio.run(service.start(request("session-follow-up", sessions.session_id)))

    assert first.session_id == sessions.session_id
    assert follow_up.session_id == sessions.session_id
    assert sessions.reserved_requests[1].session_id == sessions.session_id
    assert sessions.prepared_requests == []
    assert queue.run_ids == [first.run_id, follow_up.run_id]


def test_duplicate_run_does_not_create_another_durable_turn_or_queue_item(tmp_path: Path) -> None:
    sessions = SessionStoreStub()
    queue = QueueStub()
    service = ChatterAIService(ChatRunRepository(tmp_path), queue, sessions)

    first = asyncio.run(service.start(request("session-duplicate")))
    duplicate = asyncio.run(service.start(request("session-duplicate")))

    assert duplicate.run_id == first.run_id
    assert len(sessions.reserved_requests) == 1
    assert sessions.prepared_requests == []
    assert queue.run_ids == [first.run_id]


def test_duplicate_queued_run_rechecks_the_durable_job_without_creating_another_turn(tmp_path: Path) -> None:
    sessions = SessionStoreStub()
    queue = RecoverableQueueStub()
    service = ChatterAIService(ChatRunRepository(tmp_path), queue, sessions)

    first = asyncio.run(service.start(request("session-recover-queued")))
    duplicate = asyncio.run(service.start(request("session-recover-queued")))

    assert duplicate.run_id == first.run_id
    assert len(sessions.reserved_requests) == 1
    assert sessions.prepared_requests == []
    assert queue.recovered == [first.run_id]


def test_delta_request_is_queued_before_expensive_context_preparation(tmp_path: Path) -> None:
    sessions = SessionStoreStub()
    sessions.retrieved_context = [
        ContextUnit(source_id="record-42", kind="record", title="Lead", text="Stored record context"),
        ContextUnit(source_id="message-10", kind="chatter_message", title="Latest note", text="New detail"),
    ]
    queue = QueueStub()
    repository = ChatRunRepository(tmp_path)
    service = ChatterAIService(repository, queue, sessions)
    delta = request("session-delta", sessions.session_id).model_copy(update={
        "context_mode": ContextMode.DELTA,
        "context": [ContextUnit(source_id="message-10", kind="chatter_message", title="Latest note", text="New detail")],
    })

    status = asyncio.run(service.start(delta))

    assert sessions.reserved_requests[0].context_mode == ContextMode.DELTA
    assert repository.get(status.run_id).request.context == delta.context
    assert sessions.prepared_requests == []
    assert queue.run_ids == [status.run_id]


def test_durable_prior_turns_are_retrieved_without_repeating_current_request() -> None:
    now = datetime.now(timezone.utc)
    turns = [
        SimpleNamespace(
            id=uuid4(), direction="user", content="What is the company name?",
            turn_type="chat", created_at=now,
        ),
        SimpleNamespace(
            id=uuid4(), direction="assistant", content="The company is Nile Delta.",
            turn_type="response", created_at=now,
        ),
        SimpleNamespace(
            id=uuid4(), direction="user", content="Compare V1 and V2.",
            turn_type="chat", created_at=now,
        ),
    ]

    context = ChatterSessionStore._turn_context(turns, "What is the company name?")

    assert all(unit.text != "What is the company name?" for unit in context)
    assert any(unit.text == "The company is Nile Delta." for unit in context)
    assert any(unit.text == "Compare V1 and V2." for unit in context)


def test_version_tokens_are_kept_for_document_comparison_retrieval() -> None:
    assert {"v1", "v4"}.issubset(_query_terms("Tell me the difference between V4 and V1"))


def test_chunk_retrieval_includes_both_requested_versions_before_other_sources() -> None:
    store = object.__new__(ChatterSessionStore)
    store._max_sources = 4
    store._max_bytes = 20_000
    v1 = SimpleNamespace(
        source_id="attachment-v1", source_kind="attachment", title="20260902_En_SoW_v1.docx",
        source_metadata={}, revision=1,
    )
    v4 = SimpleNamespace(
        source_id="attachment-v4", source_kind="attachment", title="20260902_En_SoW_v4.docx",
        source_metadata={}, revision=1,
    )
    unrelated = SimpleNamespace(
        source_id="record-35", source_kind="record", title="Contact 35",
        source_metadata={}, revision=1,
    )

    def chunk(source, index):
        return SimpleNamespace(
            source_id=source.source_id, source_revision=1, chunk_index=index,
            source_kind=source.source_kind, content=f"chunk {index}", embedding=None,
        )

    selected = store._retrieve_chunks(
        [chunk(v1, 0), chunk(v1, 1), chunk(v4, 0), chunk(v4, 1), chunk(unrelated, 0)],
        {item.source_id: item for item in (v1, v4, unrelated)},
        {"difference", "between", "v1", "v4"},
        None,
        user_message="Tell me the difference between V1 and V4",
    )

    assert {unit.metadata["source_id"] for unit in selected} == {"attachment-v1", "attachment-v4"}
    assert len(selected) == 4


def test_context_ingestion_bounds_optional_remote_embedding_calls() -> None:
    class Embeddings:
        model = "test-embedding"

        def __init__(self) -> None:
            self.calls = []

        async def embed(self, text: str):
            self.calls.append(text)
            return [1.0, 0.0]

    class DatabaseSession:
        def __init__(self) -> None:
            self.rows = []

        def add(self, row) -> None:
            self.rows.append(row)

    store = object.__new__(ChatterSessionStore)
    store._embedding_provider = Embeddings()
    store._embedding_max_chunks_per_run = 2
    store._embedding_concurrency = 2
    store._chunk_bytes = 128
    db = DatabaseSession()
    source = SimpleNamespace(
        source_id="attachment-v4", revision=1, source_kind="attachment",
        title="20260902_En_SoW_v4.docx", source_metadata={}, content="x " * 500,
    )

    asyncio.run(store._store_chunks(db, uuid4(), [source], "Compare V4 with V1"))

    assert len(store._embedding_provider.calls) == 2
    assert len(db.rows) > len(store._embedding_provider.calls)
    assert sum(row.embedding is not None for row in db.rows) == 2

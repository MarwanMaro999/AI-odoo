import asyncio
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import numpy as np

from src.engine.schemas import RunState, SourceMaterial, StartRunRequest, SkillReference
from src.engine.service import EngineService, PersistentRunRepository
from src.engine.sessions import EngineSessionStore, PreparedEngineSession


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        engine_session_retrieval_max_sources=8,
        engine_session_retrieval_max_bytes=20_000,
        ai_embedding_chunk_bytes=2_000,
        ai_summary_min_new_sources=3,
    )


class _ArrayEmbeddingProvider:
    model = "array-test"

    async def embed(self, _: str):
        return np.array([0.25, 0.75])


def test_numpy_embedding_is_normalized_without_boolean_coercion() -> None:
    store = EngineSessionStore(
        SimpleNamespace(), _settings(), _ArrayEmbeddingProvider(),
    )

    assert asyncio.run(store._embed("context")) == [0.25, 0.75]


class _FastSessions:
    def __init__(self) -> None:
        self.enrichment_flags: list[bool] = []

    async def prepare(self, request, *, enrich_with_models=False):
        self.enrichment_flags.append(enrich_with_models)
        return PreparedEngineSession(uuid4(), request.source_material)


class _Queue:
    def __init__(self) -> None:
        self.run_ids = []

    async def enqueue(self, run_id) -> None:
        self.run_ids.append(run_id)


def test_engine_submission_uses_provider_free_session_preparation(tmp_path: Path) -> None:
    sessions = _FastSessions()
    queue = _Queue()
    service = EngineService(
        PersistentRunRepository(tmp_path / "state"), queue, sessions,
    )
    request = StartRunRequest(
        idempotency_key="fast-session-preparation",
        engagement_id="42",
        record_id=42,
        workflow="gen-discovery-questions",
        source_set_revision="1",
        skill=SkillReference(
            identifier="gen-discovery-questions", version="1.0.0",
        ),
        source_material=[SourceMaterial(
            source_id="record-42",
            revision="1",
            type="prospect_context",
            name="Prospect context",
            text="Known project context.",
        )],
    )

    status = asyncio.run(service.start(request))

    assert sessions.enrichment_flags == [False]
    assert queue.run_ids == [status.run_id]
    assert status.session_id is not None


def test_repository_refreshes_state_written_by_another_worker(tmp_path: Path) -> None:
    state_directory = tmp_path / "shared-state"
    first = PersistentRunRepository(state_directory)
    request = StartRunRequest(
        idempotency_key="cross-process-refresh",
        engagement_id="42",
        record_id=42,
        source_set_revision="1",
        skill=SkillReference(identifier="gen-strs", version="1.0.0"),
        source_material=[SourceMaterial(
            source_id="meeting",
            revision="1",
            type="meeting_transcript",
            name="Meeting transcript",
            text="Approved meeting evidence.",
        )],
    )
    run, _ = first.create_or_get(request)
    second = PersistentRunRepository(state_directory)
    completed = second.get(run.status.run_id)
    completed.status.state = RunState.SUCCEEDED
    second.save(completed)

    assert first.get(run.status.run_id).status.state == RunState.SUCCEEDED

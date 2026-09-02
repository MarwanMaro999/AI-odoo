"""Unit tests for durable queue state transitions without a live database."""

import asyncio
from pathlib import Path
from uuid import uuid4

from src.chatter_ai.durable_queue import DurableChatterQueue
from src.chatter_ai.schemas import ChatRunState, ChatterAIStartRequest, ContextUnit
from src.chatter_ai.service import ChatRunRepository
from src.core.config import Settings
from src.engine.durable_queue import DurableEngineQueue
from src.engine.schemas import RunState, SkillReference, SourceMaterial, StartRunRequest
from src.engine.service import PersistentRunRepository
from src.shared.queue.durable_jobs import ClaimedJob, DurableJobRepository, DurableJobWorker


class JobRepositoryStub:
    def __init__(self, jobs: list[ClaimedJob]) -> None:
        self.jobs = jobs
        self.completed = []
        self.retried = []

    async def claim(self, _worker_id):
        return self.jobs.pop(0) if self.jobs else None

    async def complete(self, job_id, worker_id, result, state="succeeded") -> None:
        self.completed.append((job_id, worker_id, result, state))

    async def retry_or_fail(self, job_id, worker_id, error) -> None:
        self.retried.append((job_id, worker_id, type(error).__name__))

    async def heartbeat(self, _job_id, _worker_id) -> bool:
        return True


def settings() -> Settings:
    return Settings(worker_concurrency=1, ai_job_lease_seconds=30, ai_job_poll_seconds=0.1)


def test_durable_worker_completes_claimed_job_once() -> None:
    job = ClaimedJob(uuid4(), "chatter_ai_run", {"run_id": str(uuid4())}, 1, 3)
    repository = JobRepositoryStub([job])

    async def handler(claimed: ClaimedJob):
        return {"run_id": claimed.payload["run_id"]}

    worker = DurableJobWorker(repository, {"chatter_ai_run": handler}, settings())
    assert asyncio.run(worker.run_once()) is True
    assert repository.completed[0][0] == job.id
    assert repository.completed[0][2]["run_id"] == job.payload["run_id"]


def test_durable_worker_keeps_a_human_intervention_job_terminal() -> None:
    job = ClaimedJob(uuid4(), "datum_engine_run", {"run_id": str(uuid4())}, 1, 3)
    repository = JobRepositoryStub([job])

    async def handler(_claimed: ClaimedJob):
        return {"run_id": job.payload["run_id"], "_job_state": "requires_human_intervention"}

    worker = DurableJobWorker(repository, {"datum_engine_run": handler}, settings())

    assert asyncio.run(worker.run_once()) is True
    assert repository.completed[0][3] == "requires_human_intervention"


def test_durable_worker_schedules_a_retry_after_handler_failure() -> None:
    job = ClaimedJob(uuid4(), "chatter_ai_run", {}, 1, 3)
    repository = JobRepositoryStub([job])

    async def handler(_claimed: ClaimedJob):
        raise RuntimeError("temporary failure")

    worker = DurableJobWorker(repository, {"chatter_ai_run": handler}, settings())
    assert asyncio.run(worker.run_once()) is True
    assert repository.completed == []
    assert repository.retried[0][0] == job.id
    assert repository.retried[0][2] == "RuntimeError"


def test_retry_delay_is_bounded_exponential_backoff() -> None:
    assert DurableJobRepository.retry_delay_seconds(1) == 1
    assert DurableJobRepository.retry_delay_seconds(4) == 8
    assert DurableJobRepository.retry_delay_seconds(20) == 60


def test_chatter_enqueue_writes_one_durable_idempotent_job(tmp_path: Path) -> None:
    request = ChatterAIStartRequest(
        idempotency_key="durable-dispatch",
        record_model="crm.lead",
        record_id=42,
        requester_id=7,
        user_message="Prepare a scope of work.",
        context=[ContextUnit(source_id="record", kind="record", title="Lead", text="Known context")],
    )
    runs = ChatRunRepository(tmp_path)
    run, _ = runs.create_or_get(request, uuid4())

    class Jobs:
        def __init__(self):
            self.calls = []

        async def enqueue(self, *args, **kwargs):
            self.calls.append((args, kwargs))
            return uuid4()

    class Worker:
        def __init__(self):
            self.notified = 0

        async def notify(self):
            self.notified += 1

    jobs = Jobs()
    worker = Worker()
    queue = DurableChatterQueue(runs, jobs, worker)
    asyncio.run(queue.enqueue(run.status.run_id))

    arguments, keywords = jobs.calls[0]
    assert arguments[0] == run.status.session_id
    assert arguments[2] == "chatter-job:%s" % run.status.run_id
    assert arguments[3] == {"run_id": str(run.status.run_id)}
    assert keywords["reactivate_terminal"] is True
    assert worker.notified == 1


def test_engine_enqueue_writes_one_durable_idempotent_job(tmp_path: Path) -> None:
    request = StartRunRequest(
        idempotency_key="durable-engine-dispatch",
        engagement_id="42",
        session_id=uuid4(),
        source_set_revision="1",
        skill=SkillReference(identifier="gen-sow", version="1.0.0"),
        source_material=[SourceMaterial(source_id="record", revision="1", type="record", name="Lead", text="Known context")],
    )
    runs = PersistentRunRepository(tmp_path)
    run, _ = runs.create_or_get(request)

    class Jobs:
        def __init__(self):
            self.calls = []

        async def enqueue(self, *args, **kwargs):
            self.calls.append((args, kwargs))
            return uuid4()

    class Worker:
        def __init__(self):
            self.notified = 0

        async def notify(self):
            self.notified += 1

    jobs = Jobs()
    worker = Worker()
    queue = DurableEngineQueue(runs, jobs, worker)
    asyncio.run(queue.enqueue(run.status.run_id))

    arguments, keywords = jobs.calls[0]
    assert arguments[0] == run.status.session_id
    assert arguments[2] == "engine-job:%s" % run.status.run_id
    assert arguments[3] == {"run_id": str(run.status.run_id)}
    assert keywords["reactivate_terminal"] is True


def test_engine_queue_recovers_persisted_active_runs_on_start(tmp_path: Path) -> None:
    request = StartRunRequest(
        idempotency_key="recover-engine-run",
        engagement_id="42",
        session_id=uuid4(),
        source_set_revision="1",
        skill=SkillReference(identifier="gen-sow", version="1.0.0"),
        source_material=[SourceMaterial(source_id="record", revision="1", type="record", name="Lead", text="Known context")],
    )
    runs = PersistentRunRepository(tmp_path)
    run, _ = runs.create_or_get(request)

    class Jobs:
        def __init__(self):
            self.calls = []

        async def enqueue(self, *args, **kwargs):
            self.calls.append((args, kwargs))
            return uuid4()

    class Worker:
        def __init__(self):
            self.started = 0
            self.notified = 0

        async def start(self):
            self.started += 1

        async def notify(self):
            self.notified += 1

    jobs = Jobs()
    worker = Worker()
    queue = DurableEngineQueue(runs, jobs, worker)
    asyncio.run(queue.start())

    assert worker.started == 1
    assert jobs.calls[0][0][2] == "engine-job:%s" % run.status.run_id
    assert jobs.calls[0][1]["reactivate_terminal"] is True


def test_chatter_queue_recovers_persisted_active_runs_on_start(tmp_path: Path) -> None:
    request = ChatterAIStartRequest(
        idempotency_key="recover-chatter-run",
        record_model="crm.lead",
        record_id=42,
        requester_id=7,
        user_message="Prepare a scope of work.",
        context=[ContextUnit(source_id="record", kind="record", title="Lead", text="Known context")],
    )
    runs = ChatRunRepository(tmp_path)
    run, _ = runs.create_or_get(request, uuid4())

    class Jobs:
        def __init__(self):
            self.calls = []

        async def enqueue(self, *args, **kwargs):
            self.calls.append((args, kwargs))
            return uuid4()

    class Worker:
        def __init__(self):
            self.started = 0
            self.notified = 0

        async def start(self):
            self.started += 1

        async def notify(self):
            self.notified += 1

    jobs = Jobs()
    worker = Worker()
    queue = DurableChatterQueue(runs, jobs, worker)
    asyncio.run(queue.start())

    assert worker.started == 1
    assert jobs.calls[0][0][2] == "chatter-job:%s" % run.status.run_id
    assert jobs.calls[0][1]["reactivate_terminal"] is True
    assert worker.notified == 1


def test_chatter_recovery_marks_a_run_failed_when_its_session_was_removed(tmp_path: Path) -> None:
    request = ChatterAIStartRequest(
        idempotency_key="orphaned-chatter-run",
        record_model="crm.lead",
        record_id=42,
        requester_id=7,
        user_message="Prepare a scope of work.",
        context=[ContextUnit(source_id="record", kind="record", title="Lead", text="Known context")],
    )
    runs = ChatRunRepository(tmp_path)
    run, _ = runs.create_or_get(request, uuid4())

    class Jobs:
        async def session_exists(self, _):
            return False

        async def enqueue(self, *_, **__):
            raise AssertionError("an orphaned run must not be enqueued")

    class Worker:
        async def start(self):
            return None

    queue = DurableChatterQueue(runs, Jobs(), Worker())
    asyncio.run(queue.start())

    recovered = runs.get(run.status.run_id)
    assert recovered.status.state == ChatRunState.FAILED
    assert recovered.status.failure_code == "durable_session_missing"


def test_engine_recovery_marks_a_run_failed_when_its_session_was_removed(tmp_path: Path) -> None:
    request = StartRunRequest(
        idempotency_key="orphaned-engine-run",
        engagement_id="42",
        session_id=uuid4(),
        source_set_revision="1",
        skill=SkillReference(identifier="gen-sow", version="1.0.0"),
        source_material=[SourceMaterial(source_id="record", revision="1", type="record", name="Lead", text="Known context")],
    )
    runs = PersistentRunRepository(tmp_path)
    run, _ = runs.create_or_get(request)

    class Jobs:
        async def session_exists(self, _):
            return False

        async def enqueue(self, *_, **__):
            raise AssertionError("an orphaned run must not be enqueued")

    class Worker:
        async def start(self):
            return None

    queue = DurableEngineQueue(runs, Jobs(), Worker())
    asyncio.run(queue.start())

    recovered = runs.get(run.status.run_id)
    assert recovered.status.state == RunState.FAILED
    assert recovered.status.failure_code == "durable_session_missing"

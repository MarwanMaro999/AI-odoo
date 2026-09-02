"""Chatter adapter for Neon-backed durable work execution."""

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from src.chatter_ai.schemas import ChatRunState
from src.chatter_ai.service import ChatRunRepository, ChatterAIOrchestrator
from src.shared.queue.durable_jobs import ClaimedJob, DurableJobRepository, DurableJobWorker


CHATTER_JOB_TYPE = "chatter_ai_run"


class DurableChatterQueue:
    """Keep the Chatter service enqueue interface while persisting every job."""

    def __init__(
        self,
        runs: ChatRunRepository,
        jobs: DurableJobRepository,
        worker: DurableJobWorker,
    ) -> None:
        self._runs = runs
        self._jobs = jobs
        self._worker = worker

    async def start(self) -> None:
        await self._worker.start()
        await self.recover_active_runs()

    async def stop(self) -> None:
        await self._worker.stop()

    async def enqueue(self, run_id: UUID) -> None:
        await self.ensure_enqueued(run_id)

    async def ensure_enqueued(self, run_id: UUID) -> None:
        """Idempotently restore a durable job for a locally persisted run."""
        await self._enqueue(run_id, reactivate_terminal=True)

    async def recover_active_runs(self) -> None:
        """Restore unfinished local work after a FastAPI restart.

        Local development state can outlive an intentionally reset Neon
        database. An orphan must not prevent the whole API from starting.
        """
        for run_id in self._runs.active_run_ids():
            run = self._runs.get(run_id)
            if await self._has_durable_session(run.status.session_id) is False:
                run.status.state = ChatRunState.FAILED
                run.status.completed_at = datetime.now(timezone.utc)
                run.status.failure_code = "durable_session_missing"
                run.status.failure_message = (
                    "The durable AI session no longer exists; this stale local run was not recovered."
                )
                self._runs.save(run)
                continue
            await self._enqueue(run_id, reactivate_terminal=True)

    async def _has_durable_session(self, session_id: UUID | None) -> bool:
        if session_id is None:
            return True
        checker = getattr(self._jobs, "session_exists", None)
        # Lightweight unit-test fakes only implement enqueue; the production
        # repository always provides the database-backed check.
        return True if checker is None else await checker(session_id)

    async def _enqueue(self, run_id: UUID, *, reactivate_terminal: bool) -> None:
        run = self._runs.get(run_id)
        await self._jobs.enqueue(
            run.status.session_id,
            CHATTER_JOB_TYPE,
            "chatter-job:%s" % run_id,
            {"run_id": str(run_id)},
            reactivate_terminal=reactivate_terminal,
        )
        await self._worker.notify()


def chatter_job_handler(orchestrator: ChatterAIOrchestrator):
    async def handle(job: ClaimedJob) -> dict[str, Any]:
        run_id = UUID(str(job.payload["run_id"]))
        await orchestrator.process(run_id)
        return {"run_id": str(run_id)}

    return handle

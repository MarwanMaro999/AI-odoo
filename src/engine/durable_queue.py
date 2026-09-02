"""Durable Neon job adapter for generic document runs."""

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from src.engine.service import DatumOrchestrator, PersistentRunRepository
from src.shared.queue.durable_jobs import ClaimedJob, DurableJobRepository, DurableJobWorker
from src.shared.queue.durable_jobs import JOB_REQUIRES_HUMAN_INTERVENTION
from src.engine.schemas import RunState


ENGINE_JOB_TYPE = "datum_engine_run"


class DurableEngineQueue:
    """Preserve the engine queue interface while storing jobs in Neon."""

    def __init__(
        self,
        runs: PersistentRunRepository,
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
        await self._enqueue(run_id, reactivate_terminal=True)

    async def recover_active_runs(self) -> None:
        """Restore local unfinished runs if the previous process stopped.

        A local run may be older than a database reset. Mark that run failed
        locally instead of trying to recreate a job with a missing FK target.
        """
        for run_id in self._runs.active_run_ids():
            run = self._runs.get(run_id)
            if await self._has_durable_session(run.status.session_id) is False:
                run.status.state = RunState.FAILED
                run.status.completed_at = datetime.now(timezone.utc)
                run.status.failure_code = "durable_session_missing"
                self._runs.save(run)
                continue
            await self._enqueue(run_id, reactivate_terminal=True)

    async def _has_durable_session(self, session_id: UUID | None) -> bool:
        if session_id is None:
            return True
        checker = getattr(self._jobs, "session_exists", None)
        return True if checker is None else await checker(session_id)

    async def _enqueue(self, run_id: UUID, *, reactivate_terminal: bool) -> None:
        run = self._runs.get(run_id)
        await self._jobs.enqueue(
            run.status.session_id,
            ENGINE_JOB_TYPE,
            "engine-job:%s" % run_id,
            {"run_id": str(run_id)},
            reactivate_terminal=reactivate_terminal,
        )
        await self._worker.notify()


def engine_job_handler(orchestrator: DatumOrchestrator):
    async def handle(job: ClaimedJob) -> dict[str, Any]:
        run_id = UUID(str(job.payload["run_id"]))
        await orchestrator.process(run_id)
        status = orchestrator._repository.get(run_id).status
        result = {"run_id": str(run_id), "run_state": status.state.value}
        if status.state == RunState.REQUIRES_HUMAN_INTERVENTION:
            result["_job_state"] = JOB_REQUIRES_HUMAN_INTERVENTION
        return result

    return handle

"""Neon-backed at-least-once background execution with worker leases."""

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert

from src.core.config import Settings
from src.core.logging import get_logger
from src.db.database import DatabaseRuntime
from src.db.models import AIJob, AISession


JOB_QUEUED = "queued"
JOB_RUNNING = "running"
JOB_SUCCEEDED = "succeeded"
JOB_FAILED = "failed"
JOB_REQUIRES_HUMAN_INTERVENTION = "requires_human_intervention"
JOB_AWAITING_CLARIFICATION = "awaiting_clarification"


@dataclass(frozen=True)
class ClaimedJob:
    id: UUID
    job_type: str
    payload: dict[str, Any]
    attempts: int
    max_attempts: int


class DurableJobRepository:
    """Perform durable job transitions atomically in PostgreSQL."""

    def __init__(self, database: DatabaseRuntime, settings: Settings) -> None:
        self._database = database
        self._lease_seconds = settings.ai_job_lease_seconds
        self._max_attempts = settings.ai_job_max_attempts

    async def session_exists(self, session_id: UUID) -> bool:
        """Return whether a local recovery target still exists in Neon."""
        async with self._database.session() as db:
            return await db.get(AISession, session_id) is not None

    async def enqueue(
        self,
        session_id: UUID | None,
        job_type: str,
        idempotency_key: str,
        payload: dict[str, Any],
        *,
        reactivate_terminal: bool = False,
    ) -> UUID:
        statement = insert(AIJob).values(
            session_id=session_id,
            job_type=job_type,
            state=JOB_QUEUED,
            idempotency_key=idempotency_key,
            payload=payload,
            max_attempts=self._max_attempts,
        ).on_conflict_do_nothing(index_elements=("idempotency_key",)).returning(AIJob.id)
        async with self._database.session() as db:
            job_id = (await db.execute(statement)).scalar_one_or_none()
            if job_id is not None:
                return job_id
            job = (await db.execute(
                select(AIJob).where(AIJob.idempotency_key == idempotency_key).with_for_update()
            )).scalar_one()
            if reactivate_terminal and job.state in {JOB_SUCCEEDED, JOB_FAILED}:
                job.state = JOB_QUEUED
                job.session_id = session_id
                job.job_type = job_type
                job.payload = payload
                job.attempts = 0
                job.available_at = datetime.now(timezone.utc)
                job.completed_at = None
                job.lease_started_at = None
                job.lease_expires_at = None
                job.worker_id = None
                job.last_error_code = None
                job.last_error_message = None
                job.result = None
            return job.id

    async def claim(self, worker_id: str) -> ClaimedJob | None:
        """Claim one available or expired-lease job without double execution."""
        now = datetime.now(timezone.utc)
        async with self._database.session() as db:
            job = (await db.execute(
                select(AIJob).where(or_(
                    (AIJob.state == JOB_QUEUED) & (AIJob.available_at <= now),
                    (AIJob.state == JOB_RUNNING) & (AIJob.lease_expires_at < now),
                )).order_by(AIJob.available_at, AIJob.created_at).with_for_update(skip_locked=True).limit(1)
            )).scalar_one_or_none()
            if job is None:
                return None
            if job.attempts >= job.max_attempts:
                job.state = JOB_FAILED
                job.completed_at = now
                job.last_error_code = "job_retry_exhausted"
                job.last_error_message = "The durable worker exhausted its retry limit."
                job.lease_expires_at = None
                job.worker_id = None
                return None
            job.state = JOB_RUNNING
            job.attempts += 1
            job.worker_id = worker_id
            job.lease_started_at = now
            job.lease_expires_at = now + timedelta(seconds=self._lease_seconds)
            return ClaimedJob(job.id, job.job_type, dict(job.payload), job.attempts, job.max_attempts)

    async def heartbeat(self, job_id: UUID, worker_id: str) -> bool:
        now = datetime.now(timezone.utc)
        async with self._database.session() as db:
            job = await db.get(AIJob, job_id, with_for_update=True)
            if job is None or job.state != JOB_RUNNING or job.worker_id != worker_id:
                return False
            job.lease_expires_at = now + timedelta(seconds=self._lease_seconds)
            return True

    async def complete(
        self, job_id: UUID, worker_id: str, result: dict[str, Any], state: str = JOB_SUCCEEDED,
    ) -> None:
        async with self._database.session() as db:
            job = await db.get(AIJob, job_id, with_for_update=True)
            if job is None or job.state != JOB_RUNNING or job.worker_id != worker_id:
                return
            job.state = state
            job.completed_at = datetime.now(timezone.utc)
            job.result = result
            job.lease_expires_at = None
            job.worker_id = None

    async def retry_or_fail(self, job_id: UUID, worker_id: str, error: Exception) -> None:
        async with self._database.session() as db:
            job = await db.get(AIJob, job_id, with_for_update=True)
            if job is None or job.state != JOB_RUNNING or job.worker_id != worker_id:
                return
            job.lease_expires_at = None
            job.worker_id = None
            if job.attempts >= job.max_attempts:
                job.state = JOB_FAILED
                job.completed_at = datetime.now(timezone.utc)
                job.last_error_code = "worker_execution_failed"
                job.last_error_message = type(error).__name__
                return
            job.state = JOB_QUEUED
            job.available_at = datetime.now(timezone.utc) + timedelta(seconds=self.retry_delay_seconds(job.attempts))
            job.last_error_code = "worker_execution_failed"
            job.last_error_message = type(error).__name__

    @staticmethod
    def retry_delay_seconds(attempts: int) -> int:
        return min(60, max(1, 2 ** max(0, attempts - 1)))


JobHandler = Callable[[ClaimedJob], Awaitable[dict[str, Any] | None]]


class DurableJobWorker:
    """Poll Neon, renew a lease while handling work, and safely retry failures."""

    def __init__(
        self,
        repository: DurableJobRepository,
        handlers: Mapping[str, JobHandler],
        settings: Settings,
    ) -> None:
        self._repository = repository
        self._handlers = dict(handlers)
        self._concurrency = settings.worker_concurrency
        self._lease_seconds = settings.ai_job_lease_seconds
        self._poll_seconds = settings.ai_job_poll_seconds
        self._worker_id = "datum-%s" % uuid4()
        self._wake = asyncio.Event()
        self._workers: list[asyncio.Task[None]] = []
        self._logger = get_logger()

    async def start(self) -> None:
        if not self._workers:
            self._wake.set()
            self._workers = [asyncio.create_task(self._work()) for _ in range(self._concurrency)]

    async def stop(self) -> None:
        for worker in self._workers:
            worker.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()

    async def notify(self) -> None:
        self._wake.set()

    async def run_once(self) -> bool:
        job = await self._repository.claim(self._worker_id)
        if job is None:
            return False
        handler = self._handlers.get(job.job_type)
        if handler is None:
            await self._repository.retry_or_fail(job.id, self._worker_id, ValueError("unsupported_job_type"))
            return True
        heartbeat = asyncio.create_task(self._renew_lease(job.id))
        try:
            result = dict(await handler(job) or {})
            state = str(result.pop("_job_state", JOB_SUCCEEDED))
            if state not in {JOB_SUCCEEDED, JOB_REQUIRES_HUMAN_INTERVENTION, JOB_AWAITING_CLARIFICATION}:
                raise ValueError("unsupported_terminal_job_state")
            await self._repository.complete(job.id, self._worker_id, result, state)
        except asyncio.CancelledError:
            # Keep the running lease for a later server process to reclaim.
            raise
        except Exception as error:
            self._logger.warning(
                "durable_job_execution_failed",
                job_id=str(job.id), job_type=job.job_type, error_type=type(error).__name__,
            )
            await self._repository.retry_or_fail(job.id, self._worker_id, error)
        finally:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)
        return True

    async def _work(self) -> None:
        while True:
            if await self.run_once():
                continue
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self._poll_seconds)
            except TimeoutError:
                continue

    async def _renew_lease(self, job_id: UUID) -> None:
        while True:
            await asyncio.sleep(max(1, self._lease_seconds // 3))
            if not await self._repository.heartbeat(job_id, self._worker_id):
                return

"""Development-only asynchronous work queue."""

import asyncio
from collections.abc import Awaitable, Callable
from uuid import UUID


class InMemoryRunQueue:
    """Queue run identifiers and process them in background tasks."""

    def __init__(self, handler: Callable[[UUID], Awaitable[None]], concurrency: int) -> None:
        self._handler = handler
        self._concurrency = concurrency
        self._queue: asyncio.Queue[UUID] = asyncio.Queue()
        self._workers: list[asyncio.Task[None]] = []

    async def start(self) -> None:
        """Start workers once FastAPI enters its lifespan."""
        if not self._workers:
            self._workers = [asyncio.create_task(self._work()) for _ in range(self._concurrency)]

    async def stop(self) -> None:
        """Stop workers cleanly during application shutdown."""
        for worker in self._workers:
            worker.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()

    async def enqueue(self, run_id: UUID) -> None:
        """Accept a run without waiting for its model execution."""
        await self._queue.put(run_id)

    async def _work(self) -> None:
        while True:
            run_id = await self._queue.get()
            try:
                await self._handler(run_id)
            finally:
                self._queue.task_done()

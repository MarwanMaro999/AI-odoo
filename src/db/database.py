"""Async SQLAlchemy runtime. It is activated by the session phase, not import time."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from src.core.config import Settings


# Psycopg's asynchronous connection implementation does not support Windows'
# default Proactor loop. This module is imported before FastAPI/Uvicorn creates
# its loop, so selecting the compatible policy here keeps local Windows runs
# aligned with Linux production behavior.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


class DatabaseRuntime:
    """Own the engine and session factory without leaking connection details."""

    def __init__(self, settings: Settings) -> None:
        url = settings.async_database_url
        if url is None:
            raise RuntimeError("DATABASE_URL is not configured")
        self.engine: AsyncEngine = create_async_engine(
            url,
            pool_pre_ping=True,
            pool_size=settings.database_pool_size,
            max_overflow=settings.database_max_overflow,
        )
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self.sessions() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def dispose(self) -> None:
        await self.engine.dispose()

    async def ping(self) -> None:
        """Confirm the configured Neon connection is usable without exposing it."""
        async with self.engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

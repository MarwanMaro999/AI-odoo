"""Durable provider quota admission shared by every routed model call."""

import asyncio
from datetime import datetime, timezone
from math import ceil
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from src.core.exceptions import QuestionnaireProviderUnavailable
from src.core.model_profiles import ModelProfile
from src.db.database import DatabaseRuntime
from src.db.models import AIModelUsageWindow


class ModelQuotaGuard(Protocol):
    """Reserve one model call before the provider receives it."""

    async def acquire(self, profile: ModelProfile, input_tokens: int) -> None: ...


class _MinuteQuotaExhausted(Exception):
    """Internal signal carrying the bounded wait until a fresh minute."""

    def __init__(self, retry_after_seconds: float) -> None:
        self.retry_after_seconds = retry_after_seconds


class NeonModelQuotaGuard:
    """Atomically enforce configured RPM, TPM, and RPD limits in Neon.

    Output tokens are reserved up front.  This is deliberately conservative:
    a failed provider attempt still consumed a provider request and must count
    against the account limit.
    """

    def __init__(self, database: DatabaseRuntime) -> None:
        self._database = database

    async def acquire(self, profile: ModelProfile, input_tokens: int) -> None:
        for wait_attempt in range(2):
            now = datetime.now(timezone.utc)
            minute_start = now.replace(second=0, microsecond=0)
            day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            # Groq limits are applied per organization/model.  Sharing one
            # durable window across generation, Arabic, review, and summary
            # prevents parallel responsibilities from each admitting the full
            # model allowance and causing avoidable provider-side 429s.
            profile_key = self._profile_key(profile)
            requested_tokens = input_tokens + profile.reserve_output_tokens
            retry_after_seconds = max(
                0.05,
                60.0 - now.second - (now.microsecond / 1_000_000),
            )
            try:
                async with self._database.session() as db:
                    minute = await self._window(db, profile_key, "minute", minute_start)
                    day = await self._window(db, profile_key, "day", day_start)
                    if minute.request_count + 1 > profile.requests_per_minute:
                        raise _MinuteQuotaExhausted(retry_after_seconds)
                    if minute.input_tokens + minute.reserved_output_tokens + requested_tokens > profile.tokens_per_minute:
                        raise _MinuteQuotaExhausted(retry_after_seconds)
                    if day.request_count + 1 > profile.requests_per_day:
                        raise QuestionnaireProviderUnavailable(
                            "The %s request-per-day quota is exhausted." % profile.responsibility
                        )
                    minute.request_count += 1
                    minute.input_tokens += input_tokens
                    minute.reserved_output_tokens += profile.reserve_output_tokens
                    day.request_count += 1
                    day.input_tokens += input_tokens
                    day.reserved_output_tokens += profile.reserve_output_tokens
                return
            except _MinuteQuotaExhausted as error:
                if wait_attempt:
                    raise QuestionnaireProviderUnavailable(
                        "The %s per-minute quota is exhausted." % profile.responsibility
                    ) from error
                await asyncio.sleep(error.retry_after_seconds)
            except QuestionnaireProviderUnavailable:
                raise
            except Exception as error:
                # A missing durable counter must fail closed.  Otherwise a database
                # outage could silently exceed provider limits across workers.
                raise QuestionnaireProviderUnavailable("Durable provider quota storage is unavailable.") from error

    @staticmethod
    def _profile_key(profile: ModelProfile) -> str:
        provider_family = profile.provider.removesuffix("_fallback")
        return "%s:%s" % (provider_family, profile.model)

    @staticmethod
    async def _window(db, profile_key: str, window_kind: str, started_at: datetime) -> AIModelUsageWindow:
        await db.execute(insert(AIModelUsageWindow).values(
            profile_key=profile_key,
            window_kind=window_kind,
            window_started_at=started_at,
            request_count=0,
            input_tokens=0,
            reserved_output_tokens=0,
        ).on_conflict_do_nothing(
            index_elements=("profile_key", "window_kind", "window_started_at"),
        ))
        return (await db.execute(select(AIModelUsageWindow).where(
            AIModelUsageWindow.profile_key == profile_key,
            AIModelUsageWindow.window_kind == window_kind,
            AIModelUsageWindow.window_started_at == started_at,
        ).with_for_update())).scalar_one()


def estimate_input_tokens(prompt: str) -> int:
    """Use the same conservative Unicode-safe estimate before admission."""
    return ceil(len(prompt.encode("utf-8")) / 2)

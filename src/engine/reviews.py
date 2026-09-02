"""Persist generic-engine review evidence in Neon."""

from uuid import UUID

from sqlalchemy import select

from src.db.database import DatabaseRuntime
from src.db.models import AIFinding, AIReviewCycle
from src.engine.schemas import FindingPayload


class ReviewPersistenceService:
    """Keep review cycles/findings durable and idempotent across worker retries."""

    def __init__(self, database: DatabaseRuntime) -> None:
        self._database = database

    async def store(
        self,
        session_id: UUID | None,
        cycle_number: int,
        document_version: int,
        state: str,
        findings: list[FindingPayload],
    ) -> None:
        if session_id is None:
            return
        async with self._database.session() as db:
            cycle = await db.scalar(select(AIReviewCycle).where(
                AIReviewCycle.session_id == session_id,
                AIReviewCycle.cycle_number == cycle_number,
            ))
            if cycle is None:
                cycle = AIReviewCycle(
                    session_id=session_id, cycle_number=cycle_number,
                    document_version=document_version, state=state,
                    review_result={"finding_count": len(findings)},
                )
                db.add(cycle)
                await db.flush()
            else:
                cycle.document_version = document_version
                cycle.state = state
                cycle.review_result = {"finding_count": len(findings)}
                existing = await db.scalar(select(AIFinding.id).where(AIFinding.review_cycle_id == cycle.id))
                if existing is not None:
                    return
            for finding in findings:
                db.add(AIFinding(
                    review_cycle_id=cycle.id, language=finding.language_code,
                    severity=finding.severity, category=finding.category, location=finding.location,
                    issue=finding.summary, recommendation=finding.recommendation,
                    resolved=state == "cleared",
                ))

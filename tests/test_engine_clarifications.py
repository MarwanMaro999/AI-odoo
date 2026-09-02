"""Tests for durable clarification pause/resume state."""

from contextlib import asynccontextmanager
from uuid import uuid4

import pytest

from src.db.models import AIClarification, AISession, AISessionSource, AISessionTurn
from src.engine.clarifications import ClarificationService


class _FakeSession:
    def __init__(self, session: AISession) -> None:
        self.session = session
        self.clarifications: dict[object, AIClarification] = {}
        self.added: list[object] = []

    async def get(self, model: type, identifier: object):
        if model is AISession and identifier == self.session.id:
            return self.session
        if model is AIClarification:
            return self.clarifications.get(identifier)
        return None

    def add(self, record: object) -> None:
        self.added.append(record)

    async def flush(self) -> None:
        for record in self.added:
            if isinstance(record, AIClarification) and record.id is None:
                record.id = uuid4()
                self.clarifications[record.id] = record


class _FakeDatabase:
    def __init__(self, session: AISession) -> None:
        self.db_session = _FakeSession(session)

    @asynccontextmanager
    async def session(self):
        yield self.db_session


@pytest.mark.asyncio
async def test_clarification_pauses_then_records_a_chatter_answer() -> None:
    durable_session = AISession(
        id=uuid4(), odoo_record_model="datum.engagement", odoo_record_id=42,
        workflow="rev-sow", state="active", summary_revision=0,
    )
    database = _FakeDatabase(durable_session)
    service = ClarificationService(database)  # type: ignore[arg-type]

    pending = await service.create(durable_session.id, "What is the go-live date?", 101)

    assert pending.state == "awaiting_answer"
    assert durable_session.state == "awaiting_clarification"
    answered = await service.answer(pending.clarification_id, "1 January 2027", 102)

    assert answered.state == "answered"
    assert answered.answer == "1 January 2027"
    assert durable_session.state == "active"
    source = next(record for record in database.db_session.added if isinstance(record, AISessionSource))
    turn = next(record for record in database.db_session.added if isinstance(record, AISessionTurn))
    assert source.source_kind == "clarification_answers"
    assert source.content == "1 January 2027"
    assert turn.turn_type == "clarification_answer"


@pytest.mark.asyncio
async def test_conflicting_second_answer_is_rejected() -> None:
    durable_session = AISession(
        id=uuid4(), odoo_record_model="datum.engagement", odoo_record_id=42,
        workflow="rev-sow", state="active", summary_revision=0,
    )
    service = ClarificationService(_FakeDatabase(durable_session))  # type: ignore[arg-type]
    pending = await service.create(durable_session.id, "What is the go-live date?")
    await service.answer(pending.clarification_id, "1 January 2027")

    with pytest.raises(ValueError, match="clarification_answer_conflict"):
        await service.answer(pending.clarification_id, "1 February 2027")

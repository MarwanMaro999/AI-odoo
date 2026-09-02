"""Durable clarification state shared by Odoo Chatter and Neon sessions."""

from datetime import datetime, timezone
import hashlib
from uuid import UUID

from src.db.database import DatabaseRuntime
from src.db.models import AIClarification, AISession, AISessionSource, AISessionTurn
from src.core.logging import get_logger
from src.engine.schemas import ClarificationStatus
from src.shared.text import html_to_plain_text


class ClarificationService:
    """Pause one server-side session and safely record the eventual answer."""

    def __init__(self, database: DatabaseRuntime) -> None:
        self._database = database

    async def create(
        self, session_id: UUID, question: str, odoo_question_message_id: int | None = None,
    ) -> ClarificationStatus:
        clean_question = html_to_plain_text(question)
        if not clean_question:
            raise ValueError("clarification_question_empty")
        async with self._database.session() as db:
            session = await db.get(AISession, session_id)
            if session is None:
                raise KeyError("ai_session_not_found")
            clarification = AIClarification(
                session_id=session.id,
                question=clean_question,
                state="awaiting_answer",
                odoo_question_message_id=odoo_question_message_id,
            )
            db.add(clarification)
            session.state = "awaiting_clarification"
            await db.flush()
            get_logger().info(
                "engine_clarification_requested",
                clarification_id=str(clarification.id),
                session_id=str(session.id),
                has_odoo_message=odoo_question_message_id is not None,
            )
            return self._status(clarification)

    async def answer(
        self, clarification_id: UUID, answer: str, odoo_answer_message_id: int | None = None,
    ) -> ClarificationStatus:
        async with self._database.session() as db:
            clarification = await db.get(AIClarification, clarification_id)
            if clarification is None:
                raise KeyError("clarification_not_found")
            text = html_to_plain_text(answer)
            if not text:
                raise ValueError("clarification_answer_empty")
            if clarification.state == "answered":
                if clarification.answer != text:
                    raise ValueError("clarification_answer_conflict")
                get_logger().info(
                    "engine_clarification_answer_replayed",
                    clarification_id=str(clarification.id),
                    session_id=str(clarification.session_id),
                )
                return self._status(clarification)
            if clarification.state != "awaiting_answer":
                raise ValueError("clarification_not_awaiting_answer")
            clarification.answer = text
            clarification.state = "answered"
            clarification.odoo_answer_message_id = odoo_answer_message_id
            clarification.answered_at = datetime.now(timezone.utc)
            session = await db.get(AISession, clarification.session_id)
            if session is None:
                raise KeyError("ai_session_not_found")
            session.state = "active"
            source_id = "clarification-%s" % clarification.id
            content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
            db.add(AISessionSource(
                session_id=session.id,
                source_id=source_id,
                source_kind="clarification_answers",
                title="Clarification answer",
                content=text,
                content_hash=content_hash,
                revision=1,
                source_metadata={"clarification_id": str(clarification.id), "odoo_message_id": odoo_answer_message_id},
            ))
            db.add(AISessionTurn(
                session_id=session.id,
                idempotency_key="clarification-answer:%s" % clarification.id,
                direction="user",
                turn_type="clarification_answer",
                content=text,
                details={"clarification_id": str(clarification.id), "odoo_message_id": odoo_answer_message_id},
            ))
            await db.flush()
            get_logger().info(
                "engine_clarification_answer_received",
                clarification_id=str(clarification.id),
                session_id=str(clarification.session_id),
                has_odoo_message=odoo_answer_message_id is not None,
            )
            return self._status(clarification)

    @staticmethod
    def _status(clarification: AIClarification) -> ClarificationStatus:
        return ClarificationStatus(
            clarification_id=clarification.id,
            session_id=clarification.session_id,
            state=clarification.state,
            question=clarification.question,
            answer=clarification.answer,
        )

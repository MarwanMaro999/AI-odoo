"""Phase 1 durable records for AI sessions and document workflows."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column
from pgvector.sqlalchemy import Vector

from src.db.base import Base


class TimestampedRecord:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class AISession(TimestampedRecord, Base):
    __tablename__ = "ai_sessions"
    __table_args__ = (UniqueConstraint("odoo_record_model", "odoo_record_id", "workflow"),)

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    odoo_record_model: Mapped[str] = mapped_column(String(128), nullable=False)
    odoo_record_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    workflow: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(48), default="active", nullable=False)
    baseline_hash: Mapped[str | None] = mapped_column(String(64))
    baseline_received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_odoo_message_id: Mapped[int | None] = mapped_column(BigInteger)
    rolling_summary: Mapped[str | None] = mapped_column(Text)
    summary_revision: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class AISessionSource(TimestampedRecord, Base):
    __tablename__ = "ai_session_sources"
    __table_args__ = (UniqueConstraint("session_id", "source_id", "revision"),)

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(ForeignKey("ai_sessions.id", ondelete="CASCADE"), nullable=False)
    source_id: Mapped[str] = mapped_column(String(256), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    source_metadata: Mapped[dict[str, object]] = mapped_column("metadata", JSONB, default=dict, nullable=False)


class AISessionTurn(Base):
    __tablename__ = "ai_session_turns"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(ForeignKey("ai_sessions.id", ondelete="CASCADE"), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(256), unique=True, nullable=False)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    turn_type: Mapped[str] = mapped_column(String(64), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict, nullable=False)
    provider: Mapped[str | None] = mapped_column(String(64))
    model: Mapped[str | None] = mapped_column(String(128))
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AIContextChunk(TimestampedRecord, Base):
    """A searchable, versioned unit of durable Odoo session context."""

    __tablename__ = "ai_context_chunks"
    __table_args__ = (
        UniqueConstraint("session_id", "source_id", "source_revision", "chunk_index"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(ForeignKey("ai_sessions.id", ondelete="CASCADE"), nullable=False)
    source_id: Mapped[str] = mapped_column(String(256), nullable=False)
    source_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    source_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    language: Mapped[str] = mapped_column(String(8), nullable=False, default="und")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding_model: Mapped[str | None] = mapped_column(String(128))
    embedding: Mapped[list[float] | None] = mapped_column(Vector(), nullable=True)
    chunk_metadata: Mapped[dict[str, object]] = mapped_column("metadata", JSONB, default=dict, nullable=False)


class AISecurityEvent(Base):
    """Non-sensitive evidence that a request passed through the security gate."""

    __tablename__ = "ai_security_events"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(ForeignKey("ai_sessions.id", ondelete="CASCADE"), nullable=False)
    source_id: Mapped[str] = mapped_column(String(256), nullable=False)
    subject_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    rule_ids: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    scanner_provider: Mapped[str | None] = mapped_column(String(64))
    scanner_model: Mapped[str | None] = mapped_column(String(128))
    scanner_verdict: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AIJob(TimestampedRecord, Base):
    __tablename__ = "ai_jobs"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    session_id: Mapped[UUID | None] = mapped_column(ForeignKey("ai_sessions.id", ondelete="CASCADE"))
    job_type: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(48), default="queued", nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(256), unique=True, nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    worker_id: Mapped[str | None] = mapped_column(String(128))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict, nullable=False)
    last_error_code: Mapped[str | None] = mapped_column(String(128))
    last_error_message: Mapped[str | None] = mapped_column(Text)


class AIModelUsageWindow(TimestampedRecord, Base):
    """Atomic per-profile quota counters for minute and daily admission limits."""

    __tablename__ = "ai_model_usage_windows"
    __table_args__ = (UniqueConstraint("profile_key", "window_kind", "window_started_at"),)

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    profile_key: Mapped[str] = mapped_column(String(96), nullable=False)
    window_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    request_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reserved_output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class AIReviewCycle(TimestampedRecord, Base):
    __tablename__ = "ai_review_cycles"
    __table_args__ = (UniqueConstraint("session_id", "cycle_number"),)

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(ForeignKey("ai_sessions.id", ondelete="CASCADE"), nullable=False)
    cycle_number: Mapped[int] = mapped_column(Integer, nullable=False)
    document_version: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(48), nullable=False)
    review_result: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict, nullable=False)


class AIFinding(TimestampedRecord, Base):
    __tablename__ = "ai_findings"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    review_cycle_id: Mapped[UUID] = mapped_column(ForeignKey("ai_review_cycles.id", ondelete="CASCADE"), nullable=False)
    language: Mapped[str] = mapped_column(String(8), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    category: Mapped[str] = mapped_column(String(128), nullable=False)
    location: Mapped[str | None] = mapped_column(String(512))
    issue: Mapped[str] = mapped_column(Text, nullable=False)
    recommendation: Mapped[str] = mapped_column(Text, nullable=False)
    resolved: Mapped[bool] = mapped_column(default=False, nullable=False)


class AIClarification(TimestampedRecord, Base):
    __tablename__ = "ai_clarifications"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(ForeignKey("ai_sessions.id", ondelete="CASCADE"), nullable=False)
    review_cycle_id: Mapped[UUID | None] = mapped_column(ForeignKey("ai_review_cycles.id", ondelete="SET NULL"))
    question: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(String(48), default="awaiting_answer", nullable=False)
    answer: Mapped[str | None] = mapped_column(Text)
    odoo_question_message_id: Mapped[int | None] = mapped_column(BigInteger)
    odoo_answer_message_id: Mapped[int | None] = mapped_column(BigInteger)
    asked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

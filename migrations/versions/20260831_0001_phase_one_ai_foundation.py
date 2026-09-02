"""Create durable AI session workflow tables.

Revision ID: 20260831_0001
Revises:
Create Date: 2026-08-31
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260831_0001"
down_revision = None
branch_labels = None
depends_on = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    ]


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "ai_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("odoo_record_model", sa.String(128), nullable=False),
        sa.Column("odoo_record_id", sa.BigInteger(), nullable=False),
        sa.Column("workflow", sa.String(64), nullable=False),
        sa.Column("state", sa.String(48), server_default="active", nullable=False),
        sa.Column("baseline_hash", sa.String(64)),
        sa.Column("baseline_received_at", sa.DateTime(timezone=True)),
        sa.Column("last_odoo_message_id", sa.BigInteger()),
        sa.Column("rolling_summary", sa.Text()),
        sa.Column("summary_revision", sa.Integer(), server_default="0", nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("odoo_record_model", "odoo_record_id", "workflow"),
    )
    op.create_table(
        "ai_session_sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ai_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_id", sa.String(256), nullable=False),
        sa.Column("source_kind", sa.String(64), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("metadata", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("session_id", "source_id", "revision"),
    )
    op.create_table(
        "ai_session_turns",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ai_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("direction", sa.String(16), nullable=False),
        sa.Column("turn_type", sa.String(64), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("details", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("provider", sa.String(64)),
        sa.Column("model", sa.String(128)),
        sa.Column("input_tokens", sa.Integer()),
        sa.Column("output_tokens", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_table(
        "ai_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ai_sessions.id", ondelete="CASCADE")),
        sa.Column("job_type", sa.String(64), nullable=False),
        sa.Column("state", sa.String(48), server_default="queued", nullable=False),
        sa.Column("idempotency_key", sa.String(256), nullable=False, unique=True),
        sa.Column("payload", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="3", nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("last_error_code", sa.String(128)),
        sa.Column("last_error_message", sa.Text()),
        *_timestamps(),
    )
    op.create_table(
        "ai_review_cycles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ai_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("cycle_number", sa.Integer(), nullable=False),
        sa.Column("document_version", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(48), nullable=False),
        sa.Column("review_result", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("session_id", "cycle_number"),
    )
    op.create_table(
        "ai_findings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("review_cycle_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ai_review_cycles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("language", sa.String(8), nullable=False),
        sa.Column("severity", sa.String(32), nullable=False),
        sa.Column("category", sa.String(128), nullable=False),
        sa.Column("location", sa.String(512)),
        sa.Column("issue", sa.Text(), nullable=False),
        sa.Column("recommendation", sa.Text(), nullable=False),
        sa.Column("resolved", sa.Boolean(), server_default=sa.false(), nullable=False),
        *_timestamps(),
    )
    op.create_table(
        "ai_clarifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ai_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("review_cycle_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ai_review_cycles.id", ondelete="SET NULL")),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("state", sa.String(48), server_default="awaiting_answer", nullable=False),
        sa.Column("answer", sa.Text()),
        sa.Column("odoo_question_message_id", sa.BigInteger()),
        sa.Column("odoo_answer_message_id", sa.BigInteger()),
        sa.Column("asked_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("answered_at", sa.DateTime(timezone=True)),
        *_timestamps(),
    )


def downgrade() -> None:
    op.drop_table("ai_clarifications")
    op.drop_table("ai_findings")
    op.drop_table("ai_review_cycles")
    op.drop_table("ai_jobs")
    op.drop_table("ai_session_turns")
    op.drop_table("ai_session_sources")
    op.drop_table("ai_sessions")

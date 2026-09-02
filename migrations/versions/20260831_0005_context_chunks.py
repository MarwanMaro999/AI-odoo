"""Add searchable, vector-ready durable context chunks.

Revision ID: 20260831_0005
Revises: 20260831_0004
Create Date: 2026-08-31
"""

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql


revision = "20260831_0005"
down_revision = "20260831_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "ai_context_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "session_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ai_sessions.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("source_id", sa.String(length=256), nullable=False),
        sa.Column("source_revision", sa.Integer(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("source_kind", sa.String(length=64), nullable=False),
        sa.Column("language", sa.String(length=8), server_default="und", nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("embedding_model", sa.String(length=128)),
        sa.Column("embedding", Vector(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("session_id", "source_id", "source_revision", "chunk_index"),
    )
    op.create_index("ix_ai_context_chunks_session", "ai_context_chunks", ["session_id"])
    op.create_index("ix_ai_context_chunks_source", "ai_context_chunks", ["session_id", "source_id"])


def downgrade() -> None:
    op.drop_index("ix_ai_context_chunks_source", table_name="ai_context_chunks")
    op.drop_index("ix_ai_context_chunks_session", table_name="ai_context_chunks")
    op.drop_table("ai_context_chunks")

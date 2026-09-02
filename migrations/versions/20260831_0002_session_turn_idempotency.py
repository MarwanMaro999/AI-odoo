"""Add durable idempotency to AI session turns.

Revision ID: 20260831_0002
Revises: 20260831_0001
Create Date: 2026-08-31
"""

from alembic import op
import sqlalchemy as sa


revision = "20260831_0002"
down_revision = "20260831_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ai_session_turns", sa.Column("idempotency_key", sa.String(256), nullable=True))
    op.execute("UPDATE ai_session_turns SET idempotency_key = id::text WHERE idempotency_key IS NULL")
    op.alter_column("ai_session_turns", "idempotency_key", nullable=False)
    op.create_unique_constraint("uq_ai_session_turns_idempotency_key", "ai_session_turns", ["idempotency_key"])


def downgrade() -> None:
    op.drop_constraint("uq_ai_session_turns_idempotency_key", "ai_session_turns", type_="unique")
    op.drop_column("ai_session_turns", "idempotency_key")

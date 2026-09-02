"""Add worker lease and completion fields for durable AI jobs.

Revision ID: 20260831_0004
Revises: 20260831_0003
Create Date: 2026-08-31
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260831_0004"
down_revision = "20260831_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ai_jobs", sa.Column("lease_started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("ai_jobs", sa.Column("worker_id", sa.String(length=128), nullable=True))
    op.add_column("ai_jobs", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "ai_jobs",
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    )
    op.create_index("ix_ai_jobs_claim", "ai_jobs", ["state", "available_at"])


def downgrade() -> None:
    op.drop_index("ix_ai_jobs_claim", table_name="ai_jobs")
    op.drop_column("ai_jobs", "result")
    op.drop_column("ai_jobs", "completed_at")
    op.drop_column("ai_jobs", "worker_id")
    op.drop_column("ai_jobs", "lease_started_at")

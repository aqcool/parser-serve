"""Persist W3C Trace Context for asynchronous task execution.

Revision ID: 0005_task_trace_context
Revises: 0004_stage_device
Create Date: 2026-07-24
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0005_task_trace_context"
down_revision: str | None = "0004_stage_device"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column("trace_context_payload", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tasks", "trace_context_payload")

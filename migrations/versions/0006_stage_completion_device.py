"""Persist the exact device used by a completed Stage.

Revision ID: 0006_stage_completion_device
Revises: 0005_task_trace_context
Create Date: 2026-07-26
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0006_stage_completion_device"
down_revision: str | None = "0005_task_trace_context"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "stages",
        sa.Column("completion_device_id", sa.String(length=128), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("stages", "completion_device_id")

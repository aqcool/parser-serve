"""Assign leased stages to an exact Worker device.

Revision ID: 0004_stage_device
Revises: 0003_callback_attempts
Create Date: 2026-07-24
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0004_stage_device"
down_revision: str | None = "0003_callback_attempts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "stages",
        sa.Column("device_id", sa.String(length=128), nullable=True),
    )
    op.create_index(
        "ix_stages_device_id",
        "stages",
        ["device_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_stages_device_id", table_name="stages")
    op.drop_column("stages", "device_id")

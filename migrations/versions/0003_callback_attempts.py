"""Add immutable callback delivery attempt history.

Revision ID: 0003_callback_attempts
Revises: 0002_system_settings
Create Date: 2026-07-24
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0003_callback_attempts"
down_revision: str | None = "0002_system_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "callback_deliveries",
        sa.Column(
            "attempt_sequence",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )
    op.create_table(
        "callback_attempts",
        sa.Column("attempt_id", sa.String(length=72), nullable=False),
        sa.Column("delivery_id", sa.String(length=72), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("delivered", sa.Boolean(), nullable=False),
        sa.Column("response_status_code", sa.Integer(), nullable=True),
        sa.Column("response_summary", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("error_payload", sa.JSON(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["delivery_id"],
            ["callback_deliveries.delivery_id"],
            name="fk_callback_attempts_delivery_id_callback_deliveries",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("attempt_id", name="pk_callback_attempts"),
        sa.UniqueConstraint(
            "delivery_id",
            "sequence",
            name="uq_callback_attempts_delivery_sequence",
        ),
    )
    op.create_index(
        "ix_callback_attempts_delivery_id",
        "callback_attempts",
        ["delivery_id"],
        unique=False,
    )
    op.create_index(
        "ix_callback_attempts_completed_at",
        "callback_attempts",
        ["completed_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_callback_attempts_completed_at",
        table_name="callback_attempts",
    )
    op.drop_index(
        "ix_callback_attempts_delivery_id",
        table_name="callback_attempts",
    )
    op.drop_table("callback_attempts")
    op.drop_column("callback_deliveries", "attempt_sequence")

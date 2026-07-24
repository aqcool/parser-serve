"""Create the initial control-plane schema.

Revision ID: 0001_initial
Revises:
Create Date: 2026-07-24
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from alembic import op
import sqlalchemy as sa


revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> tuple[sa.Column[datetime], sa.Column[datetime]]:
    return (
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def upgrade() -> None:
    op.create_table(
        "api_keys",
        sa.Column("api_key_id", sa.String(length=72), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column(
            "kind",
            sa.String(length=32),
            server_default=sa.text("'ordinary'"),
            nullable=False,
        ),
        sa.Column("worker_id", sa.String(length=72), nullable=True),
        sa.Column("prefix", sa.String(length=32), nullable=False),
        sa.Column("digest", sa.LargeBinary(length=32), nullable=False),
        sa.Column(
            "enabled",
            sa.Boolean(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("api_key_id", name="pk_api_keys"),
        sa.UniqueConstraint("digest", name="uq_api_keys_digest"),
    )
    op.create_index("ix_api_keys_prefix", "api_keys", ["prefix"], unique=False)
    op.create_index("ix_api_keys_kind", "api_keys", ["kind"], unique=False)
    op.create_index(
        "ix_api_keys_worker_id",
        "api_keys",
        ["worker_id"],
        unique=False,
    )

    op.create_table(
        "backends",
        sa.Column("backend_id", sa.String(length=72), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("execution_mode", sa.String(length=32), nullable=False),
        sa.Column("definition_payload", sa.JSON(), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("backend_id", name="pk_backends"),
        sa.UniqueConstraint(
            "name",
            "version",
            name="uq_backends_name_version",
        ),
    )
    op.create_index("ix_backends_name", "backends", ["name"], unique=False)
    op.create_index("ix_backends_status", "backends", ["status"], unique=False)

    op.create_table(
        "callback_deliveries",
        sa.Column("delivery_id", sa.String(length=72), nullable=False),
        sa.Column("event_id", sa.String(length=72), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("task_id", sa.String(length=72), nullable=False),
        sa.Column("target_url", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "attempt",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("maximum_attempts", sa.Integer(), nullable=False),
        sa.Column("event_payload", sa.JSON(), nullable=False),
        sa.Column("response_status_code", sa.Integer(), nullable=True),
        sa.Column("response_summary", sa.Text(), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint(
            "delivery_id",
            name="pk_callback_deliveries",
        ),
        sa.UniqueConstraint(
            "event_id",
            name="uq_callback_deliveries_event_id",
        ),
    )
    op.create_index(
        "ix_callback_deliveries_event_id",
        "callback_deliveries",
        ["event_id"],
        unique=False,
    )
    op.create_index(
        "ix_callback_deliveries_event_type",
        "callback_deliveries",
        ["event_type"],
        unique=False,
    )
    op.create_index(
        "ix_callback_deliveries_next_attempt_at",
        "callback_deliveries",
        ["next_attempt_at"],
        unique=False,
    )
    op.create_index(
        "ix_callback_deliveries_status",
        "callback_deliveries",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_callback_deliveries_task_id",
        "callback_deliveries",
        ["task_id"],
        unique=False,
    )

    op.create_table(
        "events",
        sa.Column("event_id", sa.String(length=72), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("task_id", sa.String(length=72), nullable=True),
        sa.Column("worker_id", sa.String(length=72), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "callback_processed",
            sa.Boolean(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("event_id", name="pk_events"),
    )
    op.create_index("ix_events_event_type", "events", ["event_type"], unique=False)
    op.create_index(
        "ix_events_callback_processed",
        "events",
        ["callback_processed"],
        unique=False,
    )
    op.create_index("ix_events_occurred_at", "events", ["occurred_at"], unique=False)
    op.create_index("ix_events_task_id", "events", ["task_id"], unique=False)
    op.create_index("ix_events_worker_id", "events", ["worker_id"], unique=False)

    op.create_table(
        "pipelines",
        sa.Column("record_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("pipeline_id", sa.String(length=72), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("definition_payload", sa.JSON(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("record_id", name="pk_pipelines"),
        sa.UniqueConstraint(
            "pipeline_id",
            "version",
            name="uq_pipelines_id_version",
        ),
    )
    op.create_index(
        "ix_pipelines_pipeline_id",
        "pipelines",
        ["pipeline_id"],
        unique=False,
    )
    op.create_index("ix_pipelines_status", "pipelines", ["status"], unique=False)

    op.create_table(
        "tasks",
        sa.Column("task_id", sa.String(length=72), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "progress_percent",
            sa.Float(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("source_payload", sa.JSON(), nullable=False),
        sa.Column("source_metadata_payload", sa.JSON(), nullable=True),
        sa.Column("media_category", sa.String(length=32), nullable=True),
        sa.Column("options_payload", sa.JSON(), nullable=False),
        sa.Column("callback_payload", sa.JSON(), nullable=True),
        sa.Column("pipeline_id", sa.String(length=72), nullable=True),
        sa.Column("pipeline_version", sa.Integer(), nullable=True),
        sa.Column("backend_name", sa.String(length=128), nullable=True),
        sa.Column("requested_runtime", sa.String(length=32), nullable=True),
        sa.Column(
            "priority",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("client_reference", sa.String(length=256), nullable=True),
        sa.Column("idempotency_digest", sa.LargeBinary(length=32), nullable=True),
        sa.Column("request_digest", sa.LargeBinary(length=32), nullable=True),
        sa.Column("result_uri", sa.Text(), nullable=True),
        sa.Column("error_payload", sa.JSON(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("task_id", name="pk_tasks"),
        sa.UniqueConstraint(
            "idempotency_digest",
            name="uq_tasks_idempotency_digest",
        ),
    )
    op.create_index(
        "ix_tasks_backend_name",
        "tasks",
        ["backend_name"],
        unique=False,
    )
    op.create_index(
        "ix_tasks_client_reference",
        "tasks",
        ["client_reference"],
        unique=False,
    )
    op.create_index(
        "ix_tasks_created_at_task_id",
        "tasks",
        ["created_at", "task_id"],
        unique=False,
    )
    op.create_index(
        "ix_tasks_media_category",
        "tasks",
        ["media_category"],
        unique=False,
    )
    op.create_index("ix_tasks_pipeline_id", "tasks", ["pipeline_id"], unique=False)
    op.create_index(
        "ix_tasks_requested_runtime",
        "tasks",
        ["requested_runtime"],
        unique=False,
    )
    op.create_index("ix_tasks_status", "tasks", ["status"], unique=False)

    op.create_table(
        "workers",
        sa.Column("worker_id", sa.String(length=72), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("hostname", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "enabled",
            sa.Boolean(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column("maximum_concurrency", sa.Integer(), nullable=False),
        sa.Column(
            "scheduling_weight",
            sa.Integer(),
            server_default=sa.text("100"),
            nullable=False,
        ),
        sa.Column("devices_payload", sa.JSON(), nullable=False),
        sa.Column("device_usage_payload", sa.JSON(), nullable=False),
        sa.Column("backends_payload", sa.JSON(), nullable=False),
        sa.Column("labels_payload", sa.JSON(), nullable=False),
        sa.Column("resource_payload", sa.JSON(), nullable=True),
        sa.Column(
            "heartbeat_sequence",
            sa.BigInteger(),
            server_default=sa.text("-1"),
            nullable=False,
        ),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("worker_id", name="pk_workers"),
    )
    op.create_index(
        "ix_workers_last_heartbeat_at",
        "workers",
        ["last_heartbeat_at"],
        unique=False,
    )
    op.create_index("ix_workers_status", "workers", ["status"], unique=False)

    op.create_table(
        "uploaded_files",
        sa.Column("file_id", sa.String(length=72), nullable=False),
        sa.Column("filename", sa.String(length=512), nullable=False),
        sa.Column("mime_type", sa.String(length=255), nullable=False),
        sa.Column("media_category", sa.String(length=32), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("storage_uri", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("file_id", name="pk_uploaded_files"),
        sa.UniqueConstraint("storage_key", name="uq_uploaded_files_storage_key"),
    )
    op.create_index(
        "ix_uploaded_files_expires_at",
        "uploaded_files",
        ["expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_uploaded_files_media_category",
        "uploaded_files",
        ["media_category"],
        unique=False,
    )
    op.create_index(
        "ix_uploaded_files_sha256",
        "uploaded_files",
        ["sha256"],
        unique=False,
    )

    op.create_table(
        "artifacts",
        sa.Column("artifact_id", sa.String(length=72), nullable=False),
        sa.Column("task_id", sa.String(length=72), nullable=False),
        sa.Column("stage_id", sa.String(length=72), nullable=True),
        sa.Column("worker_id", sa.String(length=72), nullable=True),
        sa.Column("artifact_type", sa.String(length=64), nullable=False),
        sa.Column("filename", sa.String(length=512), nullable=False),
        sa.Column("mime_type", sa.String(length=255), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("storage_uri", sa.Text(), nullable=False),
        sa.Column("idempotency_digest", sa.LargeBinary(length=32), nullable=True),
        sa.Column("request_digest", sa.LargeBinary(length=32), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["tasks.task_id"],
            name="fk_artifacts_task_id_tasks",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("artifact_id", name="pk_artifacts"),
        sa.UniqueConstraint("storage_key", name="uq_artifacts_storage_key"),
        sa.UniqueConstraint(
            "stage_id",
            "idempotency_digest",
            name="uq_artifacts_stage_idempotency",
        ),
    )
    op.create_index(
        "ix_artifacts_artifact_type",
        "artifacts",
        ["artifact_type"],
        unique=False,
    )
    op.create_index(
        "ix_artifacts_expires_at",
        "artifacts",
        ["expires_at"],
        unique=False,
    )
    op.create_index("ix_artifacts_sha256", "artifacts", ["sha256"], unique=False)
    op.create_index("ix_artifacts_stage_id", "artifacts", ["stage_id"], unique=False)
    op.create_index("ix_artifacts_task_id", "artifacts", ["task_id"], unique=False)
    op.create_index("ix_artifacts_worker_id", "artifacts", ["worker_id"], unique=False)

    op.create_table(
        "stages",
        sa.Column("stage_id", sa.String(length=72), nullable=False),
        sa.Column("task_id", sa.String(length=72), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("depends_on_payload", sa.JSON(), nullable=False),
        sa.Column(
            "optional",
            sa.Boolean(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "progress_percent",
            sa.Float(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("backend_id", sa.String(length=72), nullable=True),
        sa.Column("backend_version", sa.String(length=64), nullable=True),
        sa.Column("backend_candidates_payload", sa.JSON(), nullable=False),
        sa.Column("worker_id", sa.String(length=72), nullable=True),
        sa.Column("runtime", sa.String(length=32), nullable=True),
        sa.Column("required_runtimes_payload", sa.JSON(), nullable=False),
        sa.Column(
            "attempt",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "maximum_attempts",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column("lease_token_digest", sa.LargeBinary(length=32), nullable=True),
        sa.Column("completion_worker_id", sa.String(length=72), nullable=True),
        sa.Column(
            "completion_lease_token_digest",
            sa.LargeBinary(length=32),
            nullable=True,
        ),
        sa.Column(
            "completion_request_digest",
            sa.LargeBinary(length=32),
            nullable=True,
        ),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("retry_policy_payload", sa.JSON(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("result_uri", sa.Text(), nullable=True),
        sa.Column("error_payload", sa.JSON(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["tasks.task_id"],
            name="fk_stages_task_id_tasks",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("stage_id", name="pk_stages"),
        sa.UniqueConstraint("task_id", "name", name="uq_stages_task_name"),
        sa.UniqueConstraint(
            "task_id",
            "position",
            name="uq_stages_task_position",
        ),
    )
    op.create_index("ix_stages_backend_id", "stages", ["backend_id"], unique=False)
    op.create_index(
        "ix_stages_available_at",
        "stages",
        ["available_at"],
        unique=False,
    )
    op.create_index(
        "ix_stages_lease_expires_at",
        "stages",
        ["lease_expires_at"],
        unique=False,
    )
    op.create_index("ix_stages_status", "stages", ["status"], unique=False)
    op.create_index("ix_stages_task_id", "stages", ["task_id"], unique=False)
    op.create_index("ix_stages_worker_id", "stages", ["worker_id"], unique=False)


def downgrade() -> None:
    op.drop_table("stages")
    op.drop_table("artifacts")
    op.drop_table("uploaded_files")
    op.drop_table("workers")
    op.drop_table("tasks")
    op.drop_table("pipelines")
    op.drop_table("events")
    op.drop_table("callback_deliveries")
    op.drop_table("backends")
    op.drop_table("api_keys")

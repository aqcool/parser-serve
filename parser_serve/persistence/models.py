"""SQLAlchemy persistence models for the control plane."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from ..schema.base import JsonValue


NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class ApiKeyRecord(TimestampMixin, Base):
    __tablename__ = "api_keys"

    api_key_id: Mapped[str] = mapped_column(String(72), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    kind: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        index=True,
        server_default="ordinary",
    )
    worker_id: Mapped[str | None] = mapped_column(
        String(72),
        nullable=True,
        index=True,
    )
    prefix: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    digest: Mapped[bytes] = mapped_column(
        LargeBinary(32),
        nullable=False,
        unique=True,
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="1",
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class SystemSettingRecord(TimestampMixin, Base):
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value_payload: Mapped[JsonValue] = mapped_column(JSON, nullable=False)


class TaskRecord(TimestampMixin, Base):
    __tablename__ = "tasks"

    task_id: Mapped[str] = mapped_column(String(72), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    progress_percent: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
        server_default="0",
    )
    source_payload: Mapped[dict[str, JsonValue]] = mapped_column(
        JSON,
        nullable=False,
    )
    source_metadata_payload: Mapped[dict[str, JsonValue] | None] = mapped_column(
        JSON,
        nullable=True,
    )
    media_category: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
        index=True,
    )
    options_payload: Mapped[dict[str, JsonValue]] = mapped_column(
        JSON,
        nullable=False,
    )
    callback_payload: Mapped[dict[str, JsonValue] | None] = mapped_column(
        JSON,
        nullable=True,
    )
    trace_context_payload: Mapped[dict[str, JsonValue] | None] = mapped_column(
        JSON,
        nullable=True,
    )
    pipeline_id: Mapped[str | None] = mapped_column(
        String(72),
        nullable=True,
        index=True,
    )
    pipeline_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    backend_name: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
        index=True,
    )
    requested_runtime: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
        index=True,
    )
    priority: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    client_reference: Mapped[str | None] = mapped_column(
        String(256),
        nullable=True,
        index=True,
    )
    idempotency_digest: Mapped[bytes | None] = mapped_column(
        LargeBinary(32),
        nullable=True,
        unique=True,
    )
    request_digest: Mapped[bytes | None] = mapped_column(
        LargeBinary(32),
        nullable=True,
    )
    result_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_payload: Mapped[dict[str, JsonValue] | None] = mapped_column(
        JSON,
        nullable=True,
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    stages: Mapped[list[StageRecord]] = relationship(
        back_populates="task",
        cascade="all, delete-orphan",
    )
    artifacts: Mapped[list[ArtifactRecord]] = relationship(
        back_populates="task",
        cascade="all, delete-orphan",
    )

    __table_args__ = (Index("ix_tasks_created_at_task_id", "created_at", "task_id"),)


class StageRecord(TimestampMixin, Base):
    __tablename__ = "stages"

    stage_id: Mapped[str] = mapped_column(String(72), primary_key=True)
    task_id: Mapped[str] = mapped_column(
        ForeignKey("tasks.task_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    depends_on_payload: Mapped[list[JsonValue]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    optional: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="0",
    )
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    progress_percent: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
        server_default="0",
    )
    backend_id: Mapped[str | None] = mapped_column(
        String(72),
        nullable=True,
        index=True,
    )
    backend_version: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    backend_candidates_payload: Mapped[list[JsonValue]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    worker_id: Mapped[str | None] = mapped_column(
        String(72),
        nullable=True,
        index=True,
    )
    runtime: Mapped[str | None] = mapped_column(String(32), nullable=True)
    device_id: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
        index=True,
    )
    required_runtimes_payload: Mapped[list[JsonValue]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    attempt: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    maximum_attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )
    lease_token_digest: Mapped[bytes | None] = mapped_column(
        LargeBinary(32),
        nullable=True,
    )
    completion_worker_id: Mapped[str | None] = mapped_column(
        String(72),
        nullable=True,
    )
    completion_lease_token_digest: Mapped[bytes | None] = mapped_column(
        LargeBinary(32),
        nullable=True,
    )
    completion_request_digest: Mapped[bytes | None] = mapped_column(
        LargeBinary(32),
        nullable=True,
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    parameters: Mapped[dict[str, JsonValue]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    retry_policy_payload: Mapped[dict[str, JsonValue]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    result_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_payload: Mapped[dict[str, JsonValue] | None] = mapped_column(
        JSON,
        nullable=True,
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    task: Mapped[TaskRecord] = relationship(back_populates="stages")

    __table_args__ = (
        UniqueConstraint("task_id", "name", name="uq_stages_task_name"),
        UniqueConstraint(
            "task_id",
            "position",
            name="uq_stages_task_position",
        ),
    )


class EventRecord(Base):
    __tablename__ = "events"

    event_id: Mapped[str] = mapped_column(String(72), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    task_id: Mapped[str | None] = mapped_column(
        String(72),
        nullable=True,
        index=True,
    )
    worker_id: Mapped[str | None] = mapped_column(
        String(72),
        nullable=True,
        index=True,
    )
    payload: Mapped[dict[str, JsonValue]] = mapped_column(JSON, nullable=False)
    callback_processed: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="0",
        index=True,
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )


class WorkerRecord(TimestampMixin, Base):
    __tablename__ = "workers"

    worker_id: Mapped[str] = mapped_column(String(72), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    hostname: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="1",
    )
    maximum_concurrency: Mapped[int] = mapped_column(Integer, nullable=False)
    scheduling_weight: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=100,
        server_default="100",
    )
    devices_payload: Mapped[list[JsonValue]] = mapped_column(JSON, nullable=False)
    device_usage_payload: Mapped[list[JsonValue]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    backends_payload: Mapped[list[JsonValue]] = mapped_column(JSON, nullable=False)
    labels_payload: Mapped[dict[str, JsonValue]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    resource_payload: Mapped[dict[str, JsonValue] | None] = mapped_column(
        JSON,
        nullable=True,
    )
    heartbeat_sequence: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=-1,
        server_default="-1",
    )
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )


class PipelineRecord(TimestampMixin, Base):
    __tablename__ = "pipelines"

    record_id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )
    pipeline_id: Mapped[str] = mapped_column(String(72), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    definition_payload: Mapped[dict[str, JsonValue]] = mapped_column(
        JSON,
        nullable=False,
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    __table_args__ = (
        UniqueConstraint(
            "pipeline_id",
            "version",
            name="uq_pipelines_id_version",
        ),
    )


class BackendRecord(TimestampMixin, Base):
    __tablename__ = "backends"

    backend_id: Mapped[str] = mapped_column(String(72), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    execution_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    definition_payload: Mapped[dict[str, JsonValue]] = mapped_column(
        JSON,
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_backends_name_version"),
    )


class CallbackDeliveryRecord(TimestampMixin, Base):
    __tablename__ = "callback_deliveries"

    delivery_id: Mapped[str] = mapped_column(String(72), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(72), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    task_id: Mapped[str] = mapped_column(String(72), nullable=False, index=True)
    target_url: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    attempt: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    attempt_sequence: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    maximum_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    event_payload: Mapped[dict[str, JsonValue]] = mapped_column(
        JSON,
        nullable=False,
    )
    response_status_code: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    response_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    __table_args__ = (
        UniqueConstraint("event_id", name="uq_callback_deliveries_event_id"),
    )


class CallbackAttemptRecord(Base):
    __tablename__ = "callback_attempts"

    attempt_id: Mapped[str] = mapped_column(String(72), primary_key=True)
    delivery_id: Mapped[str] = mapped_column(
        ForeignKey("callback_deliveries.delivery_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    delivered: Mapped[bool] = mapped_column(Boolean, nullable=False)
    response_status_code: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    response_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    error_payload: Mapped[dict[str, JsonValue] | None] = mapped_column(
        JSON,
        nullable=True,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )

    __table_args__ = (
        UniqueConstraint(
            "delivery_id",
            "sequence",
            name="uq_callback_attempts_delivery_sequence",
        ),
    )


class UploadedFileRecord(Base):
    __tablename__ = "uploaded_files"

    file_id: Mapped[str] = mapped_column(String(72), primary_key=True)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(255), nullable=False)
    media_category: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        index=True,
    )
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    storage_uri: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )


class ArtifactRecord(Base):
    __tablename__ = "artifacts"

    artifact_id: Mapped[str] = mapped_column(String(72), primary_key=True)
    task_id: Mapped[str] = mapped_column(
        ForeignKey("tasks.task_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    stage_id: Mapped[str | None] = mapped_column(
        String(72),
        nullable=True,
        index=True,
    )
    worker_id: Mapped[str | None] = mapped_column(
        String(72),
        nullable=True,
        index=True,
    )
    artifact_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    storage_uri: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_digest: Mapped[bytes | None] = mapped_column(
        LargeBinary(32),
        nullable=True,
    )
    request_digest: Mapped[bytes | None] = mapped_column(
        LargeBinary(32),
        nullable=True,
    )
    artifact_metadata: Mapped[dict[str, JsonValue]] = mapped_column(
        "metadata",
        JSON,
        nullable=False,
        default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    task: Mapped[TaskRecord] = relationship(back_populates="artifacts")

    __table_args__ = (
        UniqueConstraint(
            "stage_id",
            "idempotency_digest",
            name="uq_artifacts_stage_idempotency",
        ),
    )


__all__ = [
    "ApiKeyRecord",
    "ArtifactRecord",
    "BackendRecord",
    "Base",
    "CallbackAttemptRecord",
    "CallbackDeliveryRecord",
    "EventRecord",
    "PipelineRecord",
    "StageRecord",
    "SystemSettingRecord",
    "TaskRecord",
    "UploadedFileRecord",
    "WorkerRecord",
]

"""Application settings loaded from environment variables."""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from datetime import datetime

from pydantic import (
    AnyHttpUrl,
    Field,
    RedisDsn,
    SecretStr,
    TypeAdapter,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

from .schema.authentication import ApiKeyValue


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class StorageBackend(StrEnum):
    LOCAL = "local"
    S3 = "s3"


class TaskQueueBackend(StrEnum):
    DATABASE = "database"
    REDIS_STREAMS = "redis_streams"


class LogFormat(StrEnum):
    JSON = "json"
    TEXT = "text"


_api_key_adapter = TypeAdapter(ApiKeyValue)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PARSER_SERVE_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    app_name: str = "Parser Serve"
    app_version: str = "0.1.0"
    api_version: str = "1.0"
    result_schema_version: str = "1.0"
    build_commit: str | None = Field(
        default=None,
        min_length=7,
        max_length=64,
        pattern=r"^[0-9A-Za-z._-]+$",
    )
    build_time: datetime | None = None
    log_level: str = "INFO"
    log_format: LogFormat = LogFormat.JSON
    metrics_enabled: bool = True
    otel_enabled: bool = False
    otel_service_name: str = "parser-serve-control-plane"
    otel_exporter_endpoint: AnyHttpUrl | None = None
    otel_sample_ratio: float = Field(default=1.0, ge=0.0, le=1.0)
    environment: Environment = Environment.DEVELOPMENT
    api_keys: list[SecretStr] = Field(default_factory=list)
    worker_api_keys: list[SecretStr] = Field(default_factory=list)
    maximum_upload_bytes: int = 100 * 1024 * 1024
    maximum_result_json_bytes: int = 16 * 1024 * 1024
    local_storage_path: Path = Path("./data/storage")
    storage_backend: StorageBackend = StorageBackend.LOCAL
    s3_storage_bucket: str | None = None
    s3_storage_prefix: str = "parser-serve"
    s3_storage_endpoint_url: AnyHttpUrl | None = None
    s3_storage_region_name: str | None = None
    artifact_download_url_expires_seconds: int = 300
    uploaded_file_retention_seconds: int | None = Field(
        default=86_400,
        ge=60,
        le=31_536_000,
    )
    artifact_retention_seconds: int | None = Field(
        default=2_592_000,
        ge=60,
        le=315_360_000,
    )
    event_retention_seconds: int | None = Field(
        default=604_800,
        ge=60,
        le=315_360_000,
    )
    retention_cleanup_enabled: bool = True
    retention_cleanup_interval_seconds: float = Field(
        default=300.0,
        gt=0.0,
        le=86_400.0,
    )
    retention_cleanup_batch_size: int = Field(
        default=500,
        ge=1,
        le=10_000,
    )
    database_url: str = (
        "postgresql+asyncpg://parser_serve:parser_serve@localhost/parser_serve"
    )
    database_echo: bool = False
    worker_heartbeat_interval_seconds: int = 15
    worker_offline_after_seconds: int = 45
    stage_lease_duration_seconds: int = 60
    scheduler_maximum_device_memory_utilization_percent: float = Field(
        default=95.0,
        gt=0.0,
        le=100.0,
    )
    task_queue_backend: TaskQueueBackend = TaskQueueBackend.DATABASE
    redis_url: RedisDsn = RedisDsn("redis://localhost:6379/0")
    redis_stage_stream_key: str = "parser-serve:stage-availability"
    redis_stage_stream_maximum_length: int = 10_000
    worker_lease_wait_maximum_seconds: float = Field(
        default=30.0,
        gt=0.0,
        le=30.0,
    )
    routing_poll_interval_seconds: float = 1.0
    routing_batch_size: int = 100
    sse_poll_interval_seconds: float = 1.0
    sse_heartbeat_seconds: float = 15.0
    sse_maximum_send_delay_seconds: float = Field(
        default=30.0,
        gt=0.0,
        le=3600.0,
    )
    callback_dispatcher_enabled: bool = False
    callback_timeout_seconds: float = 10.0
    callback_maximum_attempts: int = 5
    callback_initial_retry_seconds: float = 2.0
    callback_maximum_retry_seconds: float = 300.0
    callback_poll_interval_seconds: float = 1.0
    callback_claim_timeout_seconds: float = 60.0
    callback_response_summary_bytes: int = 1024
    mcp_allowed_hosts: list[str] = Field(
        default_factory=lambda: [
            "127.0.0.1:*",
            "localhost:*",
            "[::1]:*",
        ]
    )
    mcp_allowed_origins: list[str] = Field(
        default_factory=lambda: [
            "http://127.0.0.1:*",
            "http://localhost:*",
            "http://[::1]:*",
        ]
    )
    cors_allowed_origins: list[str] = Field(
        default_factory=lambda: [
            "http://127.0.0.1:5173",
            "http://localhost:5173",
        ]
    )

    @field_validator("api_keys", "worker_api_keys")
    @classmethod
    def validate_api_keys(cls, values: list[SecretStr]) -> list[SecretStr]:
        plaintext = [value.get_secret_value() for value in values]
        for value in plaintext:
            _api_key_adapter.validate_python(value)
        if len(plaintext) != len(set(plaintext)):
            raise ValueError("API keys must be unique")
        return values

    @model_validator(mode="after")
    def validate_telemetry(self) -> Settings:
        if self.otel_enabled and self.otel_exporter_endpoint is None:
            raise ValueError(
                "otel_exporter_endpoint is required when OpenTelemetry is enabled"
            )
        return self

    @field_validator(
        "mcp_allowed_hosts",
        "mcp_allowed_origins",
        "cors_allowed_origins",
    )
    @classmethod
    def validate_mcp_allowlists(cls, values: list[str]) -> list[str]:
        if not values or any(not value.strip() for value in values):
            raise ValueError("origin and host allowlists must not be empty")
        if len(values) != len(set(values)):
            raise ValueError("origin and host allowlists must be unique")
        return values

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        normalized = value.upper()
        if normalized not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("log_level is invalid")
        return normalized

    @field_validator("build_commit", "build_time", mode="before")
    @classmethod
    def empty_build_metadata_is_unset(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("build_time")
    @classmethod
    def validate_build_time(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("build_time must include a timezone")
        return value

    @field_validator("maximum_upload_bytes", "maximum_result_json_bytes")
    @classmethod
    def validate_maximum_upload_bytes(cls, value: int) -> int:
        if value < 1:
            raise ValueError("byte limit settings must be greater than zero")
        return value

    @field_validator("artifact_download_url_expires_seconds")
    @classmethod
    def validate_download_expiration(cls, value: int) -> int:
        if not 1 <= value <= 86_400:
            raise ValueError(
                "artifact_download_url_expires_seconds must be between 1 and 86400"
            )
        return value

    @field_validator(
        "worker_heartbeat_interval_seconds",
        "worker_offline_after_seconds",
        "stage_lease_duration_seconds",
    )
    @classmethod
    def validate_positive_seconds(cls, value: int) -> int:
        if value < 1:
            raise ValueError("duration settings must be greater than zero")
        return value

    @model_validator(mode="after")
    def validate_worker_timing(self) -> Settings:
        if self.worker_offline_after_seconds < self.worker_heartbeat_interval_seconds:
            raise ValueError(
                "worker_offline_after_seconds cannot be shorter than heartbeat interval"
            )
        return self

    @model_validator(mode="after")
    def validate_storage(self) -> Settings:
        if self.storage_backend is StorageBackend.S3 and not self.s3_storage_bucket:
            raise ValueError("s3_storage_bucket is required for S3 storage")
        if self.s3_storage_bucket and (
            "/" in self.s3_storage_bucket or "\\" in self.s3_storage_bucket
        ):
            raise ValueError("s3_storage_bucket is invalid")
        return self

    @field_validator(
        "sse_poll_interval_seconds",
        "sse_heartbeat_seconds",
        "sse_maximum_send_delay_seconds",
        "callback_timeout_seconds",
        "callback_initial_retry_seconds",
        "callback_maximum_retry_seconds",
        "callback_poll_interval_seconds",
        "callback_claim_timeout_seconds",
        "routing_poll_interval_seconds",
        "worker_lease_wait_maximum_seconds",
        "scheduler_maximum_device_memory_utilization_percent",
        "retention_cleanup_interval_seconds",
    )
    @classmethod
    def validate_positive_float(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("timing settings must be greater than zero")
        return value

    @field_validator("callback_maximum_attempts")
    @classmethod
    def validate_callback_attempts(cls, value: int) -> int:
        if not 1 <= value <= 20:
            raise ValueError("callback_maximum_attempts must be between 1 and 20")
        return value

    @field_validator("callback_response_summary_bytes")
    @classmethod
    def validate_callback_summary_bytes(cls, value: int) -> int:
        if not 1 <= value <= 65_536:
            raise ValueError(
                "callback_response_summary_bytes must be between 1 and 65536"
            )
        return value

    @field_validator("routing_batch_size")
    @classmethod
    def validate_routing_batch_size(cls, value: int) -> int:
        if not 1 <= value <= 10_000:
            raise ValueError("routing_batch_size must be between 1 and 10000")
        return value

    @field_validator("redis_stage_stream_key")
    @classmethod
    def validate_redis_stream_key(cls, value: str) -> str:
        if not value or len(value) > 512:
            raise ValueError("redis_stage_stream_key must contain 1 to 512 characters")
        return value

    @field_validator("redis_stage_stream_maximum_length")
    @classmethod
    def validate_redis_stream_length(cls, value: int) -> int:
        if not 100 <= value <= 10_000_000:
            raise ValueError(
                "redis_stage_stream_maximum_length must be between 100 and 10000000"
            )
        return value

    @model_validator(mode="after")
    def validate_callback_retry_timing(self) -> Settings:
        if self.callback_maximum_retry_seconds < self.callback_initial_retry_seconds:
            raise ValueError(
                "callback_maximum_retry_seconds cannot be shorter than initial retry"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


__all__ = [
    "Environment",
    "LogFormat",
    "Settings",
    "StorageBackend",
    "TaskQueueBackend",
    "get_settings",
]

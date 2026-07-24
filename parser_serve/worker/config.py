"""CPU Worker environment configuration."""

from __future__ import annotations

from pydantic import (
    AnyHttpUrl,
    Field,
    SecretStr,
    TypeAdapter,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

from ..schema.authentication import ApiKeyValue
from ..schema.backend import BackendLoadTarget
from ..schema.common import WorkerId
from ..schema.hardware import DeviceRuntime, HardwareVendor
from ..schema.engine import EngineBackendConfig
from ..schema.remote import RemoteBackendConfig
from ..settings import LogFormat


_worker_id_adapter = TypeAdapter(WorkerId)
_api_key_adapter = TypeAdapter(ApiKeyValue)


class WorkerSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PARSER_WORKER_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    control_plane_url: AnyHttpUrl = AnyHttpUrl("http://127.0.0.1:8000")
    api_key: SecretStr
    worker_id: str
    name: str = "Parser CPU Worker"
    version: str = "0.1.0"
    log_level: str = "INFO"
    log_format: LogFormat = LogFormat.JSON
    otel_enabled: bool = False
    otel_service_name: str = "parser-serve-worker"
    otel_exporter_endpoint: AnyHttpUrl | None = None
    otel_sample_ratio: float = Field(default=1.0, ge=0.0, le=1.0)
    maximum_concurrency: int = Field(default=2, ge=1, le=100)
    poll_interval_seconds: float = Field(default=1.0, gt=0.0, le=60.0)
    lease_wait_seconds: float = Field(default=20.0, ge=0.0, le=30.0)
    request_timeout_seconds: float = Field(default=60.0, gt=0.0)
    maximum_url_download_bytes: int = Field(
        default=25 * 1024 * 1024,
        ge=1,
    )
    url_download_timeout_seconds: float = Field(default=30.0, gt=0.0)
    maximum_url_redirects: int = Field(default=5, ge=0, le=20)
    allowed_s3_buckets: list[str] = Field(default_factory=list)
    s3_endpoint_url: AnyHttpUrl | None = None
    s3_region_name: str | None = None
    maximum_object_download_bytes: int = Field(
        default=100 * 1024 * 1024,
        ge=1,
    )
    maximum_pdf_pages: int = Field(default=1000, ge=1, le=1_000_000)
    maximum_image_pixels: int = Field(
        default=100_000_000,
        ge=1,
        le=1_000_000_000,
    )
    maximum_media_duration_seconds: float = Field(
        default=14_400.0,
        gt=0.0,
        le=604_800.0,
    )
    subprocess_maximum_memory_bytes: int = Field(
        default=4 * 1024 * 1024 * 1024,
        ge=64 * 1024 * 1024,
    )
    subprocess_maximum_cpu_seconds: int = Field(default=900, ge=1, le=86_400)
    subprocess_maximum_output_file_bytes: int = Field(
        default=1024 * 1024 * 1024,
        ge=1024 * 1024,
    )
    subprocess_maximum_processes: int = Field(default=64, ge=1, le=4096)
    subprocess_resource_limits_required: bool = False
    device_runtime: DeviceRuntime = DeviceRuntime.CPU
    device_vendor: HardwareVendor = HardwareVendor.GENERIC
    device_id: str = "cpu-0"
    device_model: str = "Generic CPU"
    device_total_memory_bytes: int | None = Field(default=None, ge=0)
    device_driver_version: str | None = None
    device_runtime_version: str | None = None
    device_probe_command: list[str] = Field(default_factory=list)
    device_probe_timeout_seconds: float = Field(default=5.0, gt=0.0, le=60.0)
    device_probe_maximum_output_bytes: int = Field(
        default=1024 * 1024,
        ge=1024,
        le=16 * 1024 * 1024,
    )
    device_probe_required: bool = False
    remote_backends: list[RemoteBackendConfig] = Field(default_factory=list)
    engine_backends: list[EngineBackendConfig] = Field(default_factory=list)
    preload_backends: list[BackendLoadTarget] = Field(default_factory=list)
    labels: dict[str, str] = Field(default_factory=dict)

    @field_validator("worker_id")
    @classmethod
    def validate_worker_id(cls, value: str) -> str:
        return _worker_id_adapter.validate_python(value)

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, value: SecretStr) -> SecretStr:
        _api_key_adapter.validate_python(value.get_secret_value())
        return value

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        normalized = value.upper()
        if normalized not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("log_level is invalid")
        return normalized

    @field_validator("allowed_s3_buckets")
    @classmethod
    def validate_s3_buckets(cls, values: list[str]) -> list[str]:
        if any(not value or "/" in value or "\\" in value for value in values):
            raise ValueError("allowed_s3_buckets contains an invalid bucket")
        if len(values) != len(set(values)):
            raise ValueError("allowed_s3_buckets must be unique")
        return values

    @model_validator(mode="after")
    def validate_device(self) -> WorkerSettings:
        expected_vendor = {
            DeviceRuntime.CUDA: HardwareVendor.NVIDIA,
            DeviceRuntime.ASCEND: HardwareVendor.HUAWEI,
            DeviceRuntime.MLU: HardwareVendor.CAMBRICON,
            DeviceRuntime.DCU: HardwareVendor.HYGON,
            DeviceRuntime.MUSA: HardwareVendor.MOORE_THREADS,
            DeviceRuntime.XPU: HardwareVendor.KUNLUN,
        }.get(self.device_runtime)
        if expected_vendor is not None and self.device_vendor is not expected_vendor:
            raise ValueError(
                f"device_runtime {self.device_runtime.value} requires "
                f"device_vendor {expected_vendor.value}"
            )
        backend_keys = [
            (backend.name, backend.version) for backend in self.remote_backends
        ]
        backend_keys.extend(
            (backend.engine.value, backend.version) for backend in self.engine_backends
        )
        if len(backend_keys) != len(set(backend_keys)):
            raise ValueError("remote Backend name and version pairs must be unique")
        preload_keys = [
            (backend.name, backend.version) for backend in self.preload_backends
        ]
        if len(preload_keys) != len(set(preload_keys)):
            raise ValueError("preload_backends must be unique")
        if self.device_probe_command and any(
            not argument or "\x00" in argument for argument in self.device_probe_command
        ):
            raise ValueError("device_probe_command contains an invalid argument")
        return self

    @model_validator(mode="after")
    def validate_request_timeout(self) -> WorkerSettings:
        if self.request_timeout_seconds <= self.lease_wait_seconds:
            raise ValueError(
                "request_timeout_seconds must be longer than lease_wait_seconds"
            )
        return self

    @model_validator(mode="after")
    def validate_telemetry(self) -> WorkerSettings:
        if self.otel_enabled and self.otel_exporter_endpoint is None:
            raise ValueError(
                "otel_exporter_endpoint is required when OpenTelemetry is enabled"
            )
        return self


__all__ = ["WorkerSettings"]

"""Hardware capabilities and scheduling requirements."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import Field, model_validator

from .base import StrictSchema
from .common import NonEmptyStr, SchemaVersion


class HardwareVendor(StrEnum):
    GENERIC = "generic"
    NVIDIA = "nvidia"
    HUAWEI = "huawei"
    CAMBRICON = "cambricon"
    HYGON = "hygon"
    MOORE_THREADS = "moore_threads"
    KUNLUN = "kunlun"


class DeviceRuntime(StrEnum):
    CPU = "cpu"
    CUDA = "cuda"
    ASCEND = "ascend"
    MLU = "mlu"
    DCU = "dcu"
    MUSA = "musa"
    XPU = "xpu"


class SchedulingStrategy(StrEnum):
    AUTO = "auto"
    PREFER = "prefer"
    REQUIRE = "require"


class DeviceInfo(StrictSchema):
    device_id: NonEmptyStr
    vendor: HardwareVendor
    runtime: DeviceRuntime
    model: NonEmptyStr
    total_memory_bytes: Annotated[int, Field(ge=0, strict=True)] | None = None
    driver_version: NonEmptyStr | None = None
    runtime_version: NonEmptyStr | None = None

    @model_validator(mode="after")
    def validate_vendor_runtime(self) -> DeviceInfo:
        expected_vendor = {
            DeviceRuntime.CUDA: HardwareVendor.NVIDIA,
            DeviceRuntime.ASCEND: HardwareVendor.HUAWEI,
            DeviceRuntime.MLU: HardwareVendor.CAMBRICON,
            DeviceRuntime.DCU: HardwareVendor.HYGON,
            DeviceRuntime.MUSA: HardwareVendor.MOORE_THREADS,
            DeviceRuntime.XPU: HardwareVendor.KUNLUN,
        }.get(self.runtime)
        if expected_vendor is not None and self.vendor is not expected_vendor:
            raise ValueError(
                f"runtime {self.runtime.value} requires vendor {expected_vendor.value}"
            )
        return self


class DeviceRequirement(StrictSchema):
    strategy: SchedulingStrategy = SchedulingStrategy.AUTO
    runtimes: list[DeviceRuntime] = Field(default_factory=list)
    minimum_memory_bytes: Annotated[int, Field(ge=0, strict=True)] | None = None
    worker_labels: dict[NonEmptyStr, NonEmptyStr] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_strategy(self) -> DeviceRequirement:
        if self.strategy is not SchedulingStrategy.AUTO and not self.runtimes:
            raise ValueError("prefer and require strategies need at least one runtime")
        if len(self.runtimes) != len(set(self.runtimes)):
            raise ValueError("runtimes must not contain duplicates")
        return self


class DeviceUsage(StrictSchema):
    device_id: NonEmptyStr
    utilization_percent: (
        Annotated[
            float,
            Field(ge=0.0, le=100.0, strict=True),
        ]
        | None
    ) = None
    memory_used_bytes: Annotated[int, Field(ge=0, strict=True)] | None = None
    memory_total_bytes: Annotated[int, Field(ge=0, strict=True)] | None = None
    temperature_celsius: (
        Annotated[
            float,
            Field(ge=-100.0, le=250.0, strict=True),
        ]
        | None
    ) = None

    @model_validator(mode="after")
    def validate_memory(self) -> DeviceUsage:
        if (
            self.memory_used_bytes is not None
            and self.memory_total_bytes is not None
            and self.memory_used_bytes > self.memory_total_bytes
        ):
            raise ValueError("memory_used_bytes cannot exceed memory_total_bytes")
        return self


class HardwareProbeSnapshot(StrictSchema):
    """Versioned output contract for built-in and vendor device probes."""

    schema_version: SchemaVersion = "1.0"
    devices: Annotated[list[DeviceInfo], Field(min_length=1)]
    usage: list[DeviceUsage] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_device_references(self) -> HardwareProbeSnapshot:
        device_ids = [device.device_id for device in self.devices]
        usage_ids = [item.device_id for item in self.usage]
        if len(device_ids) != len(set(device_ids)):
            raise ValueError("probe device IDs must be unique")
        if len(usage_ids) != len(set(usage_ids)):
            raise ValueError("probe usage device IDs must be unique")
        unknown = set(usage_ids) - set(device_ids)
        if unknown:
            raise ValueError("probe usage must reference a detected device")
        return self


__all__ = [
    "HardwareProbeSnapshot",
    "DeviceInfo",
    "DeviceRequirement",
    "DeviceRuntime",
    "DeviceUsage",
    "HardwareVendor",
    "SchedulingStrategy",
]

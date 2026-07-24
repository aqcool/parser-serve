"""Cross-runtime hardware discovery and utilization sampling."""

from __future__ import annotations

import csv
import os
import platform
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from pydantic import ValidationError

from ..schema.hardware import (
    DeviceInfo,
    DeviceRuntime,
    DeviceUsage,
    HardwareProbeSnapshot,
    HardwareVendor,
)
from .config import WorkerSettings


CommandRunner = Callable[[Sequence[str], float], str]


class HardwareProbeError(RuntimeError):
    """A configured hardware probe could not produce a valid snapshot."""


def run_probe_command(arguments: Sequence[str], timeout_seconds: float) -> str:
    if not arguments:
        raise HardwareProbeError("hardware probe command is empty")
    try:
        completed = subprocess.run(
            list(arguments),
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HardwareProbeError(
            f"hardware probe command failed: {type(exc).__name__}"
        ) from exc
    if completed.returncode != 0:
        raise HardwareProbeError(
            f"hardware probe command exited with status {completed.returncode}"
        )
    return completed.stdout


def _total_memory_bytes() -> int:
    try:
        return int(os.sysconf("SC_PAGE_SIZE")) * int(os.sysconf("SC_PHYS_PAGES"))
    except (AttributeError, OSError, TypeError, ValueError):
        return 0


def _available_memory_bytes() -> int:
    try:
        return int(os.sysconf("SC_PAGE_SIZE")) * int(os.sysconf("SC_AVPHYS_PAGES"))
    except (AttributeError, OSError, TypeError, ValueError):
        return 0


def cpu_device() -> DeviceInfo:
    return DeviceInfo(
        device_id="cpu-0",
        vendor=HardwareVendor.GENERIC,
        runtime=DeviceRuntime.CPU,
        model=platform.processor() or platform.machine() or "Generic CPU",
        total_memory_bytes=_total_memory_bytes(),
    )


def cpu_usage(device_id: str = "cpu-0") -> DeviceUsage:
    total = _total_memory_bytes()
    available = min(_available_memory_bytes(), total)
    processor_count = os.cpu_count() or 1
    try:
        load = os.getloadavg()[0]
        utilization = min(max(load / processor_count * 100.0, 0.0), 100.0)
    except (AttributeError, OSError):
        utilization = None
    return DeviceUsage(
        device_id=device_id,
        utilization_percent=utilization,
        memory_used_bytes=total - available,
        memory_total_bytes=total,
    )


def _csv_rows(output: str, expected_columns: int) -> list[list[str]]:
    rows = [
        [column.strip() for column in row]
        for row in csv.reader(output.splitlines())
        if row and any(column.strip() for column in row)
    ]
    if any(len(row) != expected_columns for row in rows):
        raise HardwareProbeError("hardware probe returned malformed CSV")
    return rows


def nvidia_devices(
    *,
    runner: CommandRunner = run_probe_command,
    timeout_seconds: float = 5.0,
) -> list[DeviceInfo]:
    output = runner(
        (
            "nvidia-smi",
            "--query-gpu=index,name,memory.total,driver_version",
            "--format=csv,noheader,nounits",
        ),
        timeout_seconds,
    )
    try:
        return [
            DeviceInfo(
                device_id=f"cuda-{index}",
                vendor=HardwareVendor.NVIDIA,
                runtime=DeviceRuntime.CUDA,
                model=name,
                total_memory_bytes=int(float(memory_mib) * 1024 * 1024),
                driver_version=driver,
            )
            for index, name, memory_mib, driver in _csv_rows(output, 4)
        ]
    except (ValueError, ValidationError) as exc:
        raise HardwareProbeError("nvidia-smi returned invalid device data") from exc


def nvidia_usage(
    *,
    runner: CommandRunner = run_probe_command,
    timeout_seconds: float = 5.0,
) -> list[DeviceUsage]:
    output = runner(
        (
            "nvidia-smi",
            "--query-gpu=index,utilization.gpu,memory.used,memory.total,temperature.gpu",
            "--format=csv,noheader,nounits",
        ),
        timeout_seconds,
    )
    try:
        return [
            DeviceUsage(
                device_id=f"cuda-{index}",
                utilization_percent=float(utilization),
                memory_used_bytes=int(float(memory_used_mib) * 1024 * 1024),
                memory_total_bytes=int(float(memory_total_mib) * 1024 * 1024),
                temperature_celsius=float(temperature),
            )
            for (
                index,
                utilization,
                memory_used_mib,
                memory_total_mib,
                temperature,
            ) in _csv_rows(output, 5)
        ]
    except (ValueError, ValidationError) as exc:
        raise HardwareProbeError("nvidia-smi returned invalid usage data") from exc


def configured_device(settings: WorkerSettings) -> DeviceInfo:
    if settings.device_runtime is DeviceRuntime.CPU:
        detected = cpu_device()
        model = (
            detected.model
            if settings.device_model == "Generic CPU"
            else settings.device_model
        )
        total_memory = (
            detected.total_memory_bytes
            if settings.device_total_memory_bytes is None
            else settings.device_total_memory_bytes
        )
    else:
        model = settings.device_model
        total_memory = settings.device_total_memory_bytes
    return DeviceInfo(
        device_id=settings.device_id,
        vendor=settings.device_vendor,
        runtime=settings.device_runtime,
        model=model,
        total_memory_bytes=total_memory,
        driver_version=settings.device_driver_version,
        runtime_version=settings.device_runtime_version,
    )


def _validate_expected_hardware(
    snapshot: HardwareProbeSnapshot,
    settings: WorkerSettings,
) -> HardwareProbeSnapshot:
    mismatched = [
        device.device_id
        for device in snapshot.devices
        if device.runtime is not settings.device_runtime
        or device.vendor is not settings.device_vendor
    ]
    if mismatched:
        raise HardwareProbeError(
            "hardware probe returned a runtime or vendor outside Worker configuration"
        )
    return snapshot


@dataclass
class HardwareProbe:
    settings: WorkerSettings
    runner: CommandRunner = run_probe_command

    def __post_init__(self) -> None:
        self._snapshot = self._detect()

    @property
    def devices(self) -> list[DeviceInfo]:
        return list(self._snapshot.devices)

    def _custom_snapshot(self) -> HardwareProbeSnapshot:
        output = self.runner(
            self.settings.device_probe_command,
            self.settings.device_probe_timeout_seconds,
        )
        if (
            len(output.encode("utf-8"))
            > self.settings.device_probe_maximum_output_bytes
        ):
            raise HardwareProbeError("hardware probe output exceeds configured limit")
        try:
            snapshot = HardwareProbeSnapshot.model_validate_json(output)
        except ValidationError as exc:
            raise HardwareProbeError(
                "hardware probe output does not match HardwareProbeSnapshot"
            ) from exc
        return _validate_expected_hardware(snapshot, self.settings)

    def _detect(self) -> HardwareProbeSnapshot:
        try:
            if self.settings.device_probe_command:
                return self._custom_snapshot()
            if self.settings.device_runtime is DeviceRuntime.CUDA:
                devices = nvidia_devices(
                    runner=self.runner,
                    timeout_seconds=self.settings.device_probe_timeout_seconds,
                )
                if not devices:
                    raise HardwareProbeError("nvidia-smi did not report any devices")
                return HardwareProbeSnapshot(devices=devices)
            device = configured_device(self.settings)
            usage = (
                [cpu_usage(device.device_id)]
                if self.settings.device_runtime is DeviceRuntime.CPU
                else []
            )
            return HardwareProbeSnapshot(devices=[device], usage=usage)
        except HardwareProbeError:
            if self.settings.device_probe_required:
                raise
            return HardwareProbeSnapshot(devices=[configured_device(self.settings)])

    def sample_usage(self) -> list[DeviceUsage]:
        try:
            if self.settings.device_probe_command:
                snapshot = self._custom_snapshot()
                known = {device.device_id for device in self._snapshot.devices}
                return [item for item in snapshot.usage if item.device_id in known]
            if self.settings.device_runtime is DeviceRuntime.CUDA:
                known = {device.device_id for device in self._snapshot.devices}
                return [
                    item
                    for item in nvidia_usage(
                        runner=self.runner,
                        timeout_seconds=self.settings.device_probe_timeout_seconds,
                    )
                    if item.device_id in known
                ]
            if self.settings.device_runtime is DeviceRuntime.CPU:
                return [cpu_usage(self._snapshot.devices[0].device_id)]
        except HardwareProbeError:
            if self.settings.device_probe_required:
                raise
        return []


__all__ = [
    "CommandRunner",
    "HardwareProbe",
    "HardwareProbeError",
    "configured_device",
    "cpu_device",
    "cpu_usage",
    "nvidia_devices",
    "nvidia_usage",
    "run_probe_command",
]

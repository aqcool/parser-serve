"""Runnable Worker lifecycle services."""

from __future__ import annotations

import asyncio
import logging
import socket
from collections.abc import Callable, Mapping
from datetime import UTC, datetime

from ..backends import BackendRegistry
from ..schema.backend import BackendCapability
from ..schema.hardware import DeviceInfo
from ..schema.worker import (
    WorkerHeartbeatRequest,
    WorkerHealthCheck,
    WorkerRegistrationRequest,
    WorkerResourceUsage,
    WorkerStatus,
)
from .agent import WorkerAgent
from .client import WorkerControlClient
from .config import WorkerSettings
from .hardware import (
    HardwareProbe,
    HardwareProbeError,
    configured_device,
    cpu_device,
    cpu_usage,
)
from ..utils import ffmpeg_available, libreoffice_available
from ..utils.process_limits import ProcessResourceLimits


_LEGACY_OFFICE_MIME_TYPES = {
    "application/msword",
    "application/vnd.ms-excel",
    "application/vnd.ms-powerpoint",
}
logger = logging.getLogger(__name__)


class WorkerService:
    def __init__(
        self,
        *,
        settings: WorkerSettings,
        client: WorkerControlClient,
        backends: BackendRegistry,
        devices: list[DeviceInfo] | None = None,
        hardware_probe: HardwareProbe | None = None,
        tool_checks: Mapping[str, Callable[[], bool]] | None = None,
    ) -> None:
        self.settings = settings
        self.client = client
        self.backends = backends
        self.hardware_probe = (
            hardware_probe
            if hardware_probe is not None
            else (HardwareProbe(settings) if devices is None else None)
        )
        self.devices = (
            list(devices)
            if devices is not None
            else list(self.hardware_probe.devices if self.hardware_probe else [])
        )
        self.tool_checks = dict(
            tool_checks
            or {
                "ffmpeg": ffmpeg_available,
                "libreoffice": libreoffice_available,
            }
        )
        self._required_tools: set[str] = set()

    def registration(self) -> WorkerRegistrationRequest:
        tool_availability = {
            name: self._tool_available(check)
            for name, check in self.tool_checks.items()
        }
        capabilities = self._registration_capabilities(tool_availability)
        self._required_tools = self._required_tools_for(
            capabilities,
            tool_availability=tool_availability,
        )
        probe_mode = (
            "custom"
            if self.settings.device_probe_command
            else (
                "nvidia-smi"
                if self.settings.device_runtime.value == "cuda"
                else (
                    "builtin"
                    if self.settings.device_runtime.value == "cpu"
                    else "configured"
                )
            )
        )
        labels = {
            **self.settings.labels,
            "parser_serve.hardware.probe": probe_mode,
            "parser_serve.tool.ffmpeg": (
                "available" if tool_availability.get("ffmpeg", False) else "unavailable"
            ),
            "parser_serve.tool.libreoffice": (
                "available"
                if tool_availability.get("libreoffice", False)
                else "unavailable"
            ),
        }
        return WorkerRegistrationRequest(
            worker_id=self.settings.worker_id,
            name=self.settings.name,
            version=self.settings.version,
            hostname=socket.gethostname(),
            devices=self.devices,
            backends=capabilities,
            labels=labels,
            maximum_concurrency=self.settings.maximum_concurrency,
        )

    @staticmethod
    def _tool_available(check: Callable[[], bool]) -> bool:
        try:
            return check()
        except Exception:
            return False

    def _registration_capabilities(
        self,
        tool_availability: Mapping[str, bool],
    ) -> list[BackendCapability]:
        capabilities: list[BackendCapability] = []
        for capability in self.backends.capabilities:
            if capability.name == "builtin_office" and not tool_availability.get(
                "libreoffice", False
            ):
                capability = capability.model_copy(
                    update={
                        "mime_types": [
                            mime_type
                            for mime_type in capability.mime_types
                            if mime_type not in _LEGACY_OFFICE_MIME_TYPES
                        ]
                    }
                )
            capabilities.append(capability)
        return capabilities

    @staticmethod
    def _required_tools_for(
        capabilities: list[BackendCapability],
        *,
        tool_availability: Mapping[str, bool],
    ) -> set[str]:
        required: set[str] = set()
        if tool_availability.get("ffmpeg", False) and any(
            capability.name == "builtin_ffmpeg" for capability in capabilities
        ):
            required.add("ffmpeg")
        if tool_availability.get("libreoffice", False) and any(
            capability.name == "builtin_office"
            and bool(_LEGACY_OFFICE_MIME_TYPES & set(capability.mime_types))
            for capability in capabilities
        ):
            required.add("libreoffice")
        return required

    def _tool_health_checks(self) -> list[WorkerHealthCheck]:
        checks: list[WorkerHealthCheck] = []
        for name in sorted(self._required_tools):
            healthy = self._tool_available(self.tool_checks[name])
            checks.append(
                WorkerHealthCheck(
                    name=name,
                    healthy=healthy,
                    message=None if healthy else f"{name} executable is unavailable",
                )
            )
        return checks

    async def run(self, *, stop: asyncio.Event | None = None) -> None:
        stop_event = stop or asyncio.Event()
        await self.backends.preload(self.settings.preload_backends)
        try:
            registered = await self.client.register(self.registration())
            if not registered.data.accepted:
                raise RuntimeError(
                    "the control plane rejected this Worker registration"
                )
            renew_interval = max(
                min(registered.data.lease_duration_seconds / 3, 20.0),
                1.0,
            )
            agent = WorkerAgent(
                worker_id=self.settings.worker_id,
                client=self.client,
                backends=self.backends,
                maximum_concurrency=self.settings.maximum_concurrency,
                lease_wait_seconds=self.settings.lease_wait_seconds,
                lease_renew_interval_seconds=renew_interval,
                maximum_url_download_bytes=self.settings.maximum_url_download_bytes,
                url_download_timeout_seconds=self.settings.url_download_timeout_seconds,
                maximum_url_redirects=self.settings.maximum_url_redirects,
                allowed_s3_buckets=set(self.settings.allowed_s3_buckets),
                s3_endpoint_url=(
                    str(self.settings.s3_endpoint_url)
                    if self.settings.s3_endpoint_url is not None
                    else None
                ),
                s3_region_name=self.settings.s3_region_name,
                maximum_object_download_bytes=(
                    self.settings.maximum_object_download_bytes
                ),
                process_resource_limits=ProcessResourceLimits(
                    maximum_memory_bytes=self.settings.subprocess_maximum_memory_bytes,
                    maximum_cpu_seconds=self.settings.subprocess_maximum_cpu_seconds,
                    maximum_output_file_bytes=(
                        self.settings.subprocess_maximum_output_file_bytes
                    ),
                    maximum_processes=self.settings.subprocess_maximum_processes,
                    required=self.settings.subprocess_resource_limits_required,
                ),
            )
            async with asyncio.TaskGroup() as tasks:
                tasks.create_task(self._drain_on_stop(stop_event))
                tasks.create_task(
                    self._heartbeat_loop(
                        agent,
                        stop_event,
                        interval_seconds=registered.data.heartbeat_interval_seconds,
                    )
                )
                tasks.create_task(self._poll_loop(agent, stop_event))
        finally:
            try:
                await self.backends.unload_all()
            except Exception:
                logger.warning(
                    "worker_backend_unload_failed",
                    exc_info=True,
                    extra={"worker_id": self.settings.worker_id},
                )

    async def _drain_on_stop(self, stop: asyncio.Event) -> None:
        await stop.wait()
        try:
            await self.client.drain(self.settings.worker_id)
        except Exception:
            logger.warning(
                "worker_drain_notification_failed",
                exc_info=True,
                extra={"worker_id": self.settings.worker_id},
            )

    async def _poll_loop(
        self,
        agent: WorkerAgent,
        stop: asyncio.Event,
    ) -> None:
        while not stop.is_set():
            leased = await agent.run_once()
            if leased == 0:
                await self._wait_or_stop(
                    stop,
                    self.settings.poll_interval_seconds,
                )

    async def _heartbeat_loop(
        self,
        agent: WorkerAgent,
        stop: asyncio.Event,
        *,
        interval_seconds: float,
    ) -> None:
        sequence = 0
        while not stop.is_set():
            probe_failed = False
            try:
                device_usage = (
                    await asyncio.to_thread(self.hardware_probe.sample_usage)
                    if self.hardware_probe is not None
                    else []
                )
            except HardwareProbeError:
                device_usage = []
                probe_failed = True
            health_checks = await asyncio.to_thread(self._tool_health_checks)
            health_checks.append(
                WorkerHealthCheck(
                    name="hardware",
                    healthy=not probe_failed,
                    message=(
                        "hardware utilization probe failed" if probe_failed else None
                    ),
                )
            )
            health_failed = any(not check.healthy for check in health_checks)
            system_usage = cpu_usage()
            memory_total = system_usage.memory_total_bytes or 0
            memory_used = system_usage.memory_used_bytes or 0
            response = await self.client.heartbeat(
                WorkerHeartbeatRequest(
                    worker_id=self.settings.worker_id,
                    sequence=sequence,
                    status=(
                        WorkerStatus.UNHEALTHY
                        if health_failed
                        else (
                            WorkerStatus.BUSY
                            if agent.active_count
                            else WorkerStatus.ONLINE
                        )
                    ),
                    resources=WorkerResourceUsage(
                        cpu_percent=system_usage.utilization_percent or 0.0,
                        memory_used_bytes=memory_used,
                        memory_total_bytes=memory_total,
                        running_tasks=agent.active_count,
                        leased_tasks=agent.active_count,
                        health_checks=health_checks,
                    ),
                    devices=device_usage,
                    timestamp=datetime.now(UTC),
                )
            )
            if (
                health_failed
                or response.data.should_drain
                or not response.data.accepted
            ):
                stop.set()
                return
            sequence += 1
            await self._wait_or_stop(
                stop,
                min(interval_seconds, response.data.next_heartbeat_seconds),
            )

    @staticmethod
    async def _wait_or_stop(stop: asyncio.Event, seconds: float) -> None:
        try:
            await asyncio.wait_for(stop.wait(), timeout=seconds)
        except TimeoutError:
            pass


class CpuWorkerService(WorkerService):
    """Backward-compatible CPU Worker service."""

    def __init__(
        self,
        *,
        settings: WorkerSettings,
        client: WorkerControlClient,
        backends: BackendRegistry,
    ) -> None:
        super().__init__(
            settings=settings,
            client=client,
            backends=backends,
        )


__all__ = [
    "CpuWorkerService",
    "WorkerService",
    "configured_device",
    "cpu_device",
]

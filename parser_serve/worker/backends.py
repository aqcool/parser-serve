"""Build a Worker Backend registry from built-ins and typed configuration."""

from __future__ import annotations

from ..backends import (
    BackendRegistry,
    EngineRemoteBackend,
    RemoteHttpBackend,
    builtin_cpu_backends,
)
from ..schema.hardware import DeviceRuntime
from ..utils.process_limits import ProcessResourceLimits
from .config import WorkerSettings


def configured_backend_registry(settings: WorkerSettings) -> BackendRegistry:
    resource_limits = ProcessResourceLimits(
        maximum_memory_bytes=settings.subprocess_maximum_memory_bytes,
        maximum_cpu_seconds=settings.subprocess_maximum_cpu_seconds,
        maximum_output_file_bytes=settings.subprocess_maximum_output_file_bytes,
        maximum_processes=settings.subprocess_maximum_processes,
        required=settings.subprocess_resource_limits_required,
    )
    registry = (
        builtin_cpu_backends(
            maximum_pdf_pages=settings.maximum_pdf_pages,
            maximum_image_pixels=settings.maximum_image_pixels,
            maximum_media_duration_seconds=(settings.maximum_media_duration_seconds),
            process_resource_limits=resource_limits,
        )
        if settings.device_runtime is DeviceRuntime.CPU
        else BackendRegistry()
    )
    for remote in settings.remote_backends:
        registry.register(
            RemoteHttpBackend(
                config=remote,
                runtime=settings.device_runtime,
            )
        )
    for engine in settings.engine_backends:
        registry.register(
            EngineRemoteBackend(
                config=engine,
                runtime=settings.device_runtime,
            )
        )
    return registry


__all__ = ["configured_backend_registry"]

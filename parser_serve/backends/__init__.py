"""Built-in parser Backend implementations."""

from importlib.util import find_spec

from .base import (
    Backend,
    BackendContext,
    BackendExecutionError,
    BackendOutput,
    BackendRegistry,
    ManagedBackend,
    ProducedArtifact,
)
from .image import ImageMetadataBackend
from .media import FFmpegBackend
from .office import OfficeOpenXmlBackend
from .pdf import PdfBackend
from .remote import RemoteHttpBackend
from .engines import (
    ENGINE_CAPABILITY_PRESETS,
    EngineCapabilityPreset,
    EngineRemoteBackend,
    engine_remote_config,
)
from .text import TextBackend
from .web import StaticWebBackend
from ..utils import ffmpeg_available
from ..utils.process_limits import ProcessResourceLimits


def builtin_cpu_backends(
    *,
    include_unavailable_system_tools: bool = False,
    maximum_pdf_pages: int = 1000,
    maximum_image_pixels: int = 100_000_000,
    maximum_media_duration_seconds: float = 14_400.0,
    process_resource_limits: ProcessResourceLimits | None = None,
) -> BackendRegistry:
    registry = BackendRegistry()
    registry.register(TextBackend())
    registry.register(StaticWebBackend())
    registry.register(OfficeOpenXmlBackend())
    if include_unavailable_system_tools or find_spec("pypdf") is not None:
        registry.register(PdfBackend(maximum_pages=maximum_pdf_pages))
    if include_unavailable_system_tools or find_spec("PIL") is not None:
        registry.register(ImageMetadataBackend(maximum_pixels=maximum_image_pixels))
    if include_unavailable_system_tools or ffmpeg_available():
        registry.register(
            FFmpegBackend(
                maximum_duration_seconds=maximum_media_duration_seconds,
                resource_limits=process_resource_limits,
            )
        )
    return registry


__all__ = [
    "Backend",
    "BackendContext",
    "BackendExecutionError",
    "BackendOutput",
    "BackendRegistry",
    "ManagedBackend",
    "FFmpegBackend",
    "ImageMetadataBackend",
    "OfficeOpenXmlBackend",
    "PdfBackend",
    "RemoteHttpBackend",
    "ENGINE_CAPABILITY_PRESETS",
    "EngineCapabilityPreset",
    "EngineRemoteBackend",
    "engine_remote_config",
    "ProducedArtifact",
    "TextBackend",
    "StaticWebBackend",
    "builtin_cpu_backends",
]

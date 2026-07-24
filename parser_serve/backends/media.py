"""ffprobe metadata and FFmpeg audio extraction Backend."""

from __future__ import annotations

import asyncio

from ..schema.artifact import ArtifactType
from ..schema.backend import BackendCapability
from ..schema.common import MediaCategory
from ..schema.hardware import DeviceRuntime
from ..utils.ffmpeg import FFmpegError, extract_audio_track, probe_media
from ..utils.process_limits import ProcessResourceLimits
from .base import (
    BackendContext,
    BackendExecutionError,
    BackendOutput,
    ProducedArtifact,
)


class FFmpegBackend:
    capability = BackendCapability(
        name="builtin_ffmpeg",
        version="1.0",
        media_categories=[MediaCategory.AUDIO, MediaCategory.VIDEO],
        mime_types=["audio/*", "video/*"],
        runtimes=[DeviceRuntime.CPU],
        maximum_concurrency=2,
    )

    def __init__(
        self,
        *,
        maximum_duration_seconds: float = 14_400.0,
        resource_limits: ProcessResourceLimits | None = None,
    ) -> None:
        if maximum_duration_seconds <= 0:
            raise ValueError("maximum_duration_seconds must be greater than zero")
        self.maximum_duration_seconds = maximum_duration_seconds
        self.resource_limits = resource_limits

    async def execute(self, context: BackendContext) -> BackendOutput:
        if context.source_path is None:
            raise BackendExecutionError(
                "FFmpeg Backend requires a downloaded source file"
            )
        operation = context.lease.parameters.get("operation", "probe")
        if not isinstance(operation, str):
            raise BackendExecutionError("FFmpeg operation must be a string")
        await context.report_progress(10.0)
        try:
            probe = await asyncio.to_thread(
                probe_media,
                context.source_path,
                timeout=min(float(context.lease.timeout_seconds), 30.0),
                resource_limits=self.resource_limits,
            )
            self._validate_duration(probe.duration_seconds)
            if operation == "probe":
                await context.report_progress(90.0)
                return BackendOutput(
                    artifacts=(
                        ProducedArtifact(
                            type=ArtifactType.RESULT_JSON,
                            filename="media-probe.json",
                            mime_type="application/json",
                            data=probe.model_dump_json(indent=2).encode("utf-8"),
                        ),
                    )
                )
            if operation == "extract_audio":
                output = await asyncio.to_thread(
                    extract_audio_track,
                    context.source_path,
                    context.work_dir / "audio.wav",
                    sample_rate=self._positive_parameter(
                        context,
                        "sample_rate",
                        16_000,
                    ),
                    channels=self._positive_parameter(context, "channels", 1),
                    timeout=float(context.lease.timeout_seconds),
                    resource_limits=self.resource_limits,
                )
                await context.report_progress(90.0)
                return BackendOutput(
                    artifacts=(
                        ProducedArtifact(
                            type=ArtifactType.AUDIO_TRACK,
                            filename=output.name,
                            mime_type="audio/wav",
                            path=output,
                        ),
                    )
                )
        except FFmpegError as exc:
            raise BackendExecutionError(str(exc), retryable=True) from exc
        raise BackendExecutionError(f"unsupported FFmpeg operation: {operation!r}")

    def _validate_duration(self, duration_seconds: float | None) -> None:
        if duration_seconds is None:
            raise BackendExecutionError(
                "media duration is unavailable; the Worker limit cannot be enforced"
            )
        if duration_seconds > self.maximum_duration_seconds:
            raise BackendExecutionError(
                f"media duration is {duration_seconds:g} seconds; "
                f"Worker limit is {self.maximum_duration_seconds:g} seconds"
            )

    @staticmethod
    def _positive_parameter(
        context: BackendContext,
        name: str,
        default: int,
    ) -> int:
        value = context.lease.parameters.get(name, default)
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise BackendExecutionError(f"{name} must be a positive integer")
        return value


__all__ = ["FFmpegBackend"]

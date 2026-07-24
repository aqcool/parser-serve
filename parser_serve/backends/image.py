"""Image and photo metadata Backend using Pillow."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path

from ..schema.artifact import ArtifactType
from ..schema.backend import BackendCapability
from ..schema.base import JsonValue
from ..schema.common import MediaCategory
from ..schema.hardware import DeviceRuntime
from ..schema.result import ContentMetadata, ParseResult
from .base import (
    BackendContext,
    BackendExecutionError,
    BackendOutput,
    ProducedArtifact,
)


def _json_value(value: object) -> JsonValue:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    return str(value)


def _image_metadata(
    source: Path,
    *,
    maximum_pixels: int,
) -> tuple[int, int, dict[str, JsonValue]]:
    try:
        image_module = import_module("PIL.Image")
        exif_tags = import_module("PIL.ExifTags")
    except ImportError as exc:
        raise BackendExecutionError("Pillow is not installed in this Worker") from exc
    try:
        with image_module.open(source) as image:
            width, height = image.size
            if width * height > maximum_pixels:
                raise BackendExecutionError(
                    f"image has {width * height} pixels; limit is {maximum_pixels}"
                )
            exif = image.getexif()
            decoded_exif = {
                str(exif_tags.TAGS.get(tag, tag)): _json_value(value)
                for tag, value in exif.items()
            }
            attributes: dict[str, JsonValue] = {
                "format": image.format,
                "mode": image.mode,
                "animated": bool(getattr(image, "is_animated", False)),
                "frame_count": int(getattr(image, "n_frames", 1)),
                "exif": decoded_exif,
            }
            return width, height, attributes
    except BackendExecutionError:
        raise
    except Exception as exc:
        raise BackendExecutionError(
            f"image metadata extraction failed: {type(exc).__name__}"
        ) from exc


class ImageMetadataBackend:
    capability = BackendCapability(
        name="builtin_image",
        version="1.0",
        media_categories=[MediaCategory.IMAGE],
        mime_types=["image/*"],
        runtimes=[DeviceRuntime.CPU],
        maximum_concurrency=8,
    )

    def __init__(self, *, maximum_pixels: int = 100_000_000) -> None:
        if maximum_pixels < 1:
            raise ValueError("maximum_pixels must be greater than zero")
        self.maximum_pixels = maximum_pixels

    async def execute(self, context: BackendContext) -> BackendOutput:
        if context.source_path is None:
            raise BackendExecutionError(
                "image Backend requires a downloaded source file"
            )
        maximum_pixels = self._maximum_pixels(context)
        await context.report_progress(10.0)
        width, height, attributes = await asyncio.to_thread(
            _image_metadata,
            context.source_path,
            maximum_pixels=maximum_pixels,
        )
        await context.report_progress(90.0)
        result = ParseResult(
            schema_version="1.0",
            task_id=context.lease.task_id,
            source=context.lease.source_metadata,
            metadata=ContentMetadata(
                width_pixels=width,
                height_pixels=height,
                attributes=attributes,
            ),
            created_at=datetime.now(UTC),
        )
        return BackendOutput(
            artifacts=(
                ProducedArtifact(
                    type=ArtifactType.RESULT_JSON,
                    filename="image-metadata.json",
                    mime_type="application/json",
                    data=result.model_dump_json(indent=2).encode("utf-8"),
                ),
            )
        )

    def _maximum_pixels(self, context: BackendContext) -> int:
        value = context.lease.parameters.get("maximum_pixels", self.maximum_pixels)
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise BackendExecutionError("maximum_pixels must be a positive integer")
        if value > self.maximum_pixels:
            raise BackendExecutionError(
                f"maximum_pixels cannot exceed the Worker limit {self.maximum_pixels}"
            )
        return value


__all__ = ["ImageMetadataBackend"]

"""Normalized multimodal parsing result contracts."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AnyUrl, Field, model_validator

from .artifact import Artifact
from .base import JsonValue, StrictSchema
from .common import (
    ApiResponse,
    ArtifactId,
    BlockId,
    NonEmptyStr,
    SchemaVersion,
    StageId,
    TaskId,
    UTCDateTime,
)
from .source import SourceMetadata


class BoundingBox(StrictSchema):
    left: Annotated[float, Field(ge=0.0, strict=True)]
    top: Annotated[float, Field(ge=0.0, strict=True)]
    right: Annotated[float, Field(ge=0.0, strict=True)]
    bottom: Annotated[float, Field(ge=0.0, strict=True)]

    @model_validator(mode="after")
    def validate_coordinates(self) -> BoundingBox:
        if self.right < self.left:
            raise ValueError("right cannot be less than left")
        if self.bottom < self.top:
            raise ValueError("bottom cannot be less than top")
        return self


class BlockLocation(StrictSchema):
    page_number: Annotated[int, Field(ge=1, strict=True)] | None = None
    slide_number: Annotated[int, Field(ge=1, strict=True)] | None = None
    sheet_name: NonEmptyStr | None = None
    bounding_box: BoundingBox | None = None
    start_ms: Annotated[int, Field(ge=0, strict=True)] | None = None
    end_ms: Annotated[int, Field(ge=0, strict=True)] | None = None

    @model_validator(mode="after")
    def validate_time_range(self) -> BlockLocation:
        if (
            self.start_ms is not None
            and self.end_ms is not None
            and self.end_ms < self.start_ms
        ):
            raise ValueError("end_ms cannot be earlier than start_ms")
        return self


class TextBlock(StrictSchema):
    type: Literal["text"]
    block_id: BlockId
    text: str
    location: BlockLocation | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class HeadingBlock(StrictSchema):
    type: Literal["heading"]
    block_id: BlockId
    text: NonEmptyStr
    level: Annotated[int, Field(ge=1, le=6, strict=True)]
    location: BlockLocation | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class TableBlock(StrictSchema):
    type: Literal["table"]
    block_id: BlockId
    rows: list[list[str]]
    location: BlockLocation | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class ImageBlock(StrictSchema):
    type: Literal["image"]
    block_id: BlockId
    artifact_id: ArtifactId
    caption: str | None = None
    ocr_text: str | None = None
    location: BlockLocation | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class TranscriptBlock(StrictSchema):
    type: Literal["transcript"]
    block_id: BlockId
    text: NonEmptyStr
    start_ms: Annotated[int, Field(ge=0, strict=True)]
    end_ms: Annotated[int, Field(ge=0, strict=True)]
    speaker: NonEmptyStr | None = None
    language: NonEmptyStr | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_time_range(self) -> TranscriptBlock:
        if self.end_ms < self.start_ms:
            raise ValueError("end_ms cannot be earlier than start_ms")
        return self


class KeyframeBlock(StrictSchema):
    type: Literal["keyframe"]
    block_id: BlockId
    artifact_id: ArtifactId
    timestamp_ms: Annotated[int, Field(ge=0, strict=True)]
    caption: str | None = None
    ocr_text: str | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class LinkBlock(StrictSchema):
    type: Literal["link"]
    block_id: BlockId
    url: AnyUrl
    text: str | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


ContentBlock = Annotated[
    TextBlock
    | HeadingBlock
    | TableBlock
    | ImageBlock
    | TranscriptBlock
    | KeyframeBlock
    | LinkBlock,
    Field(discriminator="type"),
]


class ParseWarning(StrictSchema):
    code: NonEmptyStr
    message: NonEmptyStr
    stage_id: StageId | None = None
    context: dict[str, JsonValue] = Field(default_factory=dict)


class ContentMetadata(StrictSchema):
    title: str | None = None
    language: NonEmptyStr | None = None
    page_count: Annotated[int, Field(ge=0, strict=True)] | None = None
    duration_ms: Annotated[int, Field(ge=0, strict=True)] | None = None
    width_pixels: Annotated[int, Field(ge=0, strict=True)] | None = None
    height_pixels: Annotated[int, Field(ge=0, strict=True)] | None = None
    attributes: dict[str, JsonValue] = Field(default_factory=dict)


class ParseResult(StrictSchema):
    schema_version: SchemaVersion
    task_id: TaskId
    source: SourceMetadata
    metadata: ContentMetadata
    blocks: list[ContentBlock] = Field(default_factory=list)
    artifacts: list[Artifact] = Field(default_factory=list)
    warnings: list[ParseWarning] = Field(default_factory=list)
    created_at: UTCDateTime


ParseResultResponse = ApiResponse[ParseResult]


__all__ = [
    "BlockLocation",
    "BoundingBox",
    "ContentBlock",
    "ContentMetadata",
    "HeadingBlock",
    "ImageBlock",
    "KeyframeBlock",
    "LinkBlock",
    "ParseResult",
    "ParseResultResponse",
    "ParseWarning",
    "TableBlock",
    "TextBlock",
    "TranscriptBlock",
]

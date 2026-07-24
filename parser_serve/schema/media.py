"""Typed ffprobe media metadata."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import Field

from .base import JsonValue, StrictSchema
from .common import NonEmptyStr


class MediaStreamType(StrEnum):
    VIDEO = "video"
    AUDIO = "audio"
    SUBTITLE = "subtitle"
    DATA = "data"
    ATTACHMENT = "attachment"
    UNKNOWN = "unknown"


class MediaStreamInfo(StrictSchema):
    index: Annotated[int, Field(ge=0, strict=True)]
    type: MediaStreamType
    codec_name: NonEmptyStr | None = None
    codec_long_name: NonEmptyStr | None = None
    duration_seconds: Annotated[float, Field(ge=0.0, strict=True)] | None = None
    bit_rate: Annotated[int, Field(ge=0, strict=True)] | None = None
    width: Annotated[int, Field(ge=1, strict=True)] | None = None
    height: Annotated[int, Field(ge=1, strict=True)] | None = None
    frame_rate: Annotated[float, Field(ge=0.0, strict=True)] | None = None
    sample_rate: Annotated[int, Field(ge=1, strict=True)] | None = None
    channels: Annotated[int, Field(ge=1, strict=True)] | None = None
    language: NonEmptyStr | None = None
    tags: dict[str, JsonValue] = Field(default_factory=dict)


class MediaProbe(StrictSchema):
    format_name: NonEmptyStr | None = None
    format_long_name: NonEmptyStr | None = None
    duration_seconds: Annotated[float, Field(ge=0.0, strict=True)] | None = None
    size_bytes: Annotated[int, Field(ge=0, strict=True)] | None = None
    bit_rate: Annotated[int, Field(ge=0, strict=True)] | None = None
    streams: list[MediaStreamInfo] = Field(default_factory=list)
    tags: dict[str, JsonValue] = Field(default_factory=dict)


__all__ = ["MediaProbe", "MediaStreamInfo", "MediaStreamType"]

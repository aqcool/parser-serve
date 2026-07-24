"""Common identifiers, enums, and response envelopes."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Generic, TypeVar

from pydantic import AfterValidator, AwareDatetime, Field, StringConstraints

from .base import StrictSchema


def _identifier(prefix: str) -> StringConstraints:
    return StringConstraints(
        pattern=rf"^{prefix}_[a-zA-Z0-9_-]{{8,64}}$",
        strict=True,
    )


RequestId = Annotated[
    str,
    _identifier("req"),
    Field(examples=["req_01J00000000000000000000000"]),
]
TaskId = Annotated[
    str,
    _identifier("task"),
    Field(examples=["task_01J00000000000000000000000"]),
]
StageId = Annotated[
    str,
    _identifier("stage"),
    Field(examples=["stage_01J00000000000000000000000"]),
]
WorkerId = Annotated[
    str,
    _identifier("worker"),
    Field(examples=["worker_01J00000000000000000000000"]),
]
BackendId = Annotated[
    str,
    _identifier("backend"),
    Field(examples=["backend_01J00000000000000000000000"]),
]
PipelineId = Annotated[
    str,
    _identifier("pipeline"),
    Field(examples=["pipeline_01J00000000000000000000000"]),
]
ArtifactId = Annotated[
    str,
    _identifier("artifact"),
    Field(examples=["artifact_01J00000000000000000000000"]),
]
FileId = Annotated[
    str,
    _identifier("file"),
    Field(examples=["file_01J00000000000000000000000"]),
]
EventId = Annotated[
    str,
    _identifier("event"),
    Field(examples=["event_01J00000000000000000000000"]),
]
ApiKeyId = Annotated[
    str,
    _identifier("key"),
    Field(examples=["key_01J00000000000000000000000"]),
]
BlockId = Annotated[
    str,
    _identifier("block"),
    Field(examples=["block_01J00000000000000000000000"]),
]
CallbackDeliveryId = Annotated[
    str,
    _identifier("delivery"),
    Field(examples=["delivery_01J00000000000000000000000"]),
]
CallbackAttemptId = Annotated[
    str,
    _identifier("attempt"),
    Field(examples=["attempt_01J00000000000000000000000"]),
]
QueueNoticeId = Annotated[
    str,
    _identifier("notice"),
    Field(examples=["notice_01J00000000000000000000000"]),
]

NonEmptyStr = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, strict=True),
]
MimeType = Annotated[
    str,
    StringConstraints(
        pattern=r"^[a-zA-Z0-9!#$&^_.+-]+/[a-zA-Z0-9!#$&^_.+-]+$",
        strict=True,
    ),
    Field(examples=["application/pdf"]),
]
MimePattern = Annotated[
    str,
    StringConstraints(
        pattern=r"^(?:\*|[a-zA-Z0-9!#$&^_.+-]+)/(?:\*|[a-zA-Z0-9!#$&^_.+-]+)$",
        strict=True,
    ),
]
Sha256 = Annotated[
    str,
    StringConstraints(pattern=r"^[a-fA-F0-9]{64}$", to_lower=True, strict=True),
    Field(examples=["a" * 64]),
]
SchemaVersion = Annotated[
    str,
    StringConstraints(pattern=r"^[1-9][0-9]*\.[0-9]+$", strict=True),
    Field(examples=["1.0"]),
]
Cursor = Annotated[str, StringConstraints(min_length=1, max_length=1024, strict=True)]


def _normalize_utc(value: datetime) -> datetime:
    return value.astimezone(UTC)


UTCDateTime = Annotated[
    AwareDatetime,
    AfterValidator(_normalize_utc),
    Field(examples=["2026-07-24T12:00:00Z"]),
]
Percent = Annotated[
    float,
    Field(ge=0.0, le=100.0, strict=True, examples=[50.0]),
]
Priority = Annotated[
    int,
    Field(ge=-100, le=100, strict=True, examples=[0]),
]
PositiveVersion = Annotated[int, Field(ge=1, strict=True, examples=[1])]
StrictBool = Annotated[bool, Field(strict=True)]


class MediaCategory(StrEnum):
    DOCUMENT = "document"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    WEB = "web"
    TEXT = "text"


class SortDirection(StrEnum):
    ASC = "asc"
    DESC = "desc"


DataT = TypeVar("DataT")


class ApiResponse(StrictSchema, Generic[DataT]):
    request_id: RequestId
    data: DataT


class PageInfo(StrictSchema):
    next_cursor: Cursor | None = None
    has_more: StrictBool


class ListResponse(StrictSchema, Generic[DataT]):
    request_id: RequestId
    items: list[DataT] = Field(default_factory=list)
    page: PageInfo


class HealthStatus(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class HealthData(StrictSchema):
    status: HealthStatus
    version: NonEmptyStr
    timestamp: UTCDateTime


HealthResponse = ApiResponse[HealthData]


__all__ = [
    "ApiKeyId",
    "ApiResponse",
    "ArtifactId",
    "BackendId",
    "BlockId",
    "CallbackAttemptId",
    "CallbackDeliveryId",
    "Cursor",
    "EventId",
    "FileId",
    "HealthData",
    "HealthResponse",
    "HealthStatus",
    "ListResponse",
    "MediaCategory",
    "MimePattern",
    "MimeType",
    "NonEmptyStr",
    "PageInfo",
    "Percent",
    "QueueNoticeId",
    "PipelineId",
    "PositiveVersion",
    "Priority",
    "RequestId",
    "SchemaVersion",
    "Sha256",
    "SortDirection",
    "StageId",
    "StrictBool",
    "TaskId",
    "UTCDateTime",
    "WorkerId",
]

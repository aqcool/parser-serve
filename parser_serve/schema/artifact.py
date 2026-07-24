"""Files and intermediate outputs produced during parsing."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import AnyUrl, Field, model_validator

from .base import JsonValue, StrictSchema
from .common import (
    ApiResponse,
    ArtifactId,
    Cursor,
    ListResponse,
    MimeType,
    NonEmptyStr,
    Sha256,
    SortDirection,
    UTCDateTime,
)


class ArtifactType(StrEnum):
    ORIGINAL = "original"
    CONVERTED_DOCUMENT = "converted_document"
    EXTRACTED_IMAGE = "extracted_image"
    KEYFRAME = "keyframe"
    AUDIO_TRACK = "audio_track"
    SUBTITLE = "subtitle"
    RESULT_JSON = "result_json"
    RESULT_TEXT = "result_text"
    RESULT_MARKDOWN = "result_markdown"
    OTHER = "other"


class ArtifactSortField(StrEnum):
    CREATED_AT = "created_at"
    FILENAME = "filename"
    SIZE_BYTES = "size_bytes"


class ArtifactListQuery(StrictSchema):
    types: list[ArtifactType] = Field(default_factory=list)
    mime_type: MimeType | None = None
    limit: Annotated[int, Field(ge=1, le=200, strict=True)] = 50
    cursor: Cursor | None = None
    sort_by: ArtifactSortField = ArtifactSortField.CREATED_AT
    sort_direction: SortDirection = SortDirection.ASC


class Artifact(StrictSchema):
    artifact_id: ArtifactId
    type: ArtifactType
    filename: NonEmptyStr
    mime_type: MimeType
    size_bytes: Annotated[int, Field(ge=0, strict=True)]
    sha256: Sha256
    storage_uri: NonEmptyStr
    created_at: UTCDateTime
    expires_at: UTCDateTime | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_expiration(self) -> Artifact:
        if self.expires_at is not None and self.expires_at <= self.created_at:
            raise ValueError("expires_at must be later than created_at")
        return self


ArtifactListResponse = ListResponse[Artifact]
ArtifactResponse = ApiResponse[Artifact]


class ArtifactDownload(StrictSchema):
    url: AnyUrl
    method: Literal["GET"] = "GET"
    expires_at: UTCDateTime


ArtifactDownloadResponse = ApiResponse[ArtifactDownload]


__all__ = [
    "Artifact",
    "ArtifactDownload",
    "ArtifactDownloadResponse",
    "ArtifactListQuery",
    "ArtifactListResponse",
    "ArtifactResponse",
    "ArtifactSortField",
    "ArtifactType",
]

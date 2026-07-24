"""Uploaded file contracts."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from .base import StrictSchema
from .common import (
    ApiResponse,
    FileId,
    MediaCategory,
    MimeType,
    NonEmptyStr,
    Sha256,
    UTCDateTime,
)


class UploadedFileDetail(StrictSchema):
    file_id: FileId
    filename: Annotated[str, Field(min_length=1, max_length=512, strict=True)]
    mime_type: MimeType
    media_category: MediaCategory
    size_bytes: Annotated[int, Field(ge=0, strict=True)]
    sha256: Sha256
    created_at: UTCDateTime
    expires_at: UTCDateTime | None = None


UploadedFileResponse = ApiResponse[UploadedFileDetail]


class FileContentMetadata(StrictSchema):
    file_id: FileId
    filename: NonEmptyStr
    mime_type: MimeType
    size_bytes: Annotated[int, Field(ge=0, strict=True)]
    sha256: Sha256


__all__ = [
    "FileContentMetadata",
    "UploadedFileDetail",
    "UploadedFileResponse",
]

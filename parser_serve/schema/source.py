"""Input source and normalized source metadata contracts."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AnyUrl, Field, HttpUrl, UrlConstraints

from .base import JsonValue, StrictSchema
from .common import FileId, MediaCategory, MimeType, NonEmptyStr, Sha256


class UploadedFileSource(StrictSchema):
    type: Literal["uploaded_file"]
    file_id: FileId


class UrlSource(StrictSchema):
    type: Literal["url"]
    url: HttpUrl


class ObjectStorageSource(StrictSchema):
    type: Literal["object_storage"]
    uri: Annotated[AnyUrl, UrlConstraints(allowed_schemes=["s3"])]
    version_id: NonEmptyStr | None = None


class TextSource(StrictSchema):
    type: Literal["text"]
    text: Annotated[str, Field(min_length=1, max_length=10_000_000, strict=True)]
    mime_type: MimeType = "text/plain"
    filename: NonEmptyStr | None = None


ParseSource = Annotated[
    UploadedFileSource | UrlSource | ObjectStorageSource | TextSource,
    Field(discriminator="type"),
]


class SourceMetadata(StrictSchema):
    filename: NonEmptyStr | None = None
    mime_type: MimeType
    media_category: MediaCategory
    size_bytes: Annotated[int, Field(ge=0, strict=True)] | None = None
    sha256: Sha256 | None = None
    attributes: dict[str, JsonValue] = Field(default_factory=dict)


__all__ = [
    "ObjectStorageSource",
    "ParseSource",
    "SourceMetadata",
    "TextSource",
    "UploadedFileSource",
    "UrlSource",
]

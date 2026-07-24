"""Content signature inspection contracts."""

from __future__ import annotations

from enum import StrEnum

from .base import StrictSchema
from .common import MediaCategory, MimeType, NonEmptyStr, StrictBool


class ContentContainer(StrEnum):
    PLAIN = "plain"
    ZIP = "zip"
    OLE = "ole"
    RIFF = "riff"
    ISO_BMFF = "iso_bmff"
    MATROSKA = "matroska"


class ContentInspection(StrictSchema):
    detected_mime_type: MimeType
    media_category: MediaCategory
    container: ContentContainer = ContentContainer.PLAIN
    signature: NonEmptyStr
    textual: StrictBool = False


__all__ = ["ContentContainer", "ContentInspection"]

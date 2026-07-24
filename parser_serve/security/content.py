"""Extension, declared MIME, and content signature validation."""

from __future__ import annotations

from pathlib import PurePath

from ..schema.common import MediaCategory
from ..schema.content import ContentContainer, ContentInspection


class ContentValidationError(ValueError):
    """Input bytes contradict their filename or declared MIME type."""


_DOCUMENT_EXTENSIONS = {
    ".doc",
    ".docx",
    ".epub",
    ".pdf",
    ".ppt",
    ".pptx",
    ".xls",
    ".xlsx",
}
_IMAGE_EXTENSIONS = {
    ".avif",
    ".bmp",
    ".gif",
    ".heic",
    ".heif",
    ".jpeg",
    ".jpg",
    ".png",
    ".tif",
    ".tiff",
    ".webp",
}
_AUDIO_EXTENSIONS = {
    ".aac",
    ".flac",
    ".m4a",
    ".mp3",
    ".ogg",
    ".opus",
    ".wav",
}
_VIDEO_EXTENSIONS = {
    ".avi",
    ".m4v",
    ".mkv",
    ".mov",
    ".mp4",
    ".mpeg",
    ".mpg",
    ".webm",
}
_WEB_EXTENSIONS = {".htm", ".html", ".xhtml"}
_TEXT_EXTENSIONS = {
    ".csv",
    ".json",
    ".log",
    ".md",
    ".rst",
    ".text",
    ".tsv",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}

_CATEGORY_EXTENSIONS = {
    MediaCategory.DOCUMENT: _DOCUMENT_EXTENSIONS,
    MediaCategory.IMAGE: _IMAGE_EXTENSIONS,
    MediaCategory.AUDIO: _AUDIO_EXTENSIONS,
    MediaCategory.VIDEO: _VIDEO_EXTENSIONS,
    MediaCategory.WEB: _WEB_EXTENSIONS,
    MediaCategory.TEXT: _TEXT_EXTENSIONS,
}

_MIME_ALIASES: dict[str, set[str]] = {
    "application/pdf": {"application/pdf", "application/octet-stream"},
    "application/x-ole-storage": {
        "application/msword",
        "application/vnd.ms-excel",
        "application/vnd.ms-powerpoint",
        "application/octet-stream",
    },
    "application/zip": {
        "application/epub+zip",
        "application/zip",
        "application/octet-stream",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    },
    "image/jpeg": {"image/jpeg", "image/jpg", "application/octet-stream"},
    "image/png": {"image/png", "application/octet-stream"},
    "image/gif": {"image/gif", "application/octet-stream"},
    "image/tiff": {"image/tiff", "application/octet-stream"},
    "image/bmp": {"image/bmp", "application/octet-stream"},
    "image/webp": {"image/webp", "application/octet-stream"},
    "image/avif": {"image/avif", "application/octet-stream"},
    "image/heic": {"image/heic", "image/heif", "application/octet-stream"},
    "audio/wav": {"audio/wav", "audio/x-wav", "application/octet-stream"},
    "audio/flac": {"audio/flac", "audio/x-flac", "application/octet-stream"},
    "audio/aac": {"audio/aac", "audio/x-aac", "application/octet-stream"},
    "audio/mpeg": {"audio/mpeg", "audio/mp3", "application/octet-stream"},
    "audio/mp4": {"audio/mp4", "audio/x-m4a", "application/octet-stream"},
    "audio/ogg": {
        "audio/ogg",
        "audio/opus",
        "application/ogg",
        "application/octet-stream",
    },
    "video/x-msvideo": {"video/x-msvideo", "video/avi", "application/octet-stream"},
    "video/mp4": {
        "audio/mp4",
        "video/mp4",
        "video/quicktime",
        "application/octet-stream",
    },
    "video/x-matroska": {
        "audio/webm",
        "video/webm",
        "video/x-matroska",
        "application/octet-stream",
    },
    "video/mpeg": {"video/mpeg", "application/octet-stream"},
}

_EXTENSION_MIME: dict[str, str] = {
    ".doc": "application/msword",
    ".xls": "application/vnd.ms-excel",
    ".ppt": "application/vnd.ms-powerpoint",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".epub": "application/epub+zip",
}


def _binary_inspection(sample: bytes) -> ContentInspection | None:
    if sample.startswith(b"%PDF-"):
        return ContentInspection(
            detected_mime_type="application/pdf",
            media_category=MediaCategory.DOCUMENT,
            signature="pdf",
        )
    if sample.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return ContentInspection(
            detected_mime_type="application/x-ole-storage",
            media_category=MediaCategory.DOCUMENT,
            container=ContentContainer.OLE,
            signature="ole-compound-document",
        )
    if sample.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")):
        return ContentInspection(
            detected_mime_type="application/zip",
            media_category=MediaCategory.DOCUMENT,
            container=ContentContainer.ZIP,
            signature="zip-container",
        )
    if sample.startswith(b"\xff\xd8\xff"):
        return _image("image/jpeg", "jpeg")
    if sample.startswith(b"\x89PNG\r\n\x1a\n"):
        return _image("image/png", "png")
    if sample.startswith((b"GIF87a", b"GIF89a")):
        return _image("image/gif", "gif")
    if sample.startswith((b"II*\x00", b"MM\x00*")):
        return _image("image/tiff", "tiff")
    if sample.startswith(b"BM"):
        return _image("image/bmp", "bmp")
    if sample.startswith(b"RIFF") and len(sample) >= 12:
        form = sample[8:12]
        if form == b"WEBP":
            return _image("image/webp", "webp", ContentContainer.RIFF)
        if form == b"WAVE":
            return _audio("audio/wav", "wav", ContentContainer.RIFF)
        if form == b"AVI ":
            return _video("video/x-msvideo", "avi", ContentContainer.RIFF)
    if sample.startswith(b"fLaC"):
        return _audio("audio/flac", "flac")
    if sample.startswith(b"OggS"):
        return _audio("audio/ogg", "ogg")
    if len(sample) >= 2 and sample[0] == 0xFF and sample[1] & 0xF6 == 0xF0:
        return _audio("audio/aac", "aac-adts")
    if sample.startswith(b"ID3") or (
        len(sample) >= 2 and sample[0] == 0xFF and sample[1] & 0xE0 == 0xE0
    ):
        return _audio("audio/mpeg", "mpeg-audio")
    if sample.startswith(b"\x1aE\xdf\xa3"):
        return _video(
            "video/x-matroska",
            "matroska",
            ContentContainer.MATROSKA,
        )
    if len(sample) >= 12 and sample[4:8] == b"ftyp":
        brand = sample[8:12]
        if brand in {b"avif", b"avis"}:
            return _image("image/avif", "avif", ContentContainer.ISO_BMFF)
        if brand in {b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1"}:
            return _image("image/heic", "heif", ContentContainer.ISO_BMFF)
        return _video("video/mp4", "iso-bmff", ContentContainer.ISO_BMFF)
    if sample.startswith(b"\x00\x00\x01\xb3"):
        return _video("video/mpeg", "mpeg-video")
    return None


def _image(
    mime_type: str,
    signature: str,
    container: ContentContainer = ContentContainer.PLAIN,
) -> ContentInspection:
    return ContentInspection(
        detected_mime_type=mime_type,
        media_category=MediaCategory.IMAGE,
        container=container,
        signature=signature,
    )


def _audio(
    mime_type: str,
    signature: str,
    container: ContentContainer = ContentContainer.PLAIN,
) -> ContentInspection:
    return ContentInspection(
        detected_mime_type=mime_type,
        media_category=MediaCategory.AUDIO,
        container=container,
        signature=signature,
    )


def _video(
    mime_type: str,
    signature: str,
    container: ContentContainer = ContentContainer.PLAIN,
) -> ContentInspection:
    return ContentInspection(
        detected_mime_type=mime_type,
        media_category=MediaCategory.VIDEO,
        container=container,
        signature=signature,
    )


def _text_inspection(
    sample: bytes,
    *,
    declared_mime_type: str,
    suffix: str,
) -> ContentInspection | None:
    if b"\x00" in sample and not sample.startswith((b"\xff\xfe", b"\xfe\xff")):
        return None
    try:
        if sample.startswith((b"\xff\xfe", b"\xfe\xff")):
            text = sample.decode("utf-16")
        else:
            text = sample.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None
    normalized = text.lstrip().casefold()
    is_web = suffix in _WEB_EXTENSIONS or declared_mime_type in {
        "text/html",
        "application/xhtml+xml",
    }
    if is_web:
        if not any(
            marker in normalized[:8192]
            for marker in ("<!doctype html", "<html", "<head", "<body", "<?xml")
        ):
            raise ContentValidationError(
                "declared web content does not contain an HTML or XHTML signature"
            )
        return ContentInspection(
            detected_mime_type=(
                "application/xhtml+xml"
                if declared_mime_type == "application/xhtml+xml"
                else "text/html"
            ),
            media_category=MediaCategory.WEB,
            signature="html-text",
            textual=True,
        )
    return ContentInspection(
        detected_mime_type=(
            declared_mime_type
            if declared_mime_type.startswith("text/")
            or declared_mime_type
            in {"application/json", "application/xml", "application/yaml"}
            else "text/plain"
        ),
        media_category=MediaCategory.TEXT,
        signature="unicode-text",
        textual=True,
    )


def inspect_content(
    *,
    filename: str,
    declared_mime_type: str,
    sample: bytes,
) -> ContentInspection:
    if not sample:
        raise ContentValidationError("content is empty")
    suffix = PurePath(filename).suffix.casefold()
    normalized_mime = declared_mime_type.casefold().split(";", 1)[0].strip()
    binary = _binary_inspection(sample)
    inspection = binary or _text_inspection(
        sample,
        declared_mime_type=normalized_mime,
        suffix=suffix,
    )
    if inspection is None:
        raise ContentValidationError("content signature is not recognized")
    if inspection.detected_mime_type == "video/mp4" and suffix == ".m4a":
        inspection = inspection.model_copy(
            update={
                "detected_mime_type": "audio/mp4",
                "media_category": MediaCategory.AUDIO,
            }
        )

    expected_category = next(
        (
            category
            for category, extensions in _CATEGORY_EXTENSIONS.items()
            if suffix in extensions
        ),
        None,
    )
    if expected_category is None:
        raise ContentValidationError("filename extension is not supported")
    if inspection.media_category is not expected_category:
        raise ContentValidationError(
            "content signature does not match the filename extension"
        )

    if not inspection.textual:
        aliases = _MIME_ALIASES.get(inspection.detected_mime_type, set())
        if normalized_mime not in aliases:
            raise ContentValidationError(
                "content signature does not match the declared MIME type"
            )
    elif not (
        normalized_mime.startswith("text/")
        or normalized_mime
        in {
            "application/json",
            "application/octet-stream",
            "application/xhtml+xml",
            "application/xml",
            "application/yaml",
        }
    ):
        raise ContentValidationError(
            "text content does not match the declared MIME type"
        )

    effective_mime = _EXTENSION_MIME.get(suffix)
    if effective_mime is not None:
        inspection = inspection.model_copy(
            update={"detected_mime_type": effective_mime}
        )
    return inspection


__all__ = ["ContentValidationError", "inspect_content"]

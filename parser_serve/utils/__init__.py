"""Utility helpers used by parser-serve."""

from .libreoffice import (
    LibreOfficeConversionError,
    LibreOfficeNotFoundError,
    UnsupportedLegacyOfficeFormatError,
    convert_legacy_office,
    convert_with_libreoffice,
    libreoffice_available,
)
from .ffmpeg import (
    FFmpegError,
    FFmpegExecutionError,
    FFmpegNotFoundError,
    extract_audio_track,
    ffmpeg_available,
    probe_media,
)
from .process_limits import ProcessResourceLimitError, ProcessResourceLimits

__all__ = [
    "LibreOfficeConversionError",
    "LibreOfficeNotFoundError",
    "UnsupportedLegacyOfficeFormatError",
    "convert_legacy_office",
    "convert_with_libreoffice",
    "FFmpegError",
    "FFmpegExecutionError",
    "FFmpegNotFoundError",
    "extract_audio_track",
    "ffmpeg_available",
    "libreoffice_available",
    "probe_media",
    "ProcessResourceLimitError",
    "ProcessResourceLimits",
]

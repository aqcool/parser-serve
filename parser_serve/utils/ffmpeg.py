"""Safe ffmpeg and ffprobe subprocess helpers."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Final

from ..schema.base import JsonValue
from ..schema.media import MediaProbe, MediaStreamInfo, MediaStreamType
from .process_limits import ProcessResourceLimitError, ProcessResourceLimits


DEFAULT_PROBE_TIMEOUT_SECONDS: Final = 30.0
DEFAULT_TRANSCODE_TIMEOUT_SECONDS: Final = 600.0


class FFmpegError(RuntimeError):
    """Base error for ffmpeg and ffprobe execution."""


class FFmpegNotFoundError(FFmpegError):
    """The requested binary is not installed."""


class FFmpegExecutionError(FFmpegError):
    """The subprocess failed or returned invalid output."""


def ffmpeg_available() -> bool:
    return all(shutil.which(command) is not None for command in ("ffmpeg", "ffprobe"))


def _source_file(source: str | Path) -> Path:
    path = Path(source).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(path)
    if not path.is_file():
        raise IsADirectoryError(path)
    return path


def _executable(name: str, override: str | Path | None) -> str:
    if override is not None:
        return str(override)
    executable = shutil.which(name)
    if executable is None:
        raise FFmpegNotFoundError(f"{name} executable was not found on PATH")
    return executable


def _optional_float(value: object) -> float | None:
    if value is None or value == "" or value == "N/A":
        return None
    try:
        parsed = float(str(value))
    except ValueError as exc:
        raise FFmpegExecutionError(f"invalid numeric ffprobe value: {value!r}") from exc
    return parsed if parsed >= 0 else None


def _optional_int(value: object) -> int | None:
    number = _optional_float(value)
    return int(number) if number is not None else None


def _frame_rate(value: object) -> float | None:
    if value is None or value == "" or value == "N/A" or value == "0/0":
        return None
    text = str(value)
    try:
        if "/" not in text:
            return _optional_float(text)
        numerator, denominator = text.split("/", 1)
        if float(denominator) == 0:
            return None
        return max(float(numerator) / float(denominator), 0.0)
    except ValueError as exc:
        raise FFmpegExecutionError(f"invalid ffprobe frame rate: {value!r}") from exc


def _json_mapping(value: object) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        return {}
    return {
        str(key): item
        for key, item in value.items()
        if item is None or isinstance(item, (str, int, float, bool, list, dict))
    }


def _stream_type(value: object) -> MediaStreamType:
    try:
        return MediaStreamType(str(value))
    except ValueError:
        return MediaStreamType.UNKNOWN


def _parse_probe(payload: dict[str, Any]) -> MediaProbe:
    format_payload = payload.get("format")
    if not isinstance(format_payload, dict):
        format_payload = {}
    streams_payload = payload.get("streams")
    if not isinstance(streams_payload, list):
        streams_payload = []
    streams: list[MediaStreamInfo] = []
    for raw in streams_payload:
        if not isinstance(raw, dict):
            continue
        tags = _json_mapping(raw.get("tags"))
        language = tags.get("language")
        streams.append(
            MediaStreamInfo(
                index=int(raw.get("index", len(streams))),
                type=_stream_type(raw.get("codec_type")),
                codec_name=raw.get("codec_name") or None,
                codec_long_name=raw.get("codec_long_name") or None,
                duration_seconds=_optional_float(raw.get("duration")),
                bit_rate=_optional_int(raw.get("bit_rate")),
                width=_optional_int(raw.get("width")),
                height=_optional_int(raw.get("height")),
                frame_rate=_frame_rate(raw.get("avg_frame_rate")),
                sample_rate=_optional_int(raw.get("sample_rate")),
                channels=_optional_int(raw.get("channels")),
                language=language if isinstance(language, str) and language else None,
                tags=tags,
            )
        )
    return MediaProbe(
        format_name=format_payload.get("format_name") or None,
        format_long_name=format_payload.get("format_long_name") or None,
        duration_seconds=_optional_float(format_payload.get("duration")),
        size_bytes=_optional_int(format_payload.get("size")),
        bit_rate=_optional_int(format_payload.get("bit_rate")),
        streams=streams,
        tags=_json_mapping(format_payload.get("tags")),
    )


def probe_media(
    source: str | Path,
    *,
    timeout: float = DEFAULT_PROBE_TIMEOUT_SECONDS,
    executable: str | Path | None = None,
    resource_limits: ProcessResourceLimits | None = None,
) -> MediaProbe:
    source_path = _source_file(source)
    if timeout <= 0:
        raise ValueError("timeout must be greater than zero")
    command = [
        _executable("ffprobe", executable),
        "-v",
        "error",
        "-show_format",
        "-show_streams",
        "-of",
        "json",
        str(source_path),
    ]
    if resource_limits is not None:
        try:
            command = resource_limits.command(command)
        except ProcessResourceLimitError as exc:
            raise FFmpegExecutionError(str(exc)) from exc
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise FFmpegNotFoundError(
            f"ffprobe executable was not found: {command[0]}"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise FFmpegExecutionError(
            f"ffprobe timed out after {timeout} seconds"
        ) from exc
    if result.returncode != 0:
        details = result.stderr.strip() or "no error output"
        raise FFmpegExecutionError(
            f"ffprobe failed with exit code {result.returncode}: {details}"
        )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise FFmpegExecutionError("ffprobe returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise FFmpegExecutionError("ffprobe JSON root must be an object")
    try:
        return _parse_probe(payload)
    except FFmpegExecutionError:
        raise
    except (TypeError, ValueError) as exc:
        raise FFmpegExecutionError(
            "ffprobe returned values that violate the media metadata schema"
        ) from exc


def extract_audio_track(
    source: str | Path,
    output: str | Path,
    *,
    sample_rate: int = 16_000,
    channels: int = 1,
    timeout: float = DEFAULT_TRANSCODE_TIMEOUT_SECONDS,
    executable: str | Path | None = None,
    resource_limits: ProcessResourceLimits | None = None,
) -> Path:
    source_path = _source_file(source)
    if sample_rate < 1 or channels < 1:
        raise ValueError("sample_rate and channels must be greater than zero")
    if timeout <= 0:
        raise ValueError("timeout must be greater than zero")
    output_path = Path(output).expanduser().resolve()
    if output_path == source_path:
        raise ValueError("output path cannot overwrite the source")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        _executable("ffmpeg", executable),
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(source_path),
        "-vn",
        "-ac",
        str(channels),
        "-ar",
        str(sample_rate),
        "-c:a",
        "pcm_s16le",
        str(output_path),
    ]
    if resource_limits is not None:
        try:
            command = resource_limits.command(command)
        except ProcessResourceLimitError as exc:
            raise FFmpegExecutionError(str(exc)) from exc
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise FFmpegNotFoundError(
            f"ffmpeg executable was not found: {command[0]}"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise FFmpegExecutionError(f"ffmpeg timed out after {timeout} seconds") from exc
    if result.returncode != 0:
        details = result.stderr.strip() or "no error output"
        raise FFmpegExecutionError(
            f"ffmpeg failed with exit code {result.returncode}: {details}"
        )
    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise FFmpegExecutionError("ffmpeg reported success without an output file")
    return output_path


__all__ = [
    "FFmpegError",
    "FFmpegExecutionError",
    "FFmpegNotFoundError",
    "extract_audio_track",
    "ffmpeg_available",
    "probe_media",
]

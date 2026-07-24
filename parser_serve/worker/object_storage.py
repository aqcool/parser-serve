"""Bounded S3/MinIO Object Storage source download."""

from __future__ import annotations

import asyncio
import mimetypes
from collections.abc import Mapping
from importlib import import_module
from pathlib import Path, PurePosixPath
from typing import Protocol, cast
from urllib.parse import unquote, urlsplit

from pydantic import AnyUrl

from ..backends import BackendExecutionError
from ..security import ContentValidationError, inspect_content


class StreamingBody(Protocol):
    def read(self, amount: int = -1) -> bytes: ...

    def close(self) -> None: ...


class S3Client(Protocol):
    def get_object(self, **kwargs: str) -> Mapping[str, object]: ...


def _client(*, endpoint_url: str | None, region_name: str | None) -> S3Client:
    try:
        boto3 = import_module("boto3")
    except ImportError as exc:
        raise BackendExecutionError(
            "boto3 is not installed; enable the object-storage dependency Profile"
        ) from exc
    return cast(
        S3Client,
        boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            region_name=region_name,
        ),
    )


def _location(uri: AnyUrl) -> tuple[str, str]:
    parsed = urlsplit(str(uri))
    if parsed.scheme != "s3" or not parsed.hostname:
        raise BackendExecutionError("Object Storage Source must use s3://bucket/key")
    key = unquote(parsed.path).lstrip("/")
    normalized = PurePosixPath(key)
    if (
        not key
        or "\\" in key
        or any(part in {"", ".", ".."} for part in normalized.parts)
    ):
        raise BackendExecutionError("Object Storage key is unsafe")
    return parsed.hostname, key


async def download_object_storage_source(
    uri: AnyUrl,
    destination: Path,
    *,
    allowed_buckets: set[str],
    maximum_bytes: int,
    declared_mime_type: str | None = None,
    version_id: str | None = None,
    endpoint_url: str | None = None,
    region_name: str | None = None,
    client: S3Client | None = None,
) -> Path:
    if maximum_bytes < 1:
        raise ValueError("maximum_bytes must be greater than zero")
    bucket, key = _location(uri)
    if bucket not in allowed_buckets:
        raise BackendExecutionError(
            "Object Storage bucket is not in the Worker allowlist"
        )
    resolved_client = client or _client(
        endpoint_url=endpoint_url,
        region_name=region_name,
    )
    arguments = {"Bucket": bucket, "Key": key}
    if version_id is not None:
        arguments["VersionId"] = version_id
    try:
        response = await asyncio.to_thread(
            resolved_client.get_object,
            **arguments,
        )
        length = response.get("ContentLength")
        if not isinstance(length, int) or isinstance(length, bool) or length < 0:
            raise BackendExecutionError(
                "Object Storage response has invalid ContentLength"
            )
        if length > maximum_bytes:
            raise BackendExecutionError(
                "Object Storage Source exceeds the download size limit"
            )
        body = response.get("Body")
        if body is None or not hasattr(body, "read") or not hasattr(body, "close"):
            raise BackendExecutionError("Object Storage response body is invalid")
        stream = cast(StreamingBody, body)
        destination.parent.mkdir(parents=True, exist_ok=True)
        handle = await asyncio.to_thread(destination.open, "wb")
        size = 0
        try:
            while chunk := await asyncio.to_thread(stream.read, 1024 * 1024):
                if not isinstance(chunk, bytes):
                    raise BackendExecutionError(
                        "Object Storage response yielded invalid bytes"
                    )
                size += len(chunk)
                if size > maximum_bytes:
                    raise BackendExecutionError(
                        "Object Storage Source exceeds the download size limit"
                    )
                await asyncio.to_thread(handle.write, chunk)
        except BaseException:
            await asyncio.to_thread(handle.close)
            await asyncio.to_thread(destination.unlink, missing_ok=True)
            raise
        finally:
            await asyncio.to_thread(stream.close)
        await asyncio.to_thread(handle.close)
        if size != length:
            await asyncio.to_thread(destination.unlink, missing_ok=True)
            raise BackendExecutionError(
                "Object Storage response length does not match ContentLength"
            )
        try:
            sample = await asyncio.to_thread(_read_sample, destination)
            inspect_content(
                filename=destination.name,
                declared_mime_type=(
                    declared_mime_type
                    or mimetypes.guess_type(destination.name)[0]
                    or "application/octet-stream"
                ),
                sample=sample,
            )
        except ContentValidationError as exc:
            await asyncio.to_thread(destination.unlink, missing_ok=True)
            raise BackendExecutionError(str(exc)) from exc
        return destination
    except BackendExecutionError:
        raise
    except Exception as exc:
        raise BackendExecutionError(
            "Object Storage Source download failed",
            retryable=True,
        ) from exc


def _read_sample(path: Path) -> bytes:
    with path.open("rb") as source:
        return source.read(64 * 1024)


__all__ = ["S3Client", "StreamingBody", "download_object_storage_source"]

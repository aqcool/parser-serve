"""S3-compatible shared object storage for multi-node deployments."""

from __future__ import annotations

import asyncio
import hashlib
import importlib
import os
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote

from .base import (
    AsyncByteStream,
    StorageObject,
    StorageObjectNotFoundError,
    StorageObjectTooLargeError,
)


def _safe_key(key: str) -> str:
    normalized = PurePosixPath(key)
    if (
        not key
        or normalized.is_absolute()
        or "\\" in key
        or any(part in {"", ".", ".."} for part in normalized.parts)
    ):
        raise ValueError("storage key must be a safe relative POSIX path")
    return normalized.as_posix()


def _error_code(exc: Exception) -> str | None:
    response = getattr(exc, "response", None)
    if not isinstance(response, dict):
        return None
    error = response.get("Error")
    if isinstance(error, dict):
        code = error.get("Code")
        if isinstance(code, str):
            return code
    metadata = response.get("ResponseMetadata")
    if isinstance(metadata, dict):
        status = metadata.get("HTTPStatusCode")
        if isinstance(status, int):
            return str(status)
    return None


class S3Storage:
    def __init__(
        self,
        *,
        bucket: str,
        prefix: str = "",
        endpoint_url: str | None = None,
        region_name: str | None = None,
        client: Any | None = None,
    ) -> None:
        if not bucket or "/" in bucket or "\\" in bucket:
            raise ValueError("S3 bucket is invalid")
        normalized_prefix = prefix.strip("/")
        if normalized_prefix:
            _safe_key(normalized_prefix)
        self.bucket = bucket
        self.prefix = normalized_prefix
        if client is None:
            try:
                boto3 = importlib.import_module("boto3")
            except ImportError as exc:  # pragma: no cover - profile boundary
                raise RuntimeError(
                    "S3 storage requires the object-storage dependency profile"
                ) from exc
            client = boto3.client(
                "s3",
                endpoint_url=endpoint_url,
                region_name=region_name,
            )
        if client is None:  # pragma: no cover - defensive type narrowing
            raise RuntimeError("S3 client initialization failed")
        self._client = client

    def _object_key(self, key: str) -> str:
        safe = _safe_key(key)
        return f"{self.prefix}/{safe}" if self.prefix else safe

    async def write(
        self,
        key: str,
        source: AsyncByteStream,
        *,
        maximum_bytes: int,
    ) -> StorageObject:
        if maximum_bytes < 1:
            raise ValueError("maximum_bytes must be greater than zero")
        object_key = self._object_key(key)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".parser-serve-s3-",
            suffix=".upload",
        )
        handle = os.fdopen(descriptor, "wb")
        size_bytes = 0
        digest = hashlib.sha256()
        try:
            async for chunk in source:
                if not isinstance(chunk, bytes):
                    raise TypeError("storage streams must yield bytes")
                if not chunk:
                    continue
                size_bytes += len(chunk)
                if size_bytes > maximum_bytes:
                    raise StorageObjectTooLargeError
                digest.update(chunk)
                await asyncio.to_thread(handle.write, chunk)
            await asyncio.to_thread(handle.flush)
            await asyncio.to_thread(os.fsync, handle.fileno())
            await asyncio.to_thread(handle.close)
            await asyncio.to_thread(
                self._client.upload_file,
                temporary_name,
                self.bucket,
                object_key,
                ExtraArgs={
                    "Metadata": {
                        "parser-serve-sha256": digest.hexdigest(),
                    }
                },
            )
        except BaseException:
            if not handle.closed:
                await asyncio.to_thread(handle.close)
            raise
        finally:
            await asyncio.to_thread(Path(temporary_name).unlink, missing_ok=True)
        return StorageObject(
            key=key,
            uri=f"s3://{self.bucket}/{quote(object_key, safe='/')}",
            size_bytes=size_bytes,
            sha256=digest.hexdigest(),
        )

    async def read(
        self,
        key: str,
        *,
        chunk_size: int = 1024 * 1024,
    ) -> AsyncIterator[bytes]:
        if chunk_size < 1:
            raise ValueError("chunk_size must be greater than zero")
        try:
            response = await asyncio.to_thread(
                self._client.get_object,
                Bucket=self.bucket,
                Key=self._object_key(key),
            )
        except Exception as exc:
            if _error_code(exc) in {"404", "NoSuchKey", "NotFound"}:
                raise StorageObjectNotFoundError from exc
            raise
        body = response["Body"]
        try:
            while chunk := await asyncio.to_thread(body.read, chunk_size):
                if not isinstance(chunk, bytes):
                    raise TypeError("S3 response body must yield bytes")
                yield chunk
        finally:
            await asyncio.to_thread(body.close)

    async def exists(self, key: str) -> bool:
        try:
            await asyncio.to_thread(
                self._client.head_object,
                Bucket=self.bucket,
                Key=self._object_key(key),
            )
        except Exception as exc:
            if _error_code(exc) in {"404", "NoSuchKey", "NotFound"}:
                return False
            raise
        return True

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(
            self._client.delete_object,
            Bucket=self.bucket,
            Key=self._object_key(key),
        )

    async def presign_get(self, key: str, *, expires_seconds: int) -> str | None:
        if not 1 <= expires_seconds <= 86_400:
            raise ValueError("expires_seconds must be between 1 and 86400")
        url = await asyncio.to_thread(
            self._client.generate_presigned_url,
            "get_object",
            Params={
                "Bucket": self.bucket,
                "Key": self._object_key(key),
            },
            ExpiresIn=expires_seconds,
            HttpMethod="GET",
        )
        if not isinstance(url, str) or not url:
            raise RuntimeError("S3 client returned an invalid presigned URL")
        return url


__all__ = ["S3Storage"]

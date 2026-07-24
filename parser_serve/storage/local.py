"""Traversal-safe local filesystem storage."""

from __future__ import annotations

import asyncio
import hashlib
import os
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path, PurePosixPath
from urllib.parse import quote

from .base import (
    AsyncByteStream,
    StorageObject,
    StorageObjectNotFoundError,
    StorageObjectTooLargeError,
)


class LocalFileStorage:
    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()

    def _path(self, key: str) -> Path:
        normalized = PurePosixPath(key)
        if (
            not key
            or normalized.is_absolute()
            or "\\" in key
            or any(part in {"", ".", ".."} for part in normalized.parts)
        ):
            raise ValueError("storage key must be a safe relative POSIX path")
        path = (self.root / Path(*normalized.parts)).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("storage key escapes the storage root")
        return path

    async def write(
        self,
        key: str,
        source: AsyncByteStream,
        *,
        maximum_bytes: int,
    ) -> StorageObject:
        if maximum_bytes < 1:
            raise ValueError("maximum_bytes must be greater than zero")
        destination = self._path(key)
        await asyncio.to_thread(destination.parent.mkdir, parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}.",
            suffix=".upload",
            dir=destination.parent,
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
            await asyncio.to_thread(os.replace, temporary_name, destination)
        except BaseException:
            if not handle.closed:
                await asyncio.to_thread(handle.close)
            await asyncio.to_thread(Path(temporary_name).unlink, missing_ok=True)
            raise
        return StorageObject(
            key=key,
            uri=f"local:///{quote(key, safe='/')}",
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
        path = self._path(key)
        try:
            handle = await asyncio.to_thread(path.open, "rb")
        except FileNotFoundError as exc:
            raise StorageObjectNotFoundError from exc
        try:
            while chunk := await asyncio.to_thread(handle.read, chunk_size):
                yield chunk
        finally:
            await asyncio.to_thread(handle.close)

    async def exists(self, key: str) -> bool:
        return await asyncio.to_thread(self._path(key).is_file)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._path(key).unlink, missing_ok=True)

    async def presign_get(self, key: str, *, expires_seconds: int) -> str | None:
        if expires_seconds < 1:
            raise ValueError("expires_seconds must be greater than zero")
        self._path(key)
        return None


__all__ = ["LocalFileStorage"]

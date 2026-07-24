"""Backend-neutral object storage contract."""

from __future__ import annotations

from collections.abc import AsyncIterable, AsyncIterator
from dataclasses import dataclass
from typing import Protocol, TypeAlias


AsyncByteStream: TypeAlias = AsyncIterable[bytes]


@dataclass(frozen=True, slots=True)
class StorageObject:
    key: str
    uri: str
    size_bytes: int
    sha256: str


class StorageObjectTooLargeError(Exception):
    """The streamed object exceeded the configured limit."""


class StorageObjectNotFoundError(Exception):
    """The requested object does not exist."""


class Storage(Protocol):
    async def write(
        self,
        key: str,
        source: AsyncByteStream,
        *,
        maximum_bytes: int,
    ) -> StorageObject:
        """Atomically write an object while hashing and enforcing its size."""
        ...

    def read(self, key: str, *, chunk_size: int = 1024 * 1024) -> AsyncIterator[bytes]:
        """Stream an object's bytes."""
        ...

    async def exists(self, key: str) -> bool:
        """Return whether an object exists."""
        ...

    async def delete(self, key: str) -> None:
        """Delete an object if present."""
        ...

    async def presign_get(self, key: str, *, expires_seconds: int) -> str | None:
        """Return a short-lived direct download URL when supported."""
        ...


__all__ = [
    "AsyncByteStream",
    "Storage",
    "StorageObject",
    "StorageObjectNotFoundError",
    "StorageObjectTooLargeError",
]

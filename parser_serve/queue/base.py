"""Task availability notification abstraction.

The database remains authoritative for Stage state and leases. Implementations
only reduce empty Worker polling latency and must be safe to lose or duplicate.
"""

from __future__ import annotations

from typing import Protocol

from ..schema.queue import StageQueueNotice


class TaskQueueUnavailableError(RuntimeError):
    """The optional availability notification backend is unavailable."""


class TaskQueue(Protocol):
    async def snapshot(self) -> str:
        """Return an opaque cursor representing currently visible notices."""
        ...

    async def publish(self, notice: StageQueueNotice) -> None:
        """Publish a best-effort Stage availability notice."""

    async def wait(self, *, after: str, timeout_seconds: float) -> bool:
        """Wait for a notice newer than ``after`` and report whether one arrived."""
        ...

    async def check(self) -> None:
        """Raise when the notification backend is unavailable."""

    async def aclose(self) -> None:
        """Release owned resources."""


__all__ = ["TaskQueue", "TaskQueueUnavailableError"]

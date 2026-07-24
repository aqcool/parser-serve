"""Database-polling notification fallback."""

from __future__ import annotations

import asyncio

from ..schema.queue import StageQueueNotice


class DatabasePollingTaskQueue:
    """A no-dependency fallback that preserves periodic database polling."""

    async def snapshot(self) -> str:
        return "database"

    async def publish(self, notice: StageQueueNotice) -> None:
        del notice

    async def wait(self, *, after: str, timeout_seconds: float) -> bool:
        del after
        await asyncio.sleep(timeout_seconds)
        return False

    async def check(self) -> None:
        return None

    async def aclose(self) -> None:
        return None


__all__ = ["DatabasePollingTaskQueue"]

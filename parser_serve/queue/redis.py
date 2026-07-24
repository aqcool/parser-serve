"""Redis Streams availability notification adapter."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any, Protocol, cast

from redis.asyncio import Redis
from redis.exceptions import RedisError

from ..schema.queue import StageQueueNotice
from .base import TaskQueueUnavailableError


class RedisStreamClient(Protocol):
    async def xrevrange(
        self,
        name: str,
        *,
        max: str = "+",
        min: str = "-",
        count: int | None = None,
    ) -> list[tuple[Any, Mapping[Any, Any]]]: ...

    async def xadd(
        self,
        name: str,
        fields: Mapping[str, str],
        *,
        maxlen: int | None = None,
        approximate: bool = True,
    ) -> Any: ...

    async def xread(
        self,
        streams: Mapping[str, str],
        *,
        count: int | None = None,
        block: int | None = None,
    ) -> list[tuple[Any, list[tuple[Any, Mapping[Any, Any]]]]]: ...

    async def ping(self) -> Any: ...

    async def aclose(self) -> None: ...


def _text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)


class RedisStreamsTaskQueue:
    def __init__(
        self,
        *,
        url: str | None = None,
        stream_key: str = "parser-serve:stage-availability",
        maximum_length: int = 10_000,
        client: RedisStreamClient | None = None,
    ) -> None:
        if not stream_key or len(stream_key) > 512:
            raise ValueError("Redis stream_key must contain 1 to 512 characters")
        if maximum_length < 100:
            raise ValueError("Redis stream maximum_length must be at least 100")
        if client is None and url is None:
            raise ValueError("Redis url is required when no client is supplied")
        self.stream_key = stream_key
        self.maximum_length = maximum_length
        self._owns_client = client is None
        self.client = client or cast(
            RedisStreamClient,
            Redis.from_url(cast(str, url), decode_responses=True),
        )

    async def snapshot(self) -> str:
        try:
            records = await self.client.xrevrange(
                self.stream_key,
                count=1,
            )
        except (RedisError, OSError, asyncio.TimeoutError) as exc:
            raise TaskQueueUnavailableError("Redis Streams snapshot failed") from exc
        return _text(records[0][0]) if records else "0-0"

    async def publish(self, notice: StageQueueNotice) -> None:
        try:
            await self.client.xadd(
                self.stream_key,
                {"notice": notice.model_dump_json()},
                maxlen=self.maximum_length,
                approximate=True,
            )
        except (RedisError, OSError, asyncio.TimeoutError) as exc:
            raise TaskQueueUnavailableError("Redis Streams publish failed") from exc

    async def wait(self, *, after: str, timeout_seconds: float) -> bool:
        if timeout_seconds <= 0:
            return False
        try:
            records = await self.client.xread(
                {self.stream_key: after},
                count=1,
                block=max(int(timeout_seconds * 1000), 1),
            )
        except (RedisError, OSError, asyncio.TimeoutError) as exc:
            raise TaskQueueUnavailableError("Redis Streams wait failed") from exc
        return bool(records)

    async def check(self) -> None:
        try:
            await self.client.ping()
        except (RedisError, OSError, asyncio.TimeoutError) as exc:
            raise TaskQueueUnavailableError(
                "Redis Streams health check failed"
            ) from exc

    async def aclose(self) -> None:
        if self._owns_client:
            await self.client.aclose()


__all__ = ["RedisStreamClient", "RedisStreamsTaskQueue"]

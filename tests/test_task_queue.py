from __future__ import annotations

import unittest
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from fastapi.testclient import TestClient
from pydantic import ValidationError
from redis.exceptions import ConnectionError as RedisConnectionError

from parser_serve.api import create_app
from parser_serve.queue import (
    RedisStreamsTaskQueue,
    TaskQueueNotifier,
    TaskQueueUnavailableError,
)
from parser_serve.schema.queue import QueueNoticeReason, StageQueueNotice
from parser_serve.settings import Environment, Settings


NOW = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)


class FakeRedisStreamClient:
    def __init__(self) -> None:
        self.records: list[tuple[Any, Mapping[Any, Any]]] = []
        self.closed = False
        self.healthy = True

    async def xrevrange(
        self,
        name: str,
        *,
        max: str = "+",
        min: str = "-",
        count: int | None = None,
    ) -> list[tuple[Any, Mapping[Any, Any]]]:
        del name, max, min
        if not self.healthy:
            raise RedisConnectionError("private redis address")
        selected = list(reversed(self.records))
        return selected[:count] if count is not None else selected

    async def xadd(
        self,
        name: str,
        fields: Mapping[str, str],
        *,
        maxlen: int | None = None,
        approximate: bool = True,
    ) -> str:
        del name, maxlen, approximate
        if not self.healthy:
            raise RedisConnectionError("private redis address")
        record_id = f"{len(self.records) + 1}-0"
        self.records.append((record_id, dict(fields)))
        return record_id

    async def xread(
        self,
        streams: Mapping[str, str],
        *,
        count: int | None = None,
        block: int | None = None,
    ) -> list[tuple[Any, list[tuple[Any, Mapping[Any, Any]]]]]:
        del count, block
        if not self.healthy:
            raise RedisConnectionError("private redis address")
        stream, after = next(iter(streams.items()))
        newer = [record for record in self.records if record[0] > after]
        return [(stream, newer[:1])] if newer else []

    async def ping(self) -> bool:
        if not self.healthy:
            raise RedisConnectionError("private redis address")
        return True

    async def aclose(self) -> None:
        self.closed = True


class TaskQueueTests(unittest.IsolatedAsyncioTestCase):
    def notice(self) -> StageQueueNotice:
        return StageQueueNotice(
            notice_id="notice_queue1234",
            reason=QueueNoticeReason.TASK_ROUTED,
            task_id="task_queue1234",
            occurred_at=NOW,
        )

    async def test_redis_stream_cursor_publish_wait_and_health(self) -> None:
        client = FakeRedisStreamClient()
        queue = RedisStreamsTaskQueue(
            client=client,
            stream_key="test:stages",
            maximum_length=100,
        )

        cursor = await queue.snapshot()
        self.assertEqual(cursor, "0-0")
        await queue.publish(self.notice())
        self.assertTrue(await queue.wait(after=cursor, timeout_seconds=0.1))
        self.assertEqual(await queue.snapshot(), "1-0")
        self.assertIn('"reason":"task_routed"', client.records[0][1]["notice"])
        await queue.check()
        await queue.aclose()
        self.assertFalse(client.closed, "injected clients are not owned by the queue")

    async def test_redis_errors_are_wrapped_without_endpoint_details(self) -> None:
        client = FakeRedisStreamClient()
        client.healthy = False
        queue = RedisStreamsTaskQueue(client=client, maximum_length=100)

        with self.assertRaises(TaskQueueUnavailableError) as raised:
            await queue.snapshot()
        self.assertNotIn("private redis address", str(raised.exception))

        notifier = TaskQueueNotifier(queue)
        self.assertFalse(
            await notifier.publish(
                reason=QueueNoticeReason.TASK_ROUTED,
                task_id="task_queue1234",
                occurred_at=NOW,
            )
        )

    async def test_queue_notice_requires_reason_target(self) -> None:
        with self.assertRaises(ValidationError):
            StageQueueNotice(
                notice_id="notice_queue1234",
                reason=QueueNoticeReason.TASK_ROUTED,
                occurred_at=NOW,
            )


class QueueReadinessTests(unittest.TestCase):
    def test_readiness_reports_queue_failure_without_secret_details(self) -> None:
        client = FakeRedisStreamClient()
        client.healthy = False
        queue = RedisStreamsTaskQueue(client=client, maximum_length=100)
        app = create_app(
            Settings(environment=Environment.TEST),
            task_queue=queue,
            clock=lambda: NOW,
        )

        response = TestClient(app).get("/ready")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["data"]["healthy"])
        component = next(
            item
            for item in response.json()["data"]["components"]
            if item["name"] == "task_queue"
        )
        self.assertEqual(
            component["message"],
            "Task queue check failed: TaskQueueUnavailableError",
        )
        self.assertNotIn("private redis address", response.text)


if __name__ == "__main__":
    unittest.main()

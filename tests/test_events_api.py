from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from fastapi.testclient import TestClient
from pydantic import SecretStr
from starlette.requests import Request

from parser_serve.api import create_app
from parser_serve.api.routes.events import _stream, format_sse
from parser_serve.persistence import Database
from parser_serve.schema.event import (
    EventEnvelope,
    EventListResponse,
    EventStreamQuery,
    TaskCreatedEvent,
)
from parser_serve.schema.task import CreateTaskResponse
from parser_serve.settings import Environment, Settings


NOW = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)
API_KEY = f"parser_{'v' * 32}"
AUTH_HEADERS = {"Authorization": f"Bearer {API_KEY}"}


class EventApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        database_path = Path(self.temporary_directory.name) / "events.sqlite3"
        self.database = Database(f"sqlite+aiosqlite:///{database_path}")
        asyncio.run(self.database.create_schema_for_testing())
        self.app = create_app(
            Settings(
                environment=Environment.TEST,
                api_keys=[SecretStr(API_KEY)],
            ),
            clock=lambda: NOW,
            database=self.database,
        )
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        self.client.close()
        asyncio.run(self.database.dispose())
        self.temporary_directory.cleanup()

    def create_task(self, text: str) -> CreateTaskResponse:
        response = self.client.post(
            "/api/v1/tasks",
            headers=AUTH_HEADERS,
            json={"source": {"type": "text", "text": text}},
        )
        self.assertEqual(response.status_code, 201)
        return CreateTaskResponse.model_validate_json(response.content)

    def test_lists_filters_and_resumes_events(self) -> None:
        first_task = self.create_task("first")
        second_task = self.create_task("second")

        response = self.client.get(
            "/api/v1/events",
            headers=AUTH_HEADERS,
            params={"types": "task.created", "limit": 1},
        )
        page_one = EventListResponse.model_validate_json(response.content)
        self.assertEqual(len(page_one.items), 1)
        self.assertTrue(page_one.page.has_more)
        self.assertIsNotNone(page_one.page.next_cursor)

        response = self.client.get(
            "/api/v1/events",
            headers=AUTH_HEADERS,
            params={
                "types": "task.created",
                "last_event_id": page_one.page.next_cursor,
                "limit": 1,
            },
        )
        page_two = EventListResponse.model_validate_json(response.content)
        self.assertEqual(len(page_two.items), 1)
        first_payload = page_one.items[0].payload
        second_payload = page_two.items[0].payload
        self.assertIsInstance(first_payload, TaskCreatedEvent)
        self.assertIsInstance(second_payload, TaskCreatedEvent)
        task_ids = set()
        if isinstance(first_payload, TaskCreatedEvent):
            task_ids.add(first_payload.task_id)
        if isinstance(second_payload, TaskCreatedEvent):
            task_ids.add(second_payload.task_id)
        self.assertEqual(
            task_ids,
            {first_task.data.task_id, second_task.data.task_id},
        )

        response = self.client.get(
            "/api/v1/events",
            headers=AUTH_HEADERS,
            params={
                "types": "task.created",
                "sort_by": "occurred_at",
                "sort_direction": "desc",
            },
        )
        descending = EventListResponse.model_validate_json(response.content)
        self.assertEqual(
            [item.event_id for item in descending.items],
            list(
                reversed(
                    [
                        page_one.items[0].event_id,
                        page_two.items[0].event_id,
                    ]
                )
            ),
        )

        response = self.client.get(
            f"/api/v1/tasks/{first_task.data.task_id}/events",
            headers=AUTH_HEADERS,
        )
        task_events = EventListResponse.model_validate_json(response.content)
        self.assertEqual(len(task_events.items), 1)
        payload = task_events.items[0].payload
        self.assertIsInstance(payload, TaskCreatedEvent)
        if isinstance(payload, TaskCreatedEvent):
            self.assertEqual(payload.task_id, first_task.data.task_id)

    def test_event_stream_requires_auth_and_valid_resume_cursor(self) -> None:
        response = self.client.get(
            "/api/v1/events/stream",
            params={"last_event_id": "event_missing12"},
        )
        self.assertEqual(response.status_code, 401)

        response = self.client.get(
            "/api/v1/events/stream",
            headers=AUTH_HEADERS,
            params={"last_event_id": "event_missing12"},
        )
        self.assertEqual(response.status_code, 404)

        task = self.create_task("cursor")
        response = self.client.get(
            f"/api/v1/tasks/{task.data.task_id}/events",
            headers=AUTH_HEADERS,
        )
        event_id = response.json()["items"][0]["event_id"]
        response = self.client.get(
            "/api/v1/events/stream",
            headers={**AUTH_HEADERS, "Last-Event-ID": event_id},
            params={"last_event_id": "event_different12"},
        )
        self.assertEqual(response.status_code, 422)

    def test_sse_frame_contains_id_type_and_typed_json(self) -> None:
        task = self.create_task("frame")
        response = self.client.get(
            f"/api/v1/tasks/{task.data.task_id}/events",
            headers=AUTH_HEADERS,
        )
        envelope = EventListResponse.model_validate_json(response.content).items[0]

        frame = format_sse(envelope)

        lines = frame.strip().splitlines()
        self.assertEqual(lines[0], f"id: {envelope.event_id}")
        self.assertEqual(lines[1], "event: task.created")
        parsed = EventEnvelope.model_validate(
            json.loads(lines[2].removeprefix("data: "))
        )
        self.assertEqual(parsed, envelope)

    def test_slow_sse_consumer_is_closed_and_can_resume(self) -> None:
        task = self.create_task("slow consumer")
        current = [NOW]
        self.app.state.clock = lambda: current[0]
        application = self.app

        class ConnectedRequest:
            app = application

            async def is_disconnected(self) -> bool:
                return False

        async def consume() -> str:
            stream = _stream(
                cast(Request, ConnectedRequest()),
                EventStreamQuery(task_id=task.data.task_id),
            )
            retry = await anext(stream)
            self.assertEqual(retry, "retry: 3000\n\n")
            frame = await anext(stream)
            current[0] = current[0].replace(second=31)
            with self.assertRaises(StopAsyncIteration):
                await anext(stream)
            return frame

        frame = asyncio.run(consume())
        event_id = next(
            line.removeprefix("id: ")
            for line in frame.splitlines()
            if line.startswith("id: ")
        )
        response = self.client.get(
            f"/api/v1/tasks/{task.data.task_id}/events",
            headers=AUTH_HEADERS,
            params={"last_event_id": event_id},
        )
        resumed = EventListResponse.model_validate_json(response.content)
        self.assertEqual(resumed.items, [])


if __name__ == "__main__":
    unittest.main()

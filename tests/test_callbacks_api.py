from __future__ import annotations

import asyncio
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import HttpUrl, SecretStr

from parser_serve.api import create_app
from parser_serve.control.callbacks import CallbackHttpResult
from parser_serve.persistence import Database
from parser_serve.schema.callback import (
    CallbackAttemptListResponse,
    CallbackDeliveryListResponse,
    CallbackDeliveryResponse,
    CallbackEvent,
    CallbackTestEvent,
    CallbackTestResponse,
)
from parser_serve.settings import Environment, Settings


NOW = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)
API_KEY = f"parser_{'c' * 32}"
AUTH_HEADERS = {"Authorization": f"Bearer {API_KEY}"}
SECRET = "z" * 32


class SuccessfulTransport:
    def __init__(self) -> None:
        self.events: list[CallbackEvent | CallbackTestEvent] = []

    async def deliver(
        self,
        *,
        event: CallbackEvent | CallbackTestEvent,
        target_url: HttpUrl,
        secret: str | None,
        now: datetime,
    ) -> CallbackHttpResult:
        self.events.append(event)
        return CallbackHttpResult(
            delivered=True,
            status_code=204,
            duration_ms=3,
            response_summary=None,
            error=None,
        )


class CallbackApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        database_path = Path(self.temporary_directory.name) / "callbacks-api.sqlite3"
        self.database = Database(f"sqlite+aiosqlite:///{database_path}")
        asyncio.run(self.database.create_schema_for_testing())
        self.transport = SuccessfulTransport()
        self.app = create_app(
            Settings(
                environment=Environment.TEST,
                api_keys=[SecretStr(API_KEY)],
            ),
            clock=lambda: NOW,
            database=self.database,
            callback_transport=self.transport,
        )
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        self.client.close()
        asyncio.run(self.database.dispose())
        self.temporary_directory.cleanup()

    def create_callback_task(self) -> str:
        response = self.client.post(
            "/api/v1/tasks",
            headers=AUTH_HEADERS,
            json={
                "source": {"type": "text", "text": "callback"},
                "callback": {
                    "url": "https://callbacks.example/hook",
                    "events": ["task.created"],
                    "secret": SECRET,
                },
            },
        )
        self.assertEqual(response.status_code, 201)
        return response.json()["data"]["task_id"]

    def test_lists_dispatches_gets_and_manually_retries(self) -> None:
        task_id = self.create_callback_task()
        response = self.client.get(
            "/api/v1/management/callbacks",
            headers=AUTH_HEADERS,
            params={"task_id": task_id},
        )
        listing = CallbackDeliveryListResponse.model_validate_json(response.content)
        self.assertEqual(len(listing.items), 1)
        self.assertEqual(listing.items[0].status, "pending")
        delivery_id = listing.items[0].delivery_id

        dispatcher = self.app.state.callback_dispatcher
        self.assertIsNotNone(dispatcher)
        asyncio.run(dispatcher.run_once(now=NOW))
        response = self.client.get(
            f"/api/v1/management/callbacks/{delivery_id}",
            headers=AUTH_HEADERS,
        )
        detail = CallbackDeliveryResponse.model_validate_json(response.content)
        self.assertEqual(detail.data.status, "succeeded")
        self.assertEqual(detail.data.response_status_code, 204)

        response = self.client.get(
            f"/api/v1/management/callbacks/{delivery_id}/attempts",
            headers=AUTH_HEADERS,
        )
        attempts = CallbackAttemptListResponse.model_validate_json(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(attempts.items), 1)
        self.assertEqual(attempts.items[0].sequence, 1)
        self.assertEqual(attempts.items[0].attempt_number, 1)
        self.assertTrue(attempts.items[0].delivered)
        self.assertEqual(attempts.items[0].duration_ms, 3)

        response = self.client.post(
            f"/api/v1/management/callbacks/{delivery_id}/retry",
            headers=AUTH_HEADERS,
        )
        retried = CallbackDeliveryResponse.model_validate_json(response.content)
        self.assertEqual(retried.data.status, "pending")
        self.assertEqual(retried.data.attempt, 0)

        response = self.client.get(
            f"/api/v1/management/callbacks/{delivery_id}/attempts",
            headers=AUTH_HEADERS,
        )
        preserved = CallbackAttemptListResponse.model_validate_json(response.content)
        self.assertEqual(len(preserved.items), 1)

    def test_attempt_history_requires_an_existing_delivery(self) -> None:
        response = self.client.get(
            "/api/v1/management/callbacks/delivery_12345678/attempts",
            headers=AUTH_HEADERS,
        )
        self.assertEqual(response.status_code, 404)

    def test_callback_test_endpoint_uses_typed_transport(self) -> None:
        response = self.client.post(
            "/api/v1/management/callbacks/test",
            headers=AUTH_HEADERS,
            json={
                "url": "https://callbacks.example/hook",
                "secret": SECRET,
                "metadata": {"source": "dashboard"},
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        result = CallbackTestResponse.model_validate_json(response.content)
        self.assertTrue(result.data.delivered)
        self.assertEqual(result.data.response_status_code, 204)
        self.assertIsInstance(self.transport.events[-1], CallbackTestEvent)


if __name__ == "__main__":
    unittest.main()

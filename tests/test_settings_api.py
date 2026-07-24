from __future__ import annotations

import asyncio
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import SecretStr

from parser_serve.api import create_app
from parser_serve.persistence import Database
from parser_serve.schema.callback import CallbackDeliveryListResponse
from parser_serve.schema.management import (
    SettingKey,
    SettingSource,
    SystemSettingsResponse,
)
from parser_serve.settings import Environment, Settings
from parser_serve.storage import LocalFileStorage


NOW = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)
API_KEY = f"parser_{'s' * 32}"
AUTH_HEADERS = {"Authorization": f"Bearer {API_KEY}"}


class SystemSettingsApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        root = Path(self.temporary_directory.name)
        self.database = Database(f"sqlite+aiosqlite:///{root / 'settings.sqlite3'}")
        asyncio.run(self.database.create_schema_for_testing())
        self.client = TestClient(
            create_app(
                Settings(
                    environment=Environment.TEST,
                    api_keys=[SecretStr(API_KEY)],
                    maximum_upload_bytes=1024,
                    maximum_result_json_bytes=2048,
                    callback_maximum_attempts=5,
                ),
                clock=lambda: NOW,
                database=self.database,
                storage=LocalFileStorage(root / "storage"),
            )
        )

    def tearDown(self) -> None:
        self.client.close()
        asyncio.run(self.database.dispose())
        self.temporary_directory.cleanup()

    def test_lists_deployment_defaults_and_persists_typed_overrides(self) -> None:
        response = self.client.get(
            "/api/v1/management/settings",
            headers=AUTH_HEADERS,
        )
        self.assertEqual(response.status_code, 200)
        initial = SystemSettingsResponse.model_validate_json(response.content)
        self.assertEqual(len(initial.data.settings), 3)
        self.assertTrue(
            all(
                setting.source is SettingSource.DEPLOYMENT
                for setting in initial.data.settings
            )
        )

        response = self.client.patch(
            "/api/v1/management/settings",
            headers=AUTH_HEADERS,
            json={
                "settings": [
                    {"key": "maximum_upload_bytes", "value": 8},
                    {"key": "callback_maximum_attempts", "value": 7},
                ]
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        updated = SystemSettingsResponse.model_validate_json(response.content)
        values = {setting.key: setting for setting in updated.data.settings}
        self.assertEqual(values[SettingKey.MAXIMUM_UPLOAD_BYTES].value, 8)
        self.assertEqual(
            values[SettingKey.MAXIMUM_UPLOAD_BYTES].source,
            SettingSource.DATABASE,
        )
        self.assertEqual(
            values[SettingKey.MAXIMUM_RESULT_JSON_BYTES].source,
            SettingSource.DEPLOYMENT,
        )

        response = self.client.get(
            "/api/v1/capabilities",
            headers=AUTH_HEADERS,
        )
        self.assertEqual(response.json()["data"]["maximum_upload_bytes"], 8)

    def test_upload_limit_override_is_enforced_without_restart(self) -> None:
        response = self.client.patch(
            "/api/v1/management/settings",
            headers=AUTH_HEADERS,
            json={
                "settings": [
                    {"key": "maximum_upload_bytes", "value": 4},
                ]
            },
        )
        self.assertEqual(response.status_code, 200)

        response = self.client.post(
            "/api/v1/files",
            headers=AUTH_HEADERS,
            files={"file": ("note.txt", b"12345", "text/plain")},
        )

        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json()["error"]["code"], "FILE_TOO_LARGE")

    def test_callback_attempt_override_is_used_for_new_deliveries(self) -> None:
        response = self.client.patch(
            "/api/v1/management/settings",
            headers=AUTH_HEADERS,
            json={
                "settings": [
                    {"key": "callback_maximum_attempts", "value": 9},
                ]
            },
        )
        self.assertEqual(response.status_code, 200)
        task = self.client.post(
            "/api/v1/tasks",
            headers=AUTH_HEADERS,
            json={
                "source": {"type": "text", "text": "callback"},
                "callback": {
                    "url": "https://callbacks.example/hook",
                    "events": ["task.created"],
                },
            },
        )
        self.assertEqual(task.status_code, 201)

        response = self.client.get(
            "/api/v1/management/callbacks",
            headers=AUTH_HEADERS,
            params={"task_id": task.json()["data"]["task_id"]},
        )
        listing = CallbackDeliveryListResponse.model_validate_json(response.content)

        self.assertEqual(listing.items[0].maximum_attempts, 9)

    def test_rejects_invalid_values_and_requires_api_key(self) -> None:
        unauthenticated = self.client.get("/api/v1/management/settings")
        self.assertEqual(unauthenticated.status_code, 401)

        for value in (True, 0, "100"):
            with self.subTest(value=value):
                response = self.client.patch(
                    "/api/v1/management/settings",
                    headers=AUTH_HEADERS,
                    json={
                        "settings": [
                            {"key": "maximum_upload_bytes", "value": value},
                        ]
                    },
                )
                self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()

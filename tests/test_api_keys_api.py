from __future__ import annotations

import asyncio
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import SecretStr

from parser_serve.api import create_app
from parser_serve.persistence import Database
from parser_serve.schema.authentication import (
    ApiKeyListResponse,
    ApiKeyResponse,
    CreateApiKeyResponse,
    DeleteApiKeyResponse,
    RotateApiKeyResponse,
)
from parser_serve.schema.error import ErrorCode
from parser_serve.settings import Environment, Settings


NOW = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)
BOOTSTRAP_KEY = f"parser_{'b' * 32}"
AUTH_HEADERS = {"Authorization": f"Bearer {BOOTSTRAP_KEY}"}


class ApiKeyManagementApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        database_path = Path(self.temporary_directory.name) / "api.sqlite3"
        self.database = Database(f"sqlite+aiosqlite:///{database_path}")
        asyncio.run(self.database.create_schema_for_testing())
        settings = Settings(
            environment=Environment.TEST,
            api_keys=[SecretStr(BOOTSTRAP_KEY)],
        )
        self.client = TestClient(
            create_app(
                settings,
                clock=lambda: NOW,
                database=self.database,
            )
        )

    def tearDown(self) -> None:
        self.client.close()
        asyncio.run(self.database.dispose())
        self.temporary_directory.cleanup()

    def create_key(self, name: str) -> CreateApiKeyResponse:
        response = self.client.post(
            "/api/v1/management/api-keys",
            headers=AUTH_HEADERS,
            json={"name": name},
        )
        self.assertEqual(response.status_code, 201)
        return CreateApiKeyResponse.model_validate_json(response.content)

    def test_create_list_get_and_database_authentication(self) -> None:
        first = self.create_key("first")
        second = self.create_key("second")

        response = self.client.get(
            "/api/v1/management/api-keys",
            headers=AUTH_HEADERS,
            params={"limit": 1},
        )
        self.assertEqual(response.status_code, 200)
        first_page = ApiKeyListResponse.model_validate_json(response.content)
        self.assertEqual(len(first_page.items), 1)
        self.assertTrue(first_page.page.has_more)
        self.assertIsNotNone(first_page.page.next_cursor)

        response = self.client.get(
            "/api/v1/management/api-keys",
            headers=AUTH_HEADERS,
            params={"limit": 1, "cursor": first_page.page.next_cursor},
        )
        second_page = ApiKeyListResponse.model_validate_json(response.content)
        self.assertEqual(len(second_page.items), 1)
        self.assertNotEqual(
            first_page.items[0].api_key_id,
            second_page.items[0].api_key_id,
        )

        response = self.client.get(
            "/api/v1/management/api-keys",
            headers=AUTH_HEADERS,
            params={
                "limit": 1,
                "sort_by": "name",
                "sort_direction": "asc",
            },
        )
        name_page = ApiKeyListResponse.model_validate_json(response.content)
        self.assertEqual([item.name for item in name_page.items], ["first"])
        self.assertTrue(name_page.page.has_more)

        response = self.client.get(
            "/api/v1/management/api-keys",
            headers=AUTH_HEADERS,
            params={
                "limit": 1,
                "sort_by": "name",
                "sort_direction": "asc",
                "cursor": name_page.page.next_cursor,
            },
        )
        next_name_page = ApiKeyListResponse.model_validate_json(response.content)
        self.assertEqual([item.name for item in next_name_page.items], ["second"])

        response = self.client.get(
            "/api/v1/management/api-keys",
            headers=AUTH_HEADERS,
            params={
                "sort_by": "created_at",
                "cursor": name_page.page.next_cursor,
            },
        )
        self.assertEqual(response.status_code, 422)

        response = self.client.get(
            f"/api/v1/management/api-keys/{first.data.summary.api_key_id}",
            headers=AUTH_HEADERS,
        )
        detail = ApiKeyResponse.model_validate_json(response.content)
        self.assertEqual(detail.data.name, "first")

        response = self.client.get(
            "/api/v1/capabilities",
            headers={"Authorization": f"Bearer {second.data.api_key}"},
        )
        self.assertEqual(response.status_code, 200)

    def test_update_rotate_delete_and_protect_final_active_key(self) -> None:
        first = self.create_key("first")
        second = self.create_key("second")

        response = self.client.patch(
            f"/api/v1/management/api-keys/{first.data.summary.api_key_id}",
            headers=AUTH_HEADERS,
            json={"name": "renamed", "enabled": False},
        )
        updated = ApiKeyResponse.model_validate_json(response.content)
        self.assertEqual(updated.data.name, "renamed")
        self.assertEqual(updated.data.status, "disabled")

        response = self.client.post(
            f"/api/v1/management/api-keys/{second.data.summary.api_key_id}/rotate",
            headers=AUTH_HEADERS,
        )
        rotated = RotateApiKeyResponse.model_validate_json(response.content)
        self.assertNotEqual(rotated.data.api_key, second.data.api_key)

        old_key_response = self.client.get(
            "/api/v1/capabilities",
            headers={"Authorization": f"Bearer {second.data.api_key}"},
        )
        self.assertEqual(old_key_response.status_code, 401)
        new_key_response = self.client.get(
            "/api/v1/capabilities",
            headers={"Authorization": f"Bearer {rotated.data.api_key}"},
        )
        self.assertEqual(new_key_response.status_code, 200)

        response = self.client.delete(
            f"/api/v1/management/api-keys/{first.data.summary.api_key_id}",
            headers=AUTH_HEADERS,
        )
        deleted = DeleteApiKeyResponse.model_validate_json(response.content)
        self.assertTrue(deleted.data.deleted)

        response = self.client.delete(
            f"/api/v1/management/api-keys/{second.data.summary.api_key_id}",
            headers=AUTH_HEADERS,
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], ErrorCode.CONFLICT)

    def test_rejects_expired_creation_and_invalid_cursor(self) -> None:
        response = self.client.post(
            "/api/v1/management/api-keys",
            headers=AUTH_HEADERS,
            json={
                "name": "expired",
                "expires_at": (NOW - timedelta(seconds=1)).isoformat(),
            },
        )
        self.assertEqual(response.status_code, 422)

        response = self.client.get(
            "/api/v1/management/api-keys",
            headers=AUTH_HEADERS,
            params={"cursor": "not-a-cursor"},
        )
        self.assertEqual(response.status_code, 422)

    def test_missing_database_is_reported_as_unavailable(self) -> None:
        app = create_app(
            Settings(
                environment=Environment.TEST,
                api_keys=[SecretStr(BOOTSTRAP_KEY)],
            ),
            clock=lambda: NOW,
        )
        client = TestClient(app)
        try:
            response = client.get(
                "/api/v1/management/api-keys",
                headers=AUTH_HEADERS,
            )
        finally:
            client.close()

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json()["error"]["code"],
            ErrorCode.DEPENDENCY_UNAVAILABLE,
        )


if __name__ == "__main__":
    unittest.main()

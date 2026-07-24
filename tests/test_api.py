from __future__ import annotations

import json
import tomllib
import unittest
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError

from parser_serve.api import create_app
from parser_serve.schema.common import HealthResponse
from parser_serve.schema.error import ErrorCode, ErrorResponse
from parser_serve.schema.management import (
    ParserCapabilitiesData,
    SystemInfoData,
)
from parser_serve.settings import Environment, Settings


NOW = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)
API_KEY = f"parser_{'a' * 32}"


def make_test_settings(*, with_api_key: bool = True) -> Settings:
    return Settings(
        environment=Environment.TEST,
        api_keys=[SecretStr(API_KEY)] if with_api_key else [],
    )


class SettingsTests(unittest.TestCase):
    def test_package_and_default_application_versions_match(self) -> None:
        pyproject = tomllib.loads(
            (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(
                encoding="utf-8"
            )
        )

        self.assertEqual(
            pyproject["project"]["version"],
            Settings().app_version,
        )

    def test_rejects_invalid_api_key(self) -> None:
        with self.assertRaises(ValidationError):
            Settings(api_keys=[SecretStr("short")])

    def test_rejects_duplicate_api_keys(self) -> None:
        with self.assertRaises(ValidationError):
            Settings(api_keys=[SecretStr(API_KEY), SecretStr(API_KEY)])

    def test_secret_is_not_exposed_by_repr(self) -> None:
        settings = make_test_settings()

        self.assertNotIn(API_KEY, repr(settings))


class HealthApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = create_app(make_test_settings(), clock=lambda: NOW)
        self.client = TestClient(self.app)

    def test_health_does_not_require_authentication(self) -> None:
        response = self.client.get("/health")

        self.assertEqual(response.status_code, 200)
        payload = HealthResponse.model_validate_json(response.content)
        self.assertEqual(payload.data.timestamp, NOW)
        self.assertEqual(response.headers["X-Request-ID"], payload.request_id)

    def test_readiness_is_typed(self) -> None:
        response = self.client.get("/ready")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["data"]["healthy"])
        self.assertEqual(response.json()["data"]["components"][0]["name"], "api")
        self.assertEqual(
            response.json()["data"]["components"][1]["name"],
            "storage",
        )

    def test_readiness_reports_storage_failure_without_leaking_details(self) -> None:
        class UnavailableStorage:
            async def exists(self, key: str) -> bool:
                raise RuntimeError("secret endpoint detail")

        app = create_app(
            make_test_settings(),
            clock=lambda: NOW,
            storage=UnavailableStorage(),  # type: ignore[arg-type]
        )
        response = TestClient(app).get("/ready")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["data"]["healthy"])
        storage = response.json()["data"]["components"][1]
        self.assertEqual(storage["name"], "storage")
        self.assertEqual(storage["message"], "Storage check failed: RuntimeError")
        self.assertNotIn("secret endpoint detail", response.text)

    def test_accepts_valid_request_id(self) -> None:
        response = self.client.get(
            "/health",
            headers={"X-Request-ID": "req_external123"},
        )

        self.assertEqual(response.headers["X-Request-ID"], "req_external123")
        self.assertEqual(response.json()["request_id"], "req_external123")

    def test_replaces_invalid_request_id(self) -> None:
        response = self.client.get(
            "/health",
            headers={"X-Request-ID": "invalid"},
        )

        request_id = response.headers["X-Request-ID"]
        self.assertRegex(request_id, r"^req_[a-zA-Z0-9_-]{8,64}$")
        self.assertNotEqual(request_id, "invalid")


class AuthenticationApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = create_app(make_test_settings(), clock=lambda: NOW)
        self.client = TestClient(self.app)

    def test_requires_api_key(self) -> None:
        response = self.client.get("/api/v1/capabilities")

        self.assertEqual(response.status_code, 401)
        error = ErrorResponse.model_validate_json(response.content)
        self.assertEqual(error.error.code, ErrorCode.AUTHENTICATION_FAILED)

    def test_accepts_bearer_api_key(self) -> None:
        response = self.client.get(
            "/api/v1/capabilities",
            headers={"Authorization": f"Bearer {API_KEY}"},
        )

        self.assertEqual(response.status_code, 200)
        data = ParserCapabilitiesData.model_validate_json(
            json.dumps(response.json()["data"])
        )
        self.assertEqual(data.schema_version, "1.0")
        self.assertEqual(data.backends, [])

    def test_accepts_x_api_key(self) -> None:
        response = self.client.get(
            "/api/v1/system/info",
            headers={"X-API-Key": API_KEY},
        )

        self.assertEqual(response.status_code, 200)
        data = SystemInfoData.model_validate_json(json.dumps(response.json()["data"]))
        self.assertEqual(data.name, "Parser Serve")
        self.assertEqual(data.api_version, "1.0")

    def test_system_info_exposes_injected_build_metadata(self) -> None:
        build_time = datetime(2026, 7, 24, 10, 30, tzinfo=UTC)
        app = create_app(
            Settings(
                environment=Environment.TEST,
                api_keys=[SecretStr(API_KEY)],
                build_commit="abcdef123456",
                build_time=build_time,
            ),
            clock=lambda: NOW,
        )

        response = TestClient(app).get(
            "/api/v1/system/info",
            headers={"Authorization": f"Bearer {API_KEY}"},
        )
        data = SystemInfoData.model_validate(response.json()["data"])

        self.assertEqual(data.build_commit, "abcdef123456")
        self.assertEqual(data.build_time, build_time)

    def test_rejects_invalid_bearer_scheme(self) -> None:
        response = self.client.get(
            "/api/v1/capabilities",
            headers={"Authorization": f"Basic {API_KEY}"},
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.json()["error"]["code"],
            ErrorCode.AUTHENTICATION_FAILED,
        )

    def test_rejects_conflicting_credentials(self) -> None:
        response = self.client.get(
            "/api/v1/capabilities",
            headers={
                "Authorization": f"Bearer {API_KEY}",
                "X-API-Key": f"parser_{'b' * 32}",
            },
        )

        self.assertEqual(response.status_code, 401)

    def test_no_configured_key_denies_all_credentials(self) -> None:
        app = create_app(make_test_settings(with_api_key=False), clock=lambda: NOW)
        client = TestClient(app)

        response = client.get(
            "/api/v1/capabilities",
            headers={"Authorization": f"Bearer {API_KEY}"},
        )

        self.assertEqual(response.status_code, 401)

    def test_cors_allows_configured_web_ui_origin_only(self) -> None:
        response = self.client.options(
            "/api/v1/capabilities",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers["access-control-allow-origin"],
            "http://localhost:5173",
        )

        response = self.client.options(
            "/api/v1/capabilities",
            headers={
                "Origin": "https://untrusted.example",
                "Access-Control-Request-Method": "GET",
            },
        )
        self.assertNotIn("access-control-allow-origin", response.headers)


class OpenApiContractTests(unittest.TestCase):
    def test_operations_have_unique_ids_and_typed_errors(self) -> None:
        app = create_app(make_test_settings(), clock=lambda: NOW)
        schema = app.openapi()
        operation_ids: list[str] = []

        for path_item in schema["paths"].values():
            for operation in path_item.values():
                operation_ids.append(operation["operationId"])
                responses = operation["responses"]
                self.assertIn("422", responses)
                self.assertIn("500", responses)

        self.assertEqual(len(operation_ids), len(set(operation_ids)))
        self.assertEqual(
            set(operation_ids),
            {
                "get_health",
                "get_readiness",
                "get_metrics",
                "get_capabilities",
                "get_system_info",
                "get_system_settings",
                "update_system_settings",
                "get_dashboard_summary",
                "run_retention_cleanup",
                "create_api_key",
                "list_api_keys",
                "get_api_key",
                "update_api_key",
                "rotate_api_key",
                "delete_api_key",
                "create_task",
                "upload_file",
                "get_uploaded_file",
                "download_uploaded_file",
                "list_tasks",
                "get_task",
                "list_task_stages",
                "get_task_stage",
                "get_task_result",
                "download_task_result",
                "list_task_artifacts",
                "download_task_artifact",
                "create_task_artifact_download_url",
                "cancel_task",
                "retry_task",
                "create_backend",
                "list_backends",
                "get_backend",
                "update_backend",
                "initialize_default_catalog",
                "create_pipeline",
                "list_pipelines",
                "get_pipeline",
                "validate_pipeline",
                "test_pipeline",
                "publish_pipeline",
                "route_task",
                "register_worker",
                "heartbeat_worker",
                "drain_worker_self",
                "lease_stages",
                "renew_stage_lease",
                "start_stage",
                "update_stage_progress",
                "complete_stage",
                "list_workers",
                "get_worker",
                "update_worker",
                "reconcile_workers",
                "download_worker_source_file",
                "upload_stage_artifact",
                "list_events",
                "list_task_events",
                "stream_events",
                "stream_task_events",
                "list_callback_deliveries",
                "get_callback_delivery",
                "list_callback_attempts",
                "retry_callback_delivery",
                "test_callback",
            },
        )


if __name__ == "__main__":
    unittest.main()

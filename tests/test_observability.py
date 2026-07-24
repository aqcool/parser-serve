from __future__ import annotations

import asyncio
import io
import json
import logging
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import SecretStr

from parser_serve.api import create_app
from parser_serve.observability import (
    CorrelationFilter,
    JsonLogFormatter,
    correlation_context,
    log_context,
)
from parser_serve.persistence import Database
from parser_serve.persistence.models import TaskRecord
from parser_serve.settings import Environment, Settings
from parser_serve.storage import LocalFileStorage


NOW = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)
API_KEY = f"parser_{'a' * 32}"
AUTH_HEADERS = {"Authorization": f"Bearer {API_KEY}"}


def make_test_settings() -> Settings:
    return Settings(
        environment=Environment.TEST,
        api_keys=[SecretStr(API_KEY)],
    )


class StructuredLoggingTests(unittest.TestCase):
    def test_json_formatter_includes_correlation_and_structured_fields(self) -> None:
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.addFilter(CorrelationFilter())
        handler.setFormatter(JsonLogFormatter())
        logger = logging.getLogger("parser_serve.test.observability")
        logger.handlers = [handler]
        logger.propagate = False
        logger.setLevel(logging.INFO)

        with log_context(
            request_id="req_observability1",
            task_id="task_observability1",
            stage_id="stage_observability1",
            worker_id="worker_observability1",
        ):
            logger.info(
                "stage completed",
                extra={"status_code": 200, "duration_ms": 12.5},
            )

        payload = json.loads(stream.getvalue())
        self.assertEqual(payload["message"], "stage completed")
        self.assertEqual(payload["request_id"], "req_observability1")
        self.assertEqual(payload["task_id"], "task_observability1")
        self.assertEqual(payload["stage_id"], "stage_observability1")
        self.assertEqual(payload["worker_id"], "worker_observability1")
        self.assertEqual(payload["status_code"], 200)
        self.assertEqual(payload["duration_ms"], 12.5)

    def test_log_context_is_reset_after_scope(self) -> None:
        self.assertEqual(correlation_context(), {})
        with log_context(request_id="req_observability2"):
            self.assertEqual(
                correlation_context(),
                {"request_id": "req_observability2"},
            )
        self.assertEqual(correlation_context(), {})


class MetricsApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(create_app(make_test_settings(), clock=lambda: NOW))

    def tearDown(self) -> None:
        self.client.close()

    def test_metrics_requires_ordinary_api_key(self) -> None:
        response = self.client.get("/metrics")

        self.assertEqual(response.status_code, 401)

    def test_metrics_returns_prometheus_format_and_templated_route_labels(
        self,
    ) -> None:
        self.client.get("/health")
        response = self.client.get("/metrics", headers=AUTH_HEADERS)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers["content-type"],
            "text/plain; version=0.0.4; charset=utf-8",
        )
        self.assertIn("# HELP parser_http_requests_total", response.text)
        self.assertIn(
            'parser_http_requests_total{method="GET",route="/health",'
            'status_code="200"} 1.0',
            response.text,
        )
        self.assertNotIn(API_KEY, response.text)

    def test_metrics_route_can_be_disabled(self) -> None:
        settings = make_test_settings()
        settings.metrics_enabled = False
        client = TestClient(create_app(settings, clock=lambda: NOW))
        try:
            response = client.get("/metrics", headers=AUTH_HEADERS)
        finally:
            client.close()

        self.assertEqual(response.status_code, 404)

    def test_metrics_refreshes_persistent_task_gauges(self) -> None:
        temporary_directory = tempfile.TemporaryDirectory()
        root = Path(temporary_directory.name)
        database = Database(f"sqlite+aiosqlite:///{root / 'metrics.sqlite3'}")

        async def seed() -> None:
            await database.create_schema_for_testing()
            async with database.session_factory() as session:
                session.add(
                    TaskRecord(
                        task_id="task_metrics1",
                        status="succeeded",
                        progress_percent=100.0,
                        source_payload={"type": "text", "text": "metrics"},
                        options_payload={},
                        priority=0,
                    )
                )
                await session.commit()

        asyncio.run(seed())
        client = TestClient(
            create_app(
                make_test_settings(),
                clock=lambda: NOW,
                database=database,
                storage=LocalFileStorage(root / "storage"),
            )
        )
        try:
            response = client.get("/metrics", headers=AUTH_HEADERS)
        finally:
            client.close()
            asyncio.run(database.dispose())
            temporary_directory.cleanup()

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            'parser_task_records{status="succeeded"} 1.0',
            response.text,
        )


if __name__ == "__main__":
    unittest.main()

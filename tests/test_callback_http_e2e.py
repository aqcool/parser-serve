from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from pydantic import HttpUrl
from sqlalchemy import select

from parser_serve.control.callbacks import (
    CallbackDispatcher,
    HttpCallbackTransport,
    callback_signature,
)
from parser_serve.persistence import CallbackRepository, Database
from parser_serve.persistence.models import CallbackDeliveryRecord
from parser_serve.persistence.tasks import TaskRepository
from parser_serve.schema.callback import CallbackConfig, CallbackEventType
from parser_serve.schema.source import TextSource
from parser_serve.schema.task import CreateTaskRequest, TaskOptions


NOW = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)
SECRET = "e2e-secret-" + ("x" * 32)


class IdempotentCallbackReceiver:
    """Minimal real TCP receiver implementing the documented consumer contract."""

    def __init__(self) -> None:
        self.server: asyncio.Server | None = None
        self.url: HttpUrl | None = None
        self.request_count = 0
        self.applied_event_ids: set[str] = set()
        self.signatures_valid: list[bool] = []

    async def __aenter__(self) -> IdempotentCallbackReceiver:
        self.server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        address = self.server.sockets[0].getsockname()
        self.url = HttpUrl(f"http://127.0.0.1:{address[1]}/callback")
        return self

    async def __aexit__(self, *_: object) -> None:
        if self.server is not None:
            self.server.close()
            await self.server.wait_closed()

    async def _handle(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        try:
            header_bytes = await reader.readuntil(b"\r\n\r\n")
            header_lines = header_bytes.decode("latin-1").split("\r\n")
            headers = {
                name.casefold(): value.strip()
                for name, value in (
                    line.split(":", 1) for line in header_lines[1:] if ":" in line
                )
            }
            body = await reader.readexactly(int(headers["content-length"]))
            event_id = str(json.loads(body)["event_id"])
            expected_signature = callback_signature(
                secret=SECRET,
                timestamp=headers["x-parser-timestamp"],
                body=body,
            )
            self.request_count += 1
            self.signatures_valid.append(
                headers.get("x-parser-signature") == expected_signature
                and headers.get("x-parser-event-id") == event_id
            )
            self.applied_event_ids.add(event_id)
            writer.write(
                b"HTTP/1.1 204 No Content\r\n"
                b"Content-Length: 0\r\n"
                b"Connection: close\r\n\r\n"
            )
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()


async def _allow_loopback_for_local_e2e(*_: object, **__: object) -> None:
    """The production SSRF validator is covered separately from this TCP test."""


class CallbackHttpEndToEndTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        database_path = Path(self.temporary_directory.name) / "callback-e2e.sqlite3"
        self.database = Database(f"sqlite+aiosqlite:///{database_path}")
        await self.database.create_schema_for_testing()
        self.repository = CallbackRepository()

    async def asyncTearDown(self) -> None:
        await self.database.dispose()
        self.temporary_directory.cleanup()

    async def test_manual_redelivery_is_idempotent_at_real_receiver(self) -> None:
        async with IdempotentCallbackReceiver() as receiver:
            self.assertIsNotNone(receiver.url)
            async with self.database.session_factory() as session:
                await TaskRepository().create(
                    session,
                    request=CreateTaskRequest(
                        source=TextSource(type="text", text="callback e2e"),
                        options=TaskOptions(),
                        callback=CallbackConfig(
                            url=receiver.url,
                            events=[CallbackEventType.TASK_CREATED],
                            secret=SECRET,
                        ),
                    ),
                    idempotency_key=None,
                    now=NOW,
                )
                await session.commit()

            transport = HttpCallbackTransport(
                timeout_seconds=2,
                maximum_response_bytes=1024,
            )
            dispatcher = CallbackDispatcher(
                database=self.database,
                repository=self.repository,
                transport=transport,
                maximum_attempts=3,
                initial_retry_seconds=1,
                maximum_retry_seconds=10,
                claim_timeout_seconds=10,
            )
            try:
                with patch(
                    "parser_serve.control.callbacks.validate_callback_url",
                    new=_allow_loopback_for_local_e2e,
                ):
                    self.assertEqual(await dispatcher.run_once(now=NOW), 1)
                    async with self.database.session_factory() as session:
                        delivery = await session.scalar(select(CallbackDeliveryRecord))
                        self.assertIsNotNone(delivery)
                        if delivery is None:
                            return
                        retried = await self.repository.retry(
                            session,
                            delivery_id=delivery.delivery_id,
                            now=NOW + timedelta(seconds=1),
                        )
                        await session.commit()
                    self.assertIsNotNone(retried)
                    self.assertEqual(
                        await dispatcher.run_once(now=NOW + timedelta(seconds=1)),
                        1,
                    )
            finally:
                await transport.aclose()

        self.assertEqual(receiver.request_count, 2)
        self.assertEqual(len(receiver.applied_event_ids), 1)
        self.assertEqual(receiver.signatures_valid, [True, True])

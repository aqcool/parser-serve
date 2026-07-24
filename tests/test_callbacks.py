from __future__ import annotations

import hashlib
import hmac
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from pydantic import HttpUrl
from sqlalchemy import select

from parser_serve.control.callbacks import (
    CallbackDispatcher,
    CallbackHttpResult,
    HttpCallbackTransport,
    callback_signature,
    validate_callback_url,
)
from parser_serve.persistence import CallbackRepository, Database
from parser_serve.persistence.callbacks import callback_delivery_detail
from parser_serve.persistence.models import (
    CallbackAttemptRecord,
    CallbackDeliveryRecord,
    EventRecord,
)
from parser_serve.persistence.tasks import TaskRepository
from parser_serve.schema.callback import (
    CallbackConfig,
    CallbackDeliveryStatus,
    CallbackEvent,
    CallbackEventType,
    CallbackTestEvent,
    TaskCreatedCallback,
)
from parser_serve.schema.error import ErrorCode, ErrorDetail
from parser_serve.schema.task import CreateTaskRequest, TaskOptions
from parser_serve.schema.source import TextSource


NOW = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)
SECRET = "s" * 32


def callback_event() -> CallbackEvent:
    return CallbackEvent(
        schema_version="1.0",
        event_id="event_callback12",
        task_id="task_callback12",
        occurred_at=NOW,
        payload=TaskCreatedCallback(type="task.created", created_at=NOW),
    )


class CallbackSecurityTests(unittest.IsolatedAsyncioTestCase):
    async def test_rejects_private_literal_and_mixed_dns_answers(self) -> None:
        with self.assertRaisesRegex(ValueError, "not public"):
            await validate_callback_url(HttpUrl("http://127.0.0.1/hook"))

        async def mixed(_: str, __: int) -> set[str]:
            return {"8.8.8.8", "10.0.0.1"}

        with self.assertRaisesRegex(ValueError, "not public"):
            await validate_callback_url(
                HttpUrl("https://callbacks.example/hook"),
                resolver=mixed,
            )

    async def test_signs_canonical_body_and_does_not_follow_redirects(self) -> None:
        captured: dict[str, object] = {}

        async def handler(request: httpx.Request) -> httpx.Response:
            captured["headers"] = request.headers
            captured["body"] = request.content
            return httpx.Response(
                302,
                headers={"Location": "http://127.0.0.1/private"},
                text="redirect",
            )

        async def public(_: str, __: int) -> set[str]:
            return {"8.8.8.8"}

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        transport = HttpCallbackTransport(
            timeout_seconds=1,
            maximum_response_bytes=1024,
            resolver=public,
            client=client,
        )
        try:
            result = await transport.deliver(
                event=callback_event(),
                target_url=HttpUrl("https://callbacks.example/hook"),
                secret=SECRET,
                now=NOW,
            )
        finally:
            await client.aclose()

        self.assertFalse(result.delivered)
        self.assertEqual(result.status_code, 302)
        headers = captured["headers"]
        self.assertIsInstance(headers, httpx.Headers)
        body = captured["body"]
        self.assertIsInstance(body, bytes)
        if isinstance(headers, httpx.Headers) and isinstance(body, bytes):
            timestamp = str(int(NOW.timestamp()))
            expected = (
                "v1="
                + hmac.new(
                    SECRET.encode(),
                    timestamp.encode() + b"." + body,
                    hashlib.sha256,
                ).hexdigest()
            )
            self.assertEqual(headers["X-Parser-Signature"], expected)
            self.assertEqual(headers["X-Parser-Event-ID"], "event_callback12")

    async def test_signature_helper_is_stable(self) -> None:
        body = b'{"hello":"world"}'
        first = callback_signature(
            secret=SECRET,
            timestamp="123",
            body=body,
        )
        second = callback_signature(
            secret=SECRET,
            timestamp="123",
            body=body,
        )
        self.assertEqual(first, second)
        self.assertNotEqual(
            first,
            callback_signature(
                secret=SECRET,
                timestamp="124",
                body=body,
            ),
        )


class FakeCallbackTransport:
    def __init__(self, results: list[CallbackHttpResult]) -> None:
        self.results = results
        self.events: list[CallbackEvent | CallbackTestEvent] = []
        self.secrets: list[str | None] = []

    async def deliver(
        self,
        *,
        event: CallbackEvent | CallbackTestEvent,
        target_url: HttpUrl,
        secret: str | None,
        now: datetime,
    ) -> CallbackHttpResult:
        self.events.append(event)
        self.secrets.append(secret)
        return self.results.pop(0)


class CallbackDispatcherTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        database_path = Path(self.temporary_directory.name) / "callbacks.sqlite3"
        self.database = Database(f"sqlite+aiosqlite:///{database_path}")
        await self.database.create_schema_for_testing()
        self.repository = CallbackRepository()

    async def asyncTearDown(self) -> None:
        await self.database.dispose()
        self.temporary_directory.cleanup()

    async def create_task(self) -> str:
        async with self.database.session_factory() as session:
            task, _ = await TaskRepository().create(
                session,
                request=CreateTaskRequest(
                    source=TextSource(type="text", text="callback"),
                    options=TaskOptions(),
                    callback=CallbackConfig(
                        url=HttpUrl("https://callbacks.example/hook"),
                        events=[CallbackEventType.TASK_CREATED],
                        secret=SECRET,
                    ),
                ),
                idempotency_key=None,
                now=NOW,
            )
            await session.commit()
            return task.task_id

    async def test_successful_delivery_is_independent_from_task_state(self) -> None:
        task_id = await self.create_task()
        transport = FakeCallbackTransport(
            [
                CallbackHttpResult(
                    delivered=True,
                    status_code=204,
                    duration_ms=5,
                    response_summary=None,
                    error=None,
                )
            ]
        )
        dispatcher = CallbackDispatcher(
            database=self.database,
            repository=self.repository,
            transport=transport,
            maximum_attempts=3,
            initial_retry_seconds=2,
            maximum_retry_seconds=30,
            claim_timeout_seconds=60,
        )

        count = await dispatcher.run_once(now=NOW)

        self.assertEqual(count, 1)
        self.assertEqual(transport.secrets, [SECRET])
        async with self.database.session_factory() as session:
            delivery = await session.scalar(select(CallbackDeliveryRecord))
            attempts = list(
                await session.scalars(
                    select(CallbackAttemptRecord).order_by(
                        CallbackAttemptRecord.sequence
                    )
                )
            )
            task = await TaskRepository().get(session, task_id)
            callback_events = list(
                await session.scalars(
                    select(EventRecord).where(
                        EventRecord.event_type == "callback.delivery_changed"
                    )
                )
            )
        self.assertIsNotNone(delivery)
        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[0].sequence, 1)
        self.assertEqual(attempts[0].attempt_number, 1)
        self.assertTrue(attempts[0].delivered)
        self.assertEqual(attempts[0].response_status_code, 204)
        self.assertEqual(attempts[0].duration_ms, 5)
        self.assertIsNone(attempts[0].error_payload)
        if delivery is not None:
            detail = callback_delivery_detail(delivery)
            self.assertEqual(detail.status, CallbackDeliveryStatus.SUCCEEDED)
            self.assertEqual(detail.attempt, 1)
            self.assertEqual(detail.response_status_code, 204)
        self.assertIsNotNone(task)
        if task is not None:
            self.assertEqual(task.status, "pending")
        self.assertEqual(len(callback_events), 3)

    async def test_retries_with_backoff_then_dead_letters_and_manual_retry(
        self,
    ) -> None:
        await self.create_task()
        failure = CallbackHttpResult(
            delivered=False,
            status_code=503,
            duration_ms=2,
            response_summary="unavailable",
            error=ErrorDetail(
                code=ErrorCode.DEPENDENCY_UNAVAILABLE,
                message="unavailable",
                retryable=True,
            ),
        )
        transport = FakeCallbackTransport([failure, failure])
        dispatcher = CallbackDispatcher(
            database=self.database,
            repository=self.repository,
            transport=transport,
            maximum_attempts=2,
            initial_retry_seconds=2,
            maximum_retry_seconds=30,
            claim_timeout_seconds=60,
        )

        await dispatcher.run_once(now=NOW)
        async with self.database.session_factory() as session:
            delivery = await session.scalar(select(CallbackDeliveryRecord))
        self.assertIsNotNone(delivery)
        if delivery is None:
            return
        self.assertEqual(delivery.status, CallbackDeliveryStatus.RETRY_WAIT)
        self.assertIsNotNone(delivery.next_attempt_at)
        if delivery.next_attempt_at is None:
            return
        self.assertEqual(
            delivery.next_attempt_at.replace(tzinfo=UTC),
            NOW + timedelta(seconds=2),
        )

        self.assertEqual(
            await dispatcher.run_once(now=NOW + timedelta(seconds=1)),
            0,
        )
        self.assertEqual(
            await dispatcher.run_once(now=NOW + timedelta(seconds=2)),
            1,
        )
        async with self.database.session_factory() as session:
            delivery = await self.repository.get(session, delivery.delivery_id)
            self.assertIsNotNone(delivery)
            if delivery is None:
                return
            self.assertEqual(delivery.status, CallbackDeliveryStatus.FAILED)
            retried = await self.repository.retry(
                session,
                delivery_id=delivery.delivery_id,
                now=NOW + timedelta(seconds=3),
            )
            await session.commit()
        self.assertIsNotNone(retried)
        if retried is not None:
            self.assertEqual(retried.status, CallbackDeliveryStatus.PENDING)
            self.assertEqual(retried.attempt, 0)
        async with self.database.session_factory() as session:
            attempts = list(
                await session.scalars(
                    select(CallbackAttemptRecord).order_by(
                        CallbackAttemptRecord.sequence
                    )
                )
            )
        self.assertEqual([attempt.sequence for attempt in attempts], [1, 2])
        self.assertEqual([attempt.attempt_number for attempt in attempts], [1, 2])
        self.assertTrue(all(not attempt.delivered for attempt in attempts))
        self.assertTrue(all(attempt.error_payload is not None for attempt in attempts))

    async def test_stale_claim_result_is_audited_without_overwriting_new_claim(
        self,
    ) -> None:
        await self.create_task()
        async with self.database.session_factory() as session:
            await self.repository.materialize(
                session,
                now=NOW,
                maximum_attempts=3,
            )
            first = await self.repository.claim_due(
                session,
                now=NOW,
                claim_timeout_seconds=60,
            )
            await session.commit()
        self.assertIsNotNone(first)
        if first is None:
            return

        takeover_time = NOW + timedelta(seconds=61)
        async with self.database.session_factory() as session:
            second = await self.repository.claim_due(
                session,
                now=takeover_time,
                claim_timeout_seconds=60,
            )
            await session.commit()
        self.assertIsNotNone(second)
        if second is None:
            return
        self.assertEqual(second.attempt_sequence, 2)

        async with self.database.session_factory() as session:
            delivery = await self.repository.record_result(
                session,
                delivery_id=first.delivery_id,
                sequence=1,
                attempt_number=1,
                delivered=False,
                retryable=True,
                response_status_code=503,
                response_summary="late response",
                duration_ms=100,
                error=ErrorDetail(
                    code=ErrorCode.DEPENDENCY_UNAVAILABLE,
                    message="late response",
                    retryable=True,
                ),
                now=takeover_time,
                initial_retry_seconds=2,
                maximum_retry_seconds=30,
            )
            await session.commit()
        self.assertIsNotNone(delivery)
        if delivery is not None:
            self.assertEqual(delivery.status, CallbackDeliveryStatus.DELIVERING)
            self.assertEqual(delivery.attempt_sequence, 2)

        async with self.database.session_factory() as session:
            delivery = await self.repository.record_result(
                session,
                delivery_id=second.delivery_id,
                sequence=2,
                attempt_number=2,
                delivered=True,
                retryable=False,
                response_status_code=204,
                response_summary=None,
                duration_ms=5,
                error=None,
                now=takeover_time,
                initial_retry_seconds=2,
                maximum_retry_seconds=30,
            )
            await session.commit()
            attempts = list(
                await session.scalars(
                    select(CallbackAttemptRecord).order_by(
                        CallbackAttemptRecord.sequence
                    )
                )
            )
        self.assertIsNotNone(delivery)
        if delivery is not None:
            self.assertEqual(delivery.status, CallbackDeliveryStatus.SUCCEEDED)
        self.assertEqual([attempt.sequence for attempt in attempts], [1, 2])


if __name__ == "__main__":
    unittest.main()

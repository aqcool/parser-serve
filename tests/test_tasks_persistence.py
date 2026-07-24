from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from parser_serve.persistence import Database
from parser_serve.persistence.models import EventRecord
from parser_serve.persistence.tasks import (
    IdempotencyConflictError,
    PipelineNotFoundError,
    TaskNotCancellableError,
    TaskRepository,
    task_detail,
)
from parser_serve.schema.common import MediaCategory
from parser_serve.schema.task import (
    CreateTaskRequest,
    TaskListQuery,
    TaskStatus,
)


NOW = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)


def task_request(text: str = "hello") -> CreateTaskRequest:
    return CreateTaskRequest.model_validate(
        {
            "source": {
                "type": "text",
                "text": text,
                "filename": "note.txt",
            },
            "client_reference": "external-42",
        }
    )


class TaskRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.database = Database("sqlite+aiosqlite:///:memory:")
        await self.database.create_schema_for_testing()
        self.repository = TaskRepository()

    async def asyncTearDown(self) -> None:
        await self.database.dispose()

    async def test_create_normalizes_text_and_writes_event(self) -> None:
        async with self.database.session_factory() as session:
            record, created = await self.repository.create(
                session,
                request=task_request(),
                idempotency_key=None,
                now=NOW,
            )
            await session.commit()

        self.assertTrue(created)
        async with self.database.session_factory() as session:
            loaded = await self.repository.get(session, record.task_id)
            events = list(await session.scalars(select(EventRecord)))

        self.assertIsNotNone(loaded)
        if loaded is not None:
            detail = task_detail(loaded)
            self.assertEqual(detail.status, TaskStatus.PENDING)
            self.assertEqual(detail.source.type, "text")
            self.assertIsNotNone(detail.source_metadata)
            if detail.source_metadata is not None:
                self.assertEqual(detail.source_metadata.size_bytes, 5)
                self.assertEqual(detail.source_metadata.media_category, "text")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "task.created")

    async def test_idempotent_create_returns_same_task(self) -> None:
        async with self.database.session_factory() as session:
            first, first_created = await self.repository.create(
                session,
                request=task_request(),
                idempotency_key="submission-123",
                now=NOW,
            )
            await session.commit()

        async with self.database.session_factory() as session:
            second, second_created = await self.repository.create(
                session,
                request=task_request(),
                idempotency_key="submission-123",
                now=NOW + timedelta(seconds=1),
            )

        self.assertTrue(first_created)
        self.assertFalse(second_created)
        self.assertEqual(first.task_id, second.task_id)

    async def test_idempotency_key_rejects_different_request(self) -> None:
        async with self.database.session_factory() as session:
            await self.repository.create(
                session,
                request=task_request("first"),
                idempotency_key="submission-123",
                now=NOW,
            )
            await session.commit()

        async with self.database.session_factory() as session:
            with self.assertRaises(IdempotencyConflictError):
                await self.repository.create(
                    session,
                    request=task_request("different"),
                    idempotency_key="submission-123",
                    now=NOW,
                )

    async def test_explicit_unknown_pipeline_is_rejected(self) -> None:
        request = CreateTaskRequest.model_validate(
            {
                "source": {"type": "text", "text": "hello"},
                "options": {
                    "pipeline_id": "pipeline_abcdefgh",
                    "pipeline_version": 1,
                },
            }
        )
        async with self.database.session_factory() as session:
            with self.assertRaises(PipelineNotFoundError):
                await self.repository.create(
                    session,
                    request=request,
                    idempotency_key=None,
                    now=NOW,
                )

    async def test_cancel_and_retry_write_status_events(self) -> None:
        async with self.database.session_factory() as session:
            record, _ = await self.repository.create(
                session,
                request=task_request(),
                idempotency_key=None,
                now=NOW,
            )
            await session.commit()

        async with self.database.session_factory() as session:
            cancelled = await self.repository.cancel(
                session,
                task_id=record.task_id,
                now=NOW + timedelta(seconds=1),
            )
            await session.commit()

        self.assertIsNotNone(cancelled)
        if cancelled is not None:
            self.assertEqual(cancelled.status, TaskStatus.CANCELLED)

        async with self.database.session_factory() as session:
            with self.assertRaises(TaskNotCancellableError):
                await self.repository.cancel(
                    session,
                    task_id=record.task_id,
                    now=NOW + timedelta(seconds=2),
                )

        async with self.database.session_factory() as session:
            retried = await self.repository.retry(
                session,
                task_id=record.task_id,
                now=NOW + timedelta(seconds=3),
            )
            await session.commit()

        self.assertIsNotNone(retried)
        if retried is not None:
            self.assertEqual(retried.status, TaskStatus.PENDING)
            self.assertIsNone(retried.completed_at)

        async with self.database.session_factory() as session:
            events = list(
                await session.scalars(
                    select(EventRecord).order_by(EventRecord.occurred_at)
                )
            )
        self.assertEqual(
            [event.event_type for event in events],
            [
                "task.created",
                "task.status_changed",
                "task.status_changed",
            ],
        )

    async def test_list_filters_by_status_and_media_category(self) -> None:
        async with self.database.session_factory() as session:
            await self.repository.create(
                session,
                request=task_request("first"),
                idempotency_key=None,
                now=NOW,
            )
            await self.repository.create(
                session,
                request=task_request("second"),
                idempotency_key=None,
                now=NOW + timedelta(seconds=1),
            )
            await session.commit()

        query = TaskListQuery(
            statuses=[TaskStatus.PENDING],
            media_category=MediaCategory.TEXT,
            limit=1,
        )
        async with self.database.session_factory() as session:
            records = await self.repository.list(session, query=query)

        self.assertEqual(len(records), 2)
        self.assertGreater(records[0].created_at, records[1].created_at)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest
from datetime import UTC, datetime

from parser_serve.persistence import Database, DatabaseEventBus
from parser_serve.persistence.events import event_envelope
from parser_serve.schema.event import (
    EventListQuery,
    TaskCreatedEvent,
    WorkerStatusChangedEvent,
)
from parser_serve.schema.worker import WorkerStatus


NOW = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)


class DatabaseEventBusTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.database = Database("sqlite+aiosqlite:///:memory:")
        await self.database.create_schema_for_testing()
        event_ids = iter(("event_taskcreated1", "event_workerchange1"))
        self.bus = DatabaseEventBus(event_id_factory=lambda: next(event_ids))

    async def asyncTearDown(self) -> None:
        await self.database.dispose()

    async def test_publish_and_consume_infer_typed_ownership(self) -> None:
        async with self.database.session_factory() as session:
            task_record = self.bus.publish(
                session,
                payload=TaskCreatedEvent(
                    type="task.created",
                    task_id="task_eventbus123",
                ),
                now=NOW,
            )
            worker_record = self.bus.publish(
                session,
                payload=WorkerStatusChangedEvent(
                    type="worker.status_changed",
                    worker_id="worker_eventbus1",
                    previous_status=None,
                    current_status=WorkerStatus.ONLINE,
                ),
                now=NOW,
            )
            await session.commit()

        self.assertEqual(task_record.task_id, "task_eventbus123")
        self.assertIsNone(task_record.worker_id)
        self.assertEqual(worker_record.worker_id, "worker_eventbus1")
        async with self.database.session_factory() as session:
            records = await self.bus.consume(
                session,
                query=EventListQuery(limit=10),
            )

        self.assertEqual(
            [record.event_id for record in records],
            ["event_taskcreated1", "event_workerchange1"],
        )
        self.assertEqual(event_envelope(records[0]).payload.type, "task.created")

    async def test_publish_participates_in_caller_transaction(self) -> None:
        async with self.database.session_factory() as session:
            self.bus.publish(
                session,
                payload=TaskCreatedEvent(
                    type="task.created",
                    task_id="task_eventbus456",
                ),
                now=NOW,
            )
            await session.rollback()

        async with self.database.session_factory() as session:
            records = await self.bus.consume(
                session,
                query=EventListQuery(limit=10),
            )

        self.assertEqual(records, [])


if __name__ == "__main__":
    unittest.main()

"""Background retry loop for pending tasks that could not yet be routed."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from ..persistence import Database
from ..persistence.models import TaskRecord
from ..queue import DatabasePollingTaskQueue, TaskQueueNotifier
from ..schema.queue import QueueNoticeReason
from ..schema.task import TaskStatus
from .router import (
    TaskAlreadyRoutedError,
    TaskRouter,
    TaskRoutingUnavailableError,
    TaskSourceUnresolvedError,
)


class TaskRoutingService:
    def __init__(
        self,
        *,
        database: Database,
        router: TaskRouter,
        queue_notifier: TaskQueueNotifier | None = None,
        batch_size: int = 100,
    ) -> None:
        if batch_size < 1:
            raise ValueError("routing batch_size must be greater than zero")
        self.database = database
        self.router = router
        self.queue_notifier = queue_notifier or TaskQueueNotifier(
            DatabasePollingTaskQueue()
        )
        self.batch_size = batch_size
        self.logger = logging.getLogger("parser_serve.routing")

    async def run_once(self, *, now: datetime | None = None) -> int:
        current = now or datetime.now(UTC)
        async with self.database.session_factory() as session:
            task_ids = list(
                await session.scalars(
                    select(TaskRecord.task_id)
                    .where(
                        TaskRecord.status == TaskStatus.PENDING.value,
                        TaskRecord.source_metadata_payload.is_not(None),
                        ~TaskRecord.stages.any(),
                    )
                    .order_by(TaskRecord.created_at, TaskRecord.task_id)
                    .limit(self.batch_size)
                )
            )

        routed = 0
        for task_id in task_ids:
            async with self.database.session_factory() as session:
                try:
                    record = await self.router.route(
                        session,
                        task_id=task_id,
                        now=current,
                    )
                except (
                    TaskAlreadyRoutedError,
                    TaskRoutingUnavailableError,
                    TaskSourceUnresolvedError,
                ):
                    await session.rollback()
                    continue
                if record is not None and record.stages:
                    routed += 1
                await session.commit()
                if record is not None and record.stages:
                    await self.queue_notifier.publish(
                        reason=QueueNoticeReason.TASK_ROUTED,
                        task_id=record.task_id,
                        occurred_at=current,
                    )
        return routed

    async def run(
        self,
        *,
        poll_interval_seconds: float,
        stop: asyncio.Event,
    ) -> None:
        if poll_interval_seconds <= 0:
            raise ValueError("routing poll interval must be greater than zero")
        while not stop.is_set():
            try:
                await self.run_once()
            except SQLAlchemyError:
                self.logger.exception("pending task routing pass failed")
            try:
                await asyncio.wait_for(
                    stop.wait(),
                    timeout=poll_interval_seconds,
                )
            except TimeoutError:
                pass


__all__ = ["TaskRoutingService"]

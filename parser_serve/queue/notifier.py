"""Best-effort queue notification service."""

from __future__ import annotations

import logging
from datetime import datetime
from uuid import uuid4

from ..schema.queue import QueueNoticeReason, StageQueueNotice
from .base import TaskQueue, TaskQueueUnavailableError


class TaskQueueNotifier:
    def __init__(
        self,
        queue: TaskQueue,
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        self.queue = queue
        self.logger = logger or logging.getLogger("parser_serve.queue")

    async def publish(
        self,
        *,
        reason: QueueNoticeReason,
        occurred_at: datetime,
        task_id: str | None = None,
        stage_id: str | None = None,
    ) -> bool:
        notice = StageQueueNotice(
            notice_id=f"notice_{uuid4().hex}",
            reason=reason,
            task_id=task_id,
            stage_id=stage_id,
            occurred_at=occurred_at,
        )
        try:
            await self.queue.publish(notice)
        except TaskQueueUnavailableError:
            self.logger.warning(
                "Stage availability notification could not be published",
                extra={
                    "notice_id": notice.notice_id,
                    "reason": notice.reason.value,
                },
            )
            return False
        return True


__all__ = ["TaskQueueNotifier"]

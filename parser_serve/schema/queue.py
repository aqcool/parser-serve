"""Typed contracts for distributed Stage availability notifications."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import model_validator

from .base import StrictSchema
from .common import QueueNoticeId, StageId, TaskId, UTCDateTime


class QueueNoticeReason(StrEnum):
    TASK_ROUTED = "task_routed"
    TASK_RETRIED = "task_retried"
    STAGE_COMPLETED = "stage_completed"
    LEASE_REQUEUED = "lease_requeued"


class StageQueueNotice(StrictSchema):
    schema_version: Literal["1.0"] = "1.0"
    notice_id: QueueNoticeId
    reason: QueueNoticeReason
    task_id: TaskId | None = None
    stage_id: StageId | None = None
    occurred_at: UTCDateTime

    @model_validator(mode="after")
    def validate_target(self) -> StageQueueNotice:
        if (
            self.reason
            in {
                QueueNoticeReason.TASK_ROUTED,
                QueueNoticeReason.TASK_RETRIED,
            }
            and self.task_id is None
        ):
            raise ValueError(f"{self.reason.value} notices require task_id")
        if self.reason is QueueNoticeReason.STAGE_COMPLETED and self.stage_id is None:
            raise ValueError("stage_completed notices require stage_id")
        return self


__all__ = ["QueueNoticeReason", "StageQueueNotice"]

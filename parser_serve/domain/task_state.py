"""Authoritative Task and Stage state-transition rules."""

from __future__ import annotations

from ..schema.stage import StageStatus
from ..schema.task import TaskStatus


TASK_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.PENDING: frozenset({TaskStatus.LEASED, TaskStatus.CANCELLED}),
    TaskStatus.LEASED: frozenset(
        {
            TaskStatus.PENDING,
            TaskStatus.RUNNING,
            TaskStatus.SUCCEEDED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        }
    ),
    TaskStatus.RUNNING: frozenset(
        {
            TaskStatus.SUCCEEDED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        }
    ),
    TaskStatus.SUCCEEDED: frozenset(),
    TaskStatus.FAILED: frozenset({TaskStatus.PENDING}),
    TaskStatus.CANCELLED: frozenset({TaskStatus.PENDING}),
}

STAGE_TRANSITIONS: dict[StageStatus, frozenset[StageStatus]] = {
    StageStatus.PENDING: frozenset(
        {
            StageStatus.LEASED,
            StageStatus.CANCELLED,
            StageStatus.SKIPPED,
        }
    ),
    StageStatus.LEASED: frozenset(
        {
            StageStatus.PENDING,
            StageStatus.RUNNING,
            StageStatus.FAILED,
            StageStatus.CANCELLED,
        }
    ),
    StageStatus.RUNNING: frozenset(
        {
            StageStatus.SUCCEEDED,
            StageStatus.FAILED,
            StageStatus.CANCELLED,
        }
    ),
    StageStatus.SUCCEEDED: frozenset(),
    StageStatus.FAILED: frozenset(
        {
            StageStatus.PENDING,
            StageStatus.SKIPPED,
        }
    ),
    StageStatus.CANCELLED: frozenset({StageStatus.PENDING}),
    StageStatus.SKIPPED: frozenset(),
}


class InvalidTaskTransitionError(ValueError):
    def __init__(self, current: TaskStatus, target: TaskStatus) -> None:
        super().__init__(f"task cannot transition from {current} to {target}")
        self.current = current
        self.target = target


class InvalidStageTransitionError(ValueError):
    def __init__(self, current: StageStatus, target: StageStatus) -> None:
        super().__init__(f"stage cannot transition from {current} to {target}")
        self.current = current
        self.target = target


def can_transition_task(current: TaskStatus, target: TaskStatus) -> bool:
    return target in TASK_TRANSITIONS[current]


def require_task_transition(current: TaskStatus, target: TaskStatus) -> None:
    if not can_transition_task(current, target):
        raise InvalidTaskTransitionError(current, target)


def can_transition_stage(current: StageStatus, target: StageStatus) -> bool:
    return target in STAGE_TRANSITIONS[current]


def require_stage_transition(current: StageStatus, target: StageStatus) -> None:
    if not can_transition_stage(current, target):
        raise InvalidStageTransitionError(current, target)


__all__ = [
    "STAGE_TRANSITIONS",
    "TASK_TRANSITIONS",
    "InvalidStageTransitionError",
    "InvalidTaskTransitionError",
    "can_transition_stage",
    "can_transition_task",
    "require_stage_transition",
    "require_task_transition",
]

from __future__ import annotations

import unittest

from parser_serve.domain.task_state import (
    InvalidStageTransitionError,
    InvalidTaskTransitionError,
    can_transition_stage,
    can_transition_task,
    require_stage_transition,
    require_task_transition,
)
from parser_serve.schema.stage import StageStatus
from parser_serve.schema.task import TaskStatus


class TaskStateMachineTests(unittest.TestCase):
    def test_happy_path(self) -> None:
        self.assertTrue(can_transition_task(TaskStatus.PENDING, TaskStatus.LEASED))
        self.assertTrue(can_transition_task(TaskStatus.LEASED, TaskStatus.RUNNING))
        self.assertTrue(can_transition_task(TaskStatus.RUNNING, TaskStatus.SUCCEEDED))

    def test_lease_can_return_to_pending(self) -> None:
        require_task_transition(TaskStatus.LEASED, TaskStatus.PENDING)

    def test_failed_and_cancelled_tasks_can_be_retried(self) -> None:
        require_task_transition(TaskStatus.FAILED, TaskStatus.PENDING)
        require_task_transition(TaskStatus.CANCELLED, TaskStatus.PENDING)

    def test_succeeded_task_is_terminal(self) -> None:
        with self.assertRaises(InvalidTaskTransitionError):
            require_task_transition(TaskStatus.SUCCEEDED, TaskStatus.PENDING)

    def test_task_cannot_skip_running_state(self) -> None:
        with self.assertRaises(InvalidTaskTransitionError):
            require_task_transition(TaskStatus.PENDING, TaskStatus.SUCCEEDED)


class StageStateMachineTests(unittest.TestCase):
    def test_happy_path(self) -> None:
        require_stage_transition(StageStatus.PENDING, StageStatus.LEASED)
        require_stage_transition(StageStatus.LEASED, StageStatus.RUNNING)
        require_stage_transition(StageStatus.RUNNING, StageStatus.SUCCEEDED)

    def test_failed_stage_can_retry(self) -> None:
        require_stage_transition(StageStatus.FAILED, StageStatus.PENDING)

    def test_pending_stage_can_be_skipped(self) -> None:
        self.assertTrue(can_transition_stage(StageStatus.PENDING, StageStatus.SKIPPED))

    def test_succeeded_and_skipped_stages_are_terminal(self) -> None:
        for current in (StageStatus.SUCCEEDED, StageStatus.SKIPPED):
            with self.assertRaises(InvalidStageTransitionError):
                require_stage_transition(current, StageStatus.PENDING)


if __name__ == "__main__":
    unittest.main()

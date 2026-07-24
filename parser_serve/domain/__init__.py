"""Domain rules shared by HTTP, MCP, workers, and background controllers."""

from .task_state import (
    InvalidStageTransitionError,
    InvalidTaskTransitionError,
    can_transition_stage,
    can_transition_task,
    require_stage_transition,
    require_task_transition,
)

__all__ = [
    "InvalidStageTransitionError",
    "InvalidTaskTransitionError",
    "can_transition_stage",
    "can_transition_task",
    "require_stage_transition",
    "require_task_transition",
]

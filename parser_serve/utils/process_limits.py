"""Portable construction of resource-limited Linux subprocess commands."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


class ProcessResourceLimitError(RuntimeError):
    """Raised when required subprocess resource enforcement is unavailable."""


@dataclass(frozen=True, slots=True)
class ProcessResourceLimits:
    maximum_memory_bytes: int
    maximum_cpu_seconds: int
    maximum_output_file_bytes: int
    maximum_processes: int
    required: bool = False

    def __post_init__(self) -> None:
        for name in (
            "maximum_memory_bytes",
            "maximum_cpu_seconds",
            "maximum_output_file_bytes",
            "maximum_processes",
        ):
            if getattr(self, name) < 1:
                raise ValueError(f"{name} must be greater than zero")

    def command(
        self,
        command: Sequence[str | Path],
        *,
        executable: str | Path | None = None,
    ) -> list[str]:
        arguments = [str(argument) for argument in command]
        if not arguments:
            raise ValueError("command cannot be empty")
        limiter = str(executable) if executable is not None else shutil.which("prlimit")
        if limiter is None:
            if self.required:
                raise ProcessResourceLimitError(
                    "prlimit is required to enforce subprocess resource limits"
                )
            return arguments
        return [
            limiter,
            f"--as={self.maximum_memory_bytes}",
            f"--cpu={self.maximum_cpu_seconds}",
            f"--fsize={self.maximum_output_file_bytes}",
            f"--nproc={self.maximum_processes}",
            "--",
            *arguments,
        ]


__all__ = ["ProcessResourceLimitError", "ProcessResourceLimits"]

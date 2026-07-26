"""Backend execution contracts shared by local parser implementations."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePath
from typing import Protocol, runtime_checkable

from ..schema.artifact import ArtifactType
from ..schema.backend import BackendCapability, BackendLoadTarget
from ..schema.base import JsonValue
from ..schema.worker import LeasedStage


ProgressReporter = Callable[[float], Awaitable[None]]


class BackendExecutionError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class BackendContext:
    lease: LeasedStage
    work_dir: Path
    source_path: Path | None
    source_text: str | None
    report_progress: ProgressReporter


@dataclass(frozen=True, slots=True)
class ProducedArtifact:
    type: ArtifactType
    filename: str
    mime_type: str
    data: bytes | None = None
    path: Path | None = None
    metadata: dict[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if (self.data is None) == (self.path is None):
            raise ValueError("exactly one of data or path must be provided")
        if PurePath(self.filename).name != self.filename or not self.filename:
            raise ValueError("artifact filename must be a plain filename")
        if self.path is not None and not self.path.is_file():
            raise FileNotFoundError(self.path)


@dataclass(frozen=True, slots=True)
class BackendOutput:
    artifacts: tuple[ProducedArtifact, ...]
    primary_artifact_index: int = 0

    def __post_init__(self) -> None:
        if not self.artifacts:
            raise ValueError("a Backend must produce at least one Artifact")
        if not 0 <= self.primary_artifact_index < len(self.artifacts):
            raise ValueError("primary_artifact_index is out of range")


class Backend(Protocol):
    @property
    def capability(self) -> BackendCapability: ...

    async def execute(self, context: BackendContext) -> BackendOutput: ...


@runtime_checkable
class ManagedBackend(Protocol):
    """Optional lifecycle implemented by local model Backends."""

    @property
    def capability(self) -> BackendCapability: ...

    async def execute(self, context: BackendContext) -> BackendOutput: ...

    async def load(self) -> None: ...

    async def unload(self) -> None: ...


class BackendRegistry:
    def __init__(self) -> None:
        self._backends: dict[tuple[str, str], Backend] = {}
        self._loaded: list[tuple[str, str]] = []
        self._lifecycle_lock = asyncio.Lock()

    def register(self, backend: Backend) -> None:
        key = (backend.capability.name, backend.capability.version)
        if key in self._backends:
            raise ValueError(
                f"Backend {backend.capability.name!r} version "
                f"{backend.capability.version!r} is already registered"
            )
        self._backends[key] = backend

    def get(self, name: str, version: str) -> Backend:
        try:
            return self._backends[(name, version)]
        except KeyError as exc:
            raise BackendExecutionError(
                f"Backend {name!r} version {version!r} is not installed"
            ) from exc

    async def preload(self, targets: Sequence[BackendLoadTarget]) -> None:
        """Load selected model Backends once, rolling back this batch on failure."""

        async with self._lifecycle_lock:
            loaded_now: list[tuple[str, str]] = []
            try:
                for target in targets:
                    key = (target.name, target.version)
                    if key in self._loaded:
                        continue
                    backend = self.get(*key)
                    if not isinstance(backend, ManagedBackend):
                        raise BackendExecutionError(
                            f"Backend {target.name!r} version "
                            f"{target.version!r} does not support model preloading"
                        )
                    await backend.load()
                    self._loaded.append(key)
                    loaded_now.append(key)
            except BaseException as exc:

                async def rollback() -> None:
                    for key in reversed(loaded_now):
                        backend = self._backends[key]
                        assert isinstance(backend, ManagedBackend)
                        with contextlib.suppress(Exception):
                            await backend.unload()
                        self._loaded.remove(key)

                rollback_task = asyncio.create_task(rollback())
                try:
                    await asyncio.shield(rollback_task)
                except asyncio.CancelledError:
                    # A second cancellation must not leave a partially loaded batch.
                    await rollback_task
                    raise
                if isinstance(exc, asyncio.CancelledError):
                    raise
                if not isinstance(exc, Exception):
                    raise
                if isinstance(exc, BackendExecutionError):
                    raise
                raise BackendExecutionError(
                    f"Backend model preload failed: {type(exc).__name__}",
                    retryable=False,
                ) from exc

    async def unload_all(self) -> None:
        """Unload every model loaded by :meth:`preload`, in reverse order."""

        async with self._lifecycle_lock:
            failures: list[str] = []
            for key in reversed(tuple(self._loaded)):
                backend = self._backends[key]
                assert isinstance(backend, ManagedBackend)
                try:
                    await backend.unload()
                except Exception:
                    failures.append(f"{key[0]}@{key[1]}")
                else:
                    self._loaded.remove(key)
            if failures:
                raise BackendExecutionError(
                    "Backend model unload failed for " + ", ".join(failures)
                )

    @property
    def loaded_backends(self) -> tuple[BackendLoadTarget, ...]:
        return tuple(
            BackendLoadTarget(name=name, version=version)
            for name, version in self._loaded
        )

    @property
    def capabilities(self) -> tuple[BackendCapability, ...]:
        return tuple(
            backend.capability for _, backend in sorted(self._backends.items())
        )


__all__ = [
    "Backend",
    "BackendContext",
    "BackendExecutionError",
    "BackendOutput",
    "BackendRegistry",
    "ManagedBackend",
    "ProducedArtifact",
    "ProgressReporter",
]

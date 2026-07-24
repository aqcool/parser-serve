"""Source preparation tools that run before parser Backends."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Protocol

from ..backends import BackendExecutionError
from ..utils.libreoffice import (
    LEGACY_OFFICE_FORMATS,
    LibreOfficeConversionError,
    convert_legacy_office,
)
from ..utils.process_limits import ProcessResourceLimits


class SourcePreprocessor(Protocol):
    def applies_to(self, source: Path) -> bool: ...

    async def prepare(
        self,
        source: Path,
        *,
        work_dir: Path,
        timeout_seconds: int,
    ) -> Path: ...


class LegacyOfficePreprocessor:
    def __init__(
        self,
        *,
        resource_limits: ProcessResourceLimits | None = None,
    ) -> None:
        self.resource_limits = resource_limits

    def applies_to(self, source: Path) -> bool:
        return source.suffix.casefold() in LEGACY_OFFICE_FORMATS

    async def prepare(
        self,
        source: Path,
        *,
        work_dir: Path,
        timeout_seconds: int,
    ) -> Path:
        try:
            return await asyncio.to_thread(
                convert_legacy_office,
                source,
                output_dir=work_dir / "libreoffice",
                timeout=float(timeout_seconds),
                resource_limits=self.resource_limits,
            )
        except LibreOfficeConversionError as exc:
            raise BackendExecutionError(str(exc), retryable=True) from exc


def builtin_preprocessors(
    *,
    resource_limits: ProcessResourceLimits | None = None,
) -> tuple[SourcePreprocessor, ...]:
    return (LegacyOfficePreprocessor(resource_limits=resource_limits),)


__all__ = [
    "LegacyOfficePreprocessor",
    "SourcePreprocessor",
    "builtin_preprocessors",
]

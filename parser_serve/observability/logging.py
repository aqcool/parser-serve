"""Structured logging with request and execution correlation context."""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from contextvars import ContextVar, Token
from datetime import UTC, datetime
from typing import Iterator


_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
_task_id: ContextVar[str | None] = ContextVar("task_id", default=None)
_stage_id: ContextVar[str | None] = ContextVar("stage_id", default=None)
_worker_id: ContextVar[str | None] = ContextVar("worker_id", default=None)

_FIELDS = {
    "request_id": _request_id,
    "task_id": _task_id,
    "stage_id": _stage_id,
    "worker_id": _worker_id,
}


def correlation_context() -> dict[str, str]:
    return {
        name: value
        for name, variable in _FIELDS.items()
        if (value := variable.get()) is not None
    }


@contextmanager
def log_context(**values: str | None) -> Iterator[None]:
    tokens: list[tuple[ContextVar[str | None], Token[str | None]]] = []
    try:
        for name, value in values.items():
            variable = _FIELDS.get(name)
            if variable is not None and value is not None:
                tokens.append((variable, variable.set(value)))
        yield
    finally:
        for variable, token in reversed(tokens):
            variable.reset(token)


class CorrelationFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        for name, value in correlation_context().items():
            if not hasattr(record, name):
                setattr(record, name, value)
        return True


class JsonLogFormatter(logging.Formatter):
    _reserved = set(logging.makeLogRecord({}).__dict__) | {
        "message",
        "asctime",
    }

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        for name in _FIELDS:
            value = getattr(record, name, None)
            if isinstance(value, str):
                payload[name] = value
        for name in (
            "method",
            "path",
            "route",
            "status_code",
            "duration_ms",
            "notice_id",
            "reason",
        ):
            value = getattr(record, name, None)
            if isinstance(value, str | int | float | bool):
                payload[name] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def configure_logging(
    *,
    level: str = "INFO",
    json_output: bool = True,
) -> None:
    handler = logging.StreamHandler()
    handler.addFilter(CorrelationFilter())
    handler.setFormatter(
        JsonLogFormatter()
        if json_output
        else logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())


__all__ = [
    "CorrelationFilter",
    "JsonLogFormatter",
    "configure_logging",
    "correlation_context",
    "log_context",
]

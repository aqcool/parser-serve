"""Optional OpenTelemetry setup and W3C context persistence helpers."""

from __future__ import annotations

import contextlib
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from importlib import import_module
from typing import Any

from pydantic import ValidationError

from ..schema.trace import TraceContext


@dataclass(slots=True)
class TracingRuntime:
    provider: Any
    httpx_instrumentor: Any
    fastapi_instrumentor: Any | None = None
    app: Any | None = None

    def instrument_fastapi(self, app: Any) -> None:
        instrumentor = import_module(
            "opentelemetry.instrumentation.fastapi"
        ).FastAPIInstrumentor
        instrumentor.instrument_app(app, tracer_provider=self.provider)
        self.fastapi_instrumentor = instrumentor
        self.app = app

    def shutdown(self) -> None:
        if self.fastapi_instrumentor is not None and self.app is not None:
            self.fastapi_instrumentor.uninstrument_app(self.app)
        if self.httpx_instrumentor.is_instrumented_by_opentelemetry:
            self.httpx_instrumentor.uninstrument()
        self.provider.shutdown()


def configure_tracing(
    *,
    service_name: str,
    endpoint: str,
    sample_ratio: float,
    span_exporter: Any | None = None,
) -> TracingRuntime:
    """Configure OTLP/HTTP tracing and global HTTPX propagation."""

    try:
        trace = import_module("opentelemetry.trace")
        resources = import_module("opentelemetry.sdk.resources")
        sdk_trace = import_module("opentelemetry.sdk.trace")
        sampling = import_module("opentelemetry.sdk.trace.sampling")
        exporting = import_module("opentelemetry.sdk.trace.export")
        httpx_instrumentation = import_module("opentelemetry.instrumentation.httpx")
    except ImportError as exc:
        raise RuntimeError(
            "OpenTelemetry is enabled but the telemetry dependency profile "
            "is not installed"
        ) from exc
    resource = resources.Resource.create({resources.SERVICE_NAME: service_name})
    provider = sdk_trace.TracerProvider(
        resource=resource,
        sampler=sampling.ParentBased(sampling.TraceIdRatioBased(sample_ratio)),
    )
    exporter = span_exporter
    if exporter is None:
        otlp = import_module("opentelemetry.exporter.otlp.proto.http.trace_exporter")
        exporter = otlp.OTLPSpanExporter(endpoint=endpoint)
    provider.add_span_processor(exporting.BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    instrumentor = httpx_instrumentation.HTTPXClientInstrumentor()
    if not instrumentor.is_instrumented_by_opentelemetry:
        instrumentor.instrument(tracer_provider=provider)
    return TracingRuntime(
        provider=provider,
        httpx_instrumentor=instrumentor,
    )


def capture_trace_context() -> TraceContext | None:
    """Serialize the current OpenTelemetry context for durable queue storage."""

    try:
        propagation = import_module("opentelemetry.propagate")
    except ImportError:
        return None
    carrier: dict[str, str] = {}
    propagation.inject(carrier)
    traceparent = carrier.get("traceparent")
    if traceparent is None:
        return None
    try:
        return TraceContext(
            traceparent=traceparent,
            tracestate=carrier.get("tracestate"),
        )
    except ValidationError:
        return None


@contextlib.contextmanager
def trace_span(
    name: str,
    *,
    parent: TraceContext | None = None,
    attributes: Mapping[str, str | int | float | bool] | None = None,
) -> Iterator[Any | None]:
    """Start a span from persisted W3C context, or become a no-op."""

    try:
        trace = import_module("opentelemetry.trace")
        propagation = import_module("opentelemetry.propagate")
    except ImportError:
        yield None
        return
    context = (
        propagation.extract(carrier=parent.model_dump(exclude_none=True))
        if parent is not None
        else None
    )
    tracer = trace.get_tracer("parser_serve")
    with tracer.start_as_current_span(
        name,
        context=context,
        attributes=dict(attributes or {}),
    ) as span:
        yield span


__all__ = [
    "TracingRuntime",
    "capture_trace_context",
    "configure_tracing",
    "trace_span",
]

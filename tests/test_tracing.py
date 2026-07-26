from __future__ import annotations

import unittest

from opentelemetry import trace
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from pydantic import SecretStr, ValidationError

from parser_serve.observability import (
    capture_trace_context,
    configure_tracing,
    trace_span,
)
from parser_serve.schema.trace import TraceContext
from parser_serve.settings import Settings
from parser_serve.worker.config import WorkerSettings


class TraceContextTests(unittest.TestCase):
    def test_w3c_context_rejects_malformed_and_zero_identifiers(self) -> None:
        for value in (
            "not-a-traceparent",
            f"00-{'0' * 32}-00f067aa0ba902b7-01",
            f"00-4bf92f3577b34da6a3ce929d0e0e4736-{'0' * 16}-01",
        ):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                TraceContext(traceparent=value)

    def test_enabled_settings_require_an_exporter_endpoint(self) -> None:
        with self.assertRaisesRegex(ValidationError, "otel_exporter_endpoint"):
            Settings(otel_enabled=True)
        with self.assertRaisesRegex(ValidationError, "otel_exporter_endpoint"):
            WorkerSettings(
                api_key=SecretStr(f"parser_{'o' * 32}"),
                worker_id="worker_tracing12",
                otel_enabled=True,
            )


class OpenTelemetryIntegrationTests(unittest.TestCase):
    def test_persisted_context_links_api_stage_and_callback_spans(self) -> None:
        exporter = InMemorySpanExporter()
        runtime = configure_tracing(
            service_name="parser-serve-test",
            endpoint="http://collector.invalid/v1/traces",
            sample_ratio=1.0,
            span_exporter=exporter,
        )
        try:
            tracer = trace.get_tracer("parser-serve-test")
            with tracer.start_as_current_span("parser.api.create_task"):
                persisted = capture_trace_context()
            self.assertIsNotNone(persisted)
            assert persisted is not None

            with trace_span(
                "parser.stage.execute",
                parent=persisted,
                attributes={"parser.stage.id": "stage_trace123"},
            ):
                stage_context = capture_trace_context()
            with trace_span("parser.callback.deliver", parent=persisted):
                callback_context = capture_trace_context()

            self.assertIsNotNone(stage_context)
            self.assertIsNotNone(callback_context)
            runtime.provider.force_flush()
            spans = {span.name: span for span in exporter.get_finished_spans()}
            root = spans["parser.api.create_task"]
            stage = spans["parser.stage.execute"]
            callback = spans["parser.callback.deliver"]
            root_context = root.context
            stage_context = stage.context
            callback_context = callback.context
            stage_parent = stage.parent
            callback_parent = callback.parent
            attributes = stage.attributes
            assert root_context is not None
            assert stage_context is not None
            assert callback_context is not None
            assert stage_parent is not None
            assert callback_parent is not None
            assert attributes is not None
            self.assertEqual(stage_context.trace_id, root_context.trace_id)
            self.assertEqual(callback_context.trace_id, root_context.trace_id)
            self.assertEqual(stage_parent.span_id, root_context.span_id)
            self.assertEqual(callback_parent.span_id, root_context.span_id)
            self.assertEqual(
                attributes["parser.stage.id"],
                "stage_trace123",
            )
        finally:
            runtime.shutdown()


if __name__ == "__main__":
    unittest.main()

"""Command-line entrypoint for a configured hardware Worker."""

from __future__ import annotations

import asyncio
import signal

from ..observability import configure_logging, configure_tracing, log_context
from .backends import configured_backend_registry
from .client import HttpWorkerControlClient
from .config import WorkerSettings
from .service import WorkerService


async def _run(settings: WorkerSettings) -> None:
    backends = configured_backend_registry(settings)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signal_number in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signal_number, stop.set)
        except NotImplementedError:
            pass
    with log_context(worker_id=settings.worker_id):
        async with HttpWorkerControlClient(
            base_url=str(settings.control_plane_url),
            api_key=settings.api_key.get_secret_value(),
            timeout_seconds=settings.request_timeout_seconds,
        ) as client:
            await WorkerService(
                settings=settings,
                client=client,
                backends=backends,
            ).run(stop=stop)


def main() -> None:
    settings = WorkerSettings.model_validate({})
    configure_logging(
        level=settings.log_level,
        json_output=settings.log_format.value == "json",
    )
    tracing_runtime = (
        configure_tracing(
            service_name=settings.otel_service_name,
            endpoint=str(settings.otel_exporter_endpoint),
            sample_ratio=settings.otel_sample_ratio,
        )
        if settings.otel_enabled and settings.otel_exporter_endpoint is not None
        else None
    )
    try:
        asyncio.run(_run(settings))
    finally:
        if tracing_runtime is not None:
            tracing_runtime.shutdown()


if __name__ == "__main__":
    main()

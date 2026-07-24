"""FastAPI application factory."""

from __future__ import annotations

import logging
import asyncio
import contextlib
from contextlib import AsyncExitStack, asynccontextmanager
from collections.abc import Callable
from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from ..persistence import (
    ArtifactRepository,
    CallbackRepository,
    Database,
    DatabaseEventBus,
    FileRepository,
    SystemSettingRepository,
)
from ..persistence.api_keys import ApiKeyRepository
from ..persistence.registry import BackendRepository, PipelineRepository
from ..persistence.tasks import TaskRepository
from ..persistence.workers import WorkerRepository
from ..observability import ParserMetrics, configure_tracing
from ..mcp import McpApiKeyMiddleware, ParserMcpService, create_mcp_server
from ..control import (
    CallbackDispatcher,
    DashboardService,
    HttpCallbackTransport,
    RetentionService,
    StageScheduler,
    TaskRouter,
    TaskRoutingService,
)
from ..control.callbacks import CallbackTransport
from ..schema.error import ErrorResponse
from ..queue import (
    DatabasePollingTaskQueue,
    RedisStreamsTaskQueue,
    TaskQueue,
    TaskQueueNotifier,
)
from ..settings import (
    Settings,
    StorageBackend,
    TaskQueueBackend,
    get_settings,
)
from ..storage import LocalFileStorage, S3Storage, Storage
from .authentication import ApiKeyAuthenticator
from .errors import (
    ApiError,
    api_error_handler,
    unhandled_error_handler,
    validation_error_handler,
)
from .request_id import RequestIdMiddleware
from .openapi import install_openapi_annotations
from .routes import (
    api_keys,
    callbacks,
    dashboard,
    events,
    files,
    health,
    maintenance,
    metrics,
    registry,
    settings as settings_routes,
    system,
    tasks,
    workers,
)


Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _configured_storage(settings: Settings) -> Storage:
    if settings.storage_backend is StorageBackend.S3:
        if settings.s3_storage_bucket is None:  # protected by Settings validation
            raise ValueError("s3_storage_bucket is required")
        return S3Storage(
            bucket=settings.s3_storage_bucket,
            prefix=settings.s3_storage_prefix,
            endpoint_url=(
                str(settings.s3_storage_endpoint_url)
                if settings.s3_storage_endpoint_url is not None
                else None
            ),
            region_name=settings.s3_storage_region_name,
        )
    return LocalFileStorage(settings.local_storage_path)


def _configured_task_queue(settings: Settings) -> TaskQueue:
    if settings.task_queue_backend is TaskQueueBackend.REDIS_STREAMS:
        return RedisStreamsTaskQueue(
            url=str(settings.redis_url),
            stream_key=settings.redis_stage_stream_key,
            maximum_length=settings.redis_stage_stream_maximum_length,
        )
    return DatabasePollingTaskQueue()


def create_app(
    settings: Settings | None = None,
    *,
    clock: Clock = _utc_now,
    database: Database | None = None,
    storage: Storage | None = None,
    task_queue: TaskQueue | None = None,
    callback_transport: CallbackTransport | None = None,
    dispose_database_on_shutdown: bool = False,
) -> FastAPI:
    resolved_settings = settings or get_settings()
    tracing_runtime = (
        configure_tracing(
            service_name=resolved_settings.otel_service_name,
            endpoint=str(resolved_settings.otel_exporter_endpoint),
            sample_ratio=resolved_settings.otel_sample_ratio,
        )
        if resolved_settings.otel_enabled
        and resolved_settings.otel_exporter_endpoint is not None
        else None
    )
    resolved_storage = storage or _configured_storage(resolved_settings)
    resolved_task_queue = task_queue or _configured_task_queue(resolved_settings)
    owns_task_queue = task_queue is None
    api_key_authenticator = ApiKeyAuthenticator(resolved_settings.api_keys)
    api_key_repository = ApiKeyRepository()
    event_bus = DatabaseEventBus()
    mcp_server = None
    mcp_http_app = None
    mcp_asgi_app = None
    if database is not None:
        mcp_server = create_mcp_server(
            ParserMcpService(
                database=database,
                storage=resolved_storage,
                settings=resolved_settings,
                clock=clock,
                events=event_bus,
            )
        )
        mcp_http_app = mcp_server.streamable_http_app()
        mcp_asgi_app = McpApiKeyMiddleware(
            mcp_http_app,
            authenticator=api_key_authenticator,
            database=database,
            repository=api_key_repository,
            clock=clock,
        )
    owns_callback_transport = callback_transport is None
    resolved_callback_transport = callback_transport or HttpCallbackTransport(
        timeout_seconds=resolved_settings.callback_timeout_seconds,
        maximum_response_bytes=(resolved_settings.callback_response_summary_bytes),
    )
    callback_repository = CallbackRepository(events=event_bus)
    system_setting_repository = SystemSettingRepository()
    callback_dispatcher = (
        CallbackDispatcher(
            database=database,
            repository=callback_repository,
            transport=resolved_callback_transport,
            maximum_attempts=resolved_settings.callback_maximum_attempts,
            initial_retry_seconds=(resolved_settings.callback_initial_retry_seconds),
            maximum_retry_seconds=(resolved_settings.callback_maximum_retry_seconds),
            claim_timeout_seconds=(resolved_settings.callback_claim_timeout_seconds),
            system_settings=system_setting_repository,
            deployment_settings=resolved_settings,
        )
        if database is not None
        else None
    )
    retention_service = (
        RetentionService(
            database=database,
            storage=resolved_storage,
            uploaded_file_retention_seconds=(
                resolved_settings.uploaded_file_retention_seconds
            ),
            artifact_retention_seconds=(resolved_settings.artifact_retention_seconds),
            event_retention_seconds=resolved_settings.event_retention_seconds,
            batch_size=resolved_settings.retention_cleanup_batch_size,
            clock=clock,
        )
        if database is not None
        else None
    )

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        stop = asyncio.Event()
        dispatcher_task: asyncio.Task[None] | None = None
        routing_task: asyncio.Task[None] | None = None
        retention_task: asyncio.Task[None] | None = None
        if (
            resolved_settings.callback_dispatcher_enabled
            and callback_dispatcher is not None
        ):
            dispatcher_task = asyncio.create_task(
                callback_dispatcher.run(
                    poll_interval_seconds=(
                        resolved_settings.callback_poll_interval_seconds
                    ),
                    stop=stop,
                )
            )
        if application.state.task_routing_service is not None:
            routing_task = asyncio.create_task(
                application.state.task_routing_service.run(
                    poll_interval_seconds=(
                        resolved_settings.routing_poll_interval_seconds
                    ),
                    stop=stop,
                )
            )
        if (
            resolved_settings.retention_cleanup_enabled
            and application.state.retention_service is not None
        ):
            retention_task = asyncio.create_task(
                application.state.retention_service.run(
                    interval_seconds=(
                        resolved_settings.retention_cleanup_interval_seconds
                    ),
                    stop=stop,
                )
            )
        try:
            async with AsyncExitStack() as stack:
                if mcp_http_app is not None:
                    await stack.enter_async_context(
                        mcp_http_app.router.lifespan_context(mcp_http_app)
                    )
                yield
        finally:
            stop.set()
            if dispatcher_task is not None:
                with contextlib.suppress(Exception):
                    await dispatcher_task
            if routing_task is not None:
                with contextlib.suppress(Exception):
                    await routing_task
            if retention_task is not None:
                with contextlib.suppress(Exception):
                    await retention_task
            if owns_callback_transport and isinstance(
                resolved_callback_transport,
                HttpCallbackTransport,
            ):
                await resolved_callback_transport.aclose()
            if owns_task_queue:
                await resolved_task_queue.aclose()
            if database is not None and dispose_database_on_shutdown:
                await database.dispose()
            if tracing_runtime is not None:
                tracing_runtime.shutdown()

    app = FastAPI(
        title=resolved_settings.app_name,
        version=resolved_settings.app_version,
        lifespan=lifespan,
        responses={
            401: {"model": ErrorResponse},
            422: {"model": ErrorResponse},
            503: {"model": ErrorResponse},
            500: {"model": ErrorResponse},
        },
    )
    app.state.settings = resolved_settings
    app.state.clock = clock
    app.state.logger = logging.getLogger("parser_serve.api")
    app.state.metrics = ParserMetrics()
    app.state.api_key_authenticator = api_key_authenticator
    app.state.worker_api_key_authenticator = ApiKeyAuthenticator(
        resolved_settings.worker_api_keys
    )
    app.state.database = database
    app.state.storage = resolved_storage
    app.state.task_queue = resolved_task_queue
    app.state.task_queue_notifier = TaskQueueNotifier(resolved_task_queue)
    app.state.api_key_repository = api_key_repository
    app.state.mcp_server = mcp_server
    app.state.file_repository = FileRepository()
    app.state.event_bus = event_bus
    app.state.event_repository = event_bus
    app.state.callback_repository = callback_repository
    app.state.callback_transport = resolved_callback_transport
    app.state.callback_dispatcher = callback_dispatcher
    app.state.retention_service = retention_service
    app.state.dashboard_service = DashboardService()
    app.state.artifact_repository = ArtifactRepository()
    app.state.task_repository = TaskRepository(events=event_bus)
    app.state.backend_repository = BackendRepository()
    app.state.pipeline_repository = PipelineRepository()
    app.state.system_setting_repository = system_setting_repository
    app.state.task_router = TaskRouter(
        pipelines=app.state.pipeline_repository,
        backends=app.state.backend_repository,
        events=event_bus,
    )
    app.state.task_routing_service = (
        TaskRoutingService(
            database=database,
            router=app.state.task_router,
            queue_notifier=app.state.task_queue_notifier,
            batch_size=resolved_settings.routing_batch_size,
        )
        if database is not None
        else None
    )
    app.state.worker_repository = WorkerRepository(events=event_bus)
    app.state.stage_scheduler = StageScheduler(
        lease_duration_seconds=resolved_settings.stage_lease_duration_seconds,
        maximum_device_memory_utilization_percent=(
            resolved_settings.scheduler_maximum_device_memory_utilization_percent
        ),
        events=event_bus,
    )

    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "Idempotency-Key",
            "Last-Event-ID",
            "X-API-Key",
            "X-Request-ID",
        ],
        expose_headers=[
            "Content-Disposition",
            "Content-Length",
            "X-Content-SHA256",
            "X-Request-ID",
        ],
    )
    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)

    app.include_router(health.router)
    if resolved_settings.metrics_enabled:
        app.include_router(metrics.router)
    app.include_router(system.router)
    app.include_router(api_keys.router)
    app.include_router(files.router)
    app.include_router(files.internal_router)
    app.include_router(events.router)
    app.include_router(callbacks.router)
    app.include_router(dashboard.router)
    app.include_router(maintenance.router)
    app.include_router(tasks.router)
    app.include_router(registry.router)
    app.include_router(settings_routes.router)
    app.include_router(workers.internal_router)
    app.include_router(workers.management_router)
    if mcp_asgi_app is not None:
        app.mount("/", mcp_asgi_app, name="mcp")
    install_openapi_annotations(app)
    if tracing_runtime is not None:
        tracing_runtime.instrument_fastapi(app)
    return app


__all__ = ["create_app"]

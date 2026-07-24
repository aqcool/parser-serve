"""Generated OpenAPI operation identifiers and routes. Do not edit."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal


OperationId = Literal[
    "cancel_task",
    "complete_stage",
    "create_api_key",
    "create_backend",
    "create_pipeline",
    "create_task",
    "create_task_artifact_download_url",
    "delete_api_key",
    "download_task_artifact",
    "download_task_result",
    "download_uploaded_file",
    "download_worker_source_file",
    "drain_worker_self",
    "get_api_key",
    "get_backend",
    "get_callback_delivery",
    "get_capabilities",
    "get_dashboard_summary",
    "get_health",
    "get_metrics",
    "get_pipeline",
    "get_readiness",
    "get_system_info",
    "get_system_settings",
    "get_task",
    "get_task_result",
    "get_task_stage",
    "get_uploaded_file",
    "get_worker",
    "heartbeat_worker",
    "initialize_default_catalog",
    "lease_stages",
    "list_api_keys",
    "list_backends",
    "list_callback_attempts",
    "list_callback_deliveries",
    "list_events",
    "list_pipelines",
    "list_task_artifacts",
    "list_task_events",
    "list_task_stages",
    "list_tasks",
    "list_workers",
    "publish_pipeline",
    "reconcile_workers",
    "register_worker",
    "renew_stage_lease",
    "retry_callback_delivery",
    "retry_task",
    "rotate_api_key",
    "route_task",
    "run_retention_cleanup",
    "start_stage",
    "stream_events",
    "stream_task_events",
    "test_callback",
    "test_pipeline",
    "update_api_key",
    "update_backend",
    "update_stage_progress",
    "update_system_settings",
    "update_worker",
    "upload_file",
    "upload_stage_artifact",
    "validate_pipeline",
]
HttpMethod = Literal[
    "DELETE",
    "GET",
    "HEAD",
    "OPTIONS",
    "PATCH",
    "POST",
    "PUT",
]


@dataclass(frozen=True, slots=True)
class OperationSpec:
    method: HttpMethod
    path: str


OPERATION_SPECS: Final[dict[OperationId, OperationSpec]] = {
    "cancel_task": OperationSpec(
        "POST",
        "/api/v1/tasks/{task_id}/cancel",
    ),
    "complete_stage": OperationSpec(
        "POST",
        "/internal/v1/workers/stages/{stage_id}/complete",
    ),
    "create_api_key": OperationSpec(
        "POST",
        "/api/v1/management/api-keys",
    ),
    "create_backend": OperationSpec(
        "POST",
        "/api/v1/management/backends",
    ),
    "create_pipeline": OperationSpec(
        "POST",
        "/api/v1/management/pipelines",
    ),
    "create_task": OperationSpec(
        "POST",
        "/api/v1/tasks",
    ),
    "create_task_artifact_download_url": OperationSpec(
        "GET",
        "/api/v1/tasks/{task_id}/artifacts/{artifact_id}/download-url",
    ),
    "delete_api_key": OperationSpec(
        "DELETE",
        "/api/v1/management/api-keys/{api_key_id}",
    ),
    "download_task_artifact": OperationSpec(
        "GET",
        "/api/v1/tasks/{task_id}/artifacts/{artifact_id}/content",
    ),
    "download_task_result": OperationSpec(
        "GET",
        "/api/v1/tasks/{task_id}/result/content",
    ),
    "download_uploaded_file": OperationSpec(
        "GET",
        "/api/v1/files/{file_id}/content",
    ),
    "download_worker_source_file": OperationSpec(
        "GET",
        "/internal/v1/workers/{worker_id}/files/{file_id}/content",
    ),
    "drain_worker_self": OperationSpec(
        "POST",
        "/internal/v1/workers/{worker_id}/drain",
    ),
    "get_api_key": OperationSpec(
        "GET",
        "/api/v1/management/api-keys/{api_key_id}",
    ),
    "get_backend": OperationSpec(
        "GET",
        "/api/v1/management/backends/{backend_id}",
    ),
    "get_callback_delivery": OperationSpec(
        "GET",
        "/api/v1/management/callbacks/{delivery_id}",
    ),
    "get_capabilities": OperationSpec(
        "GET",
        "/api/v1/capabilities",
    ),
    "get_dashboard_summary": OperationSpec(
        "GET",
        "/api/v1/management/dashboard/summary",
    ),
    "get_health": OperationSpec(
        "GET",
        "/health",
    ),
    "get_metrics": OperationSpec(
        "GET",
        "/metrics",
    ),
    "get_pipeline": OperationSpec(
        "GET",
        "/api/v1/management/pipelines/{pipeline_id}/versions/{version}",
    ),
    "get_readiness": OperationSpec(
        "GET",
        "/ready",
    ),
    "get_system_info": OperationSpec(
        "GET",
        "/api/v1/system/info",
    ),
    "get_system_settings": OperationSpec(
        "GET",
        "/api/v1/management/settings",
    ),
    "get_task": OperationSpec(
        "GET",
        "/api/v1/tasks/{task_id}",
    ),
    "get_task_result": OperationSpec(
        "GET",
        "/api/v1/tasks/{task_id}/result",
    ),
    "get_task_stage": OperationSpec(
        "GET",
        "/api/v1/tasks/{task_id}/stages/{stage_id}",
    ),
    "get_uploaded_file": OperationSpec(
        "GET",
        "/api/v1/files/{file_id}",
    ),
    "get_worker": OperationSpec(
        "GET",
        "/api/v1/management/workers/{worker_id}",
    ),
    "heartbeat_worker": OperationSpec(
        "POST",
        "/internal/v1/workers/heartbeat",
    ),
    "initialize_default_catalog": OperationSpec(
        "POST",
        "/api/v1/management/defaults/initialize",
    ),
    "lease_stages": OperationSpec(
        "POST",
        "/internal/v1/workers/lease",
    ),
    "list_api_keys": OperationSpec(
        "GET",
        "/api/v1/management/api-keys",
    ),
    "list_backends": OperationSpec(
        "GET",
        "/api/v1/management/backends",
    ),
    "list_callback_attempts": OperationSpec(
        "GET",
        "/api/v1/management/callbacks/{delivery_id}/attempts",
    ),
    "list_callback_deliveries": OperationSpec(
        "GET",
        "/api/v1/management/callbacks",
    ),
    "list_events": OperationSpec(
        "GET",
        "/api/v1/events",
    ),
    "list_pipelines": OperationSpec(
        "GET",
        "/api/v1/management/pipelines",
    ),
    "list_task_artifacts": OperationSpec(
        "GET",
        "/api/v1/tasks/{task_id}/artifacts",
    ),
    "list_task_events": OperationSpec(
        "GET",
        "/api/v1/tasks/{task_id}/events",
    ),
    "list_task_stages": OperationSpec(
        "GET",
        "/api/v1/tasks/{task_id}/stages",
    ),
    "list_tasks": OperationSpec(
        "GET",
        "/api/v1/tasks",
    ),
    "list_workers": OperationSpec(
        "GET",
        "/api/v1/management/workers",
    ),
    "publish_pipeline": OperationSpec(
        "POST",
        "/api/v1/management/pipelines/{pipeline_id}/versions/{version}/publish",
    ),
    "reconcile_workers": OperationSpec(
        "POST",
        "/api/v1/management/workers/reconcile",
    ),
    "register_worker": OperationSpec(
        "POST",
        "/internal/v1/workers/register",
    ),
    "renew_stage_lease": OperationSpec(
        "POST",
        "/internal/v1/workers/stages/{stage_id}/renew",
    ),
    "retry_callback_delivery": OperationSpec(
        "POST",
        "/api/v1/management/callbacks/{delivery_id}/retry",
    ),
    "retry_task": OperationSpec(
        "POST",
        "/api/v1/tasks/{task_id}/retry",
    ),
    "rotate_api_key": OperationSpec(
        "POST",
        "/api/v1/management/api-keys/{api_key_id}/rotate",
    ),
    "route_task": OperationSpec(
        "POST",
        "/api/v1/management/tasks/{task_id}/route",
    ),
    "run_retention_cleanup": OperationSpec(
        "POST",
        "/api/v1/management/maintenance/retention/run",
    ),
    "start_stage": OperationSpec(
        "POST",
        "/internal/v1/workers/stages/{stage_id}/start",
    ),
    "stream_events": OperationSpec(
        "GET",
        "/api/v1/events/stream",
    ),
    "stream_task_events": OperationSpec(
        "GET",
        "/api/v1/tasks/{task_id}/events/stream",
    ),
    "test_callback": OperationSpec(
        "POST",
        "/api/v1/management/callbacks/test",
    ),
    "test_pipeline": OperationSpec(
        "POST",
        "/api/v1/management/pipelines/{pipeline_id}/versions/{version}/test",
    ),
    "update_api_key": OperationSpec(
        "PATCH",
        "/api/v1/management/api-keys/{api_key_id}",
    ),
    "update_backend": OperationSpec(
        "PATCH",
        "/api/v1/management/backends/{backend_id}",
    ),
    "update_stage_progress": OperationSpec(
        "POST",
        "/internal/v1/workers/stages/{stage_id}/progress",
    ),
    "update_system_settings": OperationSpec(
        "PATCH",
        "/api/v1/management/settings",
    ),
    "update_worker": OperationSpec(
        "PATCH",
        "/api/v1/management/workers/{worker_id}",
    ),
    "upload_file": OperationSpec(
        "POST",
        "/api/v1/files",
    ),
    "upload_stage_artifact": OperationSpec(
        "POST",
        "/internal/v1/workers/{worker_id}/stages/{stage_id}/artifacts",
    ),
    "validate_pipeline": OperationSpec(
        "POST",
        "/api/v1/management/pipelines/{pipeline_id}/versions/{version}/validate",
    ),
}


__all__ = ["OPERATION_SPECS", "HttpMethod", "OperationId", "OperationSpec"]

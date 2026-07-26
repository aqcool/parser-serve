"""Generated Python wire types, operations, and clients. Do not edit."""
# fmt: off

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
import typing
from typing import BinaryIO, Literal, NotRequired, TypedDict, cast


type JsonValue = (
    str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]
)
type UploadContent = bytes | BinaryIO
type UploadFile = tuple[str, UploadContent, str]

type ApiKeyKind = Literal['ordinary', 'worker']

type ApiKeySortField = Literal['created_at', 'updated_at', 'name']

type ApiKeyStatus = Literal['active', 'disabled', 'expired']

class ApiKeySummary(TypedDict):
    api_key_id: str
    created_at: str
    expires_at: NotRequired[(str) | (None)]
    kind: NotRequired[ApiKeyKind]
    last_used_at: NotRequired[(str) | (None)]
    name: str
    prefix: str
    status: ApiKeyStatus
    updated_at: str
    worker_id: NotRequired[(str) | (None)]

class ApiResponse_ApiKeySummary_(TypedDict):
    data: ApiKeySummary
    request_id: str

class ApiResponse_ArtifactDownload_(TypedDict):
    data: ArtifactDownload
    request_id: str

class ApiResponse_Artifact_(TypedDict):
    data: Artifact
    request_id: str

class ApiResponse_BackendDetail_(TypedDict):
    data: BackendDetail
    request_id: str

class ApiResponse_CallbackDeliveryDetail_(TypedDict):
    data: CallbackDeliveryDetail
    request_id: str

class ApiResponse_CallbackTestData_(TypedDict):
    data: CallbackTestData
    request_id: str

class ApiResponse_CreateApiKeyData_(TypedDict):
    data: CreateApiKeyData
    request_id: str

class ApiResponse_CreateTaskData_(TypedDict):
    data: CreateTaskData
    request_id: str

class ApiResponse_DashboardData_(TypedDict):
    data: DashboardData
    request_id: str

class ApiResponse_DefaultCatalogInitializationData_(TypedDict):
    data: DefaultCatalogInitializationData
    request_id: str

class ApiResponse_DeleteApiKeyData_(TypedDict):
    data: DeleteApiKeyData
    request_id: str

class ApiResponse_HealthData_(TypedDict):
    data: HealthData
    request_id: str

class ApiResponse_ParseResult_(TypedDict):
    data: ParseResult
    request_id: str

class ApiResponse_ParserCapabilitiesData_(TypedDict):
    data: ParserCapabilitiesData
    request_id: str

class ApiResponse_PipelineDefinition_(TypedDict):
    data: PipelineDefinition
    request_id: str

class ApiResponse_PipelineValidationData_(TypedDict):
    data: PipelineValidationData
    request_id: str

class ApiResponse_RenewStageLeaseData_(TypedDict):
    data: RenewStageLeaseData
    request_id: str

class ApiResponse_RetentionRunData_(TypedDict):
    data: RetentionRunData
    request_id: str

class ApiResponse_RotateApiKeyData_(TypedDict):
    data: RotateApiKeyData
    request_id: str

class ApiResponse_StageDetail_(TypedDict):
    data: StageDetail
    request_id: str

class ApiResponse_StageExecutionData_(TypedDict):
    data: StageExecutionData
    request_id: str

class ApiResponse_SystemHealthData_(TypedDict):
    data: SystemHealthData
    request_id: str

class ApiResponse_SystemInfoData_(TypedDict):
    data: SystemInfoData
    request_id: str

class ApiResponse_SystemSettingsData_(TypedDict):
    data: SystemSettingsData
    request_id: str

class ApiResponse_TaskDetail_(TypedDict):
    data: TaskDetail
    request_id: str

class ApiResponse_UploadedFileDetail_(TypedDict):
    data: UploadedFileDetail
    request_id: str

class ApiResponse_WorkerDetail_(TypedDict):
    data: WorkerDetail
    request_id: str

class ApiResponse_WorkerHeartbeatData_(TypedDict):
    data: WorkerHeartbeatData
    request_id: str

class ApiResponse_WorkerLeaseData_(TypedDict):
    data: WorkerLeaseData
    request_id: str

class ApiResponse_WorkerReconcileData_(TypedDict):
    data: WorkerReconcileData
    request_id: str

class ApiResponse_WorkerRegistrationData_(TypedDict):
    data: WorkerRegistrationData
    request_id: str

class Artifact(TypedDict):
    artifact_id: str
    created_at: str
    expires_at: NotRequired[(str) | (None)]
    filename: str
    metadata: NotRequired[dict[str, JsonValue_Output]]
    mime_type: str
    sha256: str
    size_bytes: int
    storage_uri: str
    type: ArtifactType

class ArtifactDownload(TypedDict):
    expires_at: str
    method: NotRequired[Literal['GET']]
    url: str

type ArtifactSortField = Literal['created_at', 'filename', 'size_bytes']

type ArtifactType = Literal['original', 'converted_document', 'extracted_image', 'keyframe', 'audio_track', 'subtitle', 'result_json', 'result_text', 'result_markdown', 'other']

class BackendCapability(TypedDict):
    maximum_concurrency: int
    media_categories: NotRequired[list[MediaCategory]]
    mime_types: NotRequired[list[str]]
    name: str
    runtimes: list[DeviceRuntime]
    version: str

class BackendDetail(TypedDict):
    backend_id: str
    capability: BackendCapability
    configuration: NotRequired[dict[str, JsonValue_Output]]
    created_at: str
    default_timeout_seconds: int
    execution_mode: BackendExecutionMode
    maximum_attempts: NotRequired[int]
    remote_url: NotRequired[(str) | (None)]
    scheduling_weight: NotRequired[int]
    status: BackendStatus
    updated_at: str

type BackendExecutionMode = Literal['local', 'remote']

class BackendMetric(TypedDict):
    average_duration_ms: float
    backend_id: str
    calls: int
    failures: int
    fallbacks: int
    timeouts: int

class BackendSelector(TypedDict):
    fallbacks: NotRequired[list[str]]
    preferred: str
    required_runtimes: NotRequired[list[DeviceRuntime]]

type BackendSortField = Literal['created_at', 'updated_at', 'name']

type BackendStatus = Literal['enabled', 'disabled', 'unhealthy']

class BlockLocation(TypedDict):
    bounding_box: NotRequired[(BoundingBox) | (None)]
    end_ms: NotRequired[(int) | (None)]
    page_number: NotRequired[(int) | (None)]
    sheet_name: NotRequired[(str) | (None)]
    slide_number: NotRequired[(int) | (None)]
    start_ms: NotRequired[(int) | (None)]

class Body_upload_file(TypedDict):
    file: UploadFile

class Body_upload_stage_artifact(TypedDict):
    artifact_type: ArtifactType
    file: UploadFile
    idempotency_key: str
    lease_token: str

class BoundingBox(TypedDict):
    bottom: float
    left: float
    right: float
    top: float

class CallbackAttempt(TypedDict):
    attempt_id: str
    attempt_number: int
    completed_at: str
    delivered: bool
    delivery_id: str
    duration_ms: int
    error: NotRequired[(ErrorDetail_Output) | (None)]
    response_status_code: NotRequired[(int) | (None)]
    response_summary: NotRequired[(str) | (None)]
    sequence: int
    started_at: str

type CallbackAttemptSortField = Literal['sequence', 'started_at', 'duration_ms']

class CallbackConfig(TypedDict):
    events: list[CallbackEventType]
    secret: NotRequired[(str) | (None)]
    url: str

class CallbackDashboardSummary(TypedDict):
    failed_deliveries: int
    pending_retries: int
    success_rate: float
    successful_deliveries: int
    total_deliveries: int

class CallbackDeliveryChangedEvent(TypedDict):
    delivery_id: str
    status: CallbackDeliveryStatus
    task_id: str
    type: Literal['callback.delivery_changed']

class CallbackDeliveryDetail(TypedDict):
    attempt: int
    created_at: str
    delivery_id: str
    event: CallbackEvent
    maximum_attempts: int
    next_attempt_at: NotRequired[(str) | (None)]
    response_status_code: NotRequired[(int) | (None)]
    response_summary: NotRequired[(str) | (None)]
    status: CallbackDeliveryStatus
    target_url: str
    total_attempts: int
    updated_at: str

type CallbackDeliveryStatus = Literal['pending', 'delivering', 'succeeded', 'retry_wait', 'failed', 'cancelled']

class CallbackEvent(TypedDict):
    event_id: str
    occurred_at: str
    payload: (TaskCreatedCallback) | (TaskRunningCallback) | (TaskProgressCallback) | (TaskSucceededCallback) | (TaskFailedCallback) | (TaskCancelledCallback)
    schema_version: str
    task_id: str

type CallbackEventType = Literal['task.created', 'task.running', 'task.progress', 'task.succeeded', 'task.failed', 'task.cancelled']

type CallbackSortField = Literal['created_at', 'updated_at', 'status']

class CallbackTestData(TypedDict):
    delivered: bool
    duration_ms: int
    error: NotRequired[(ErrorDetail_Output) | (None)]
    response_status_code: NotRequired[(int) | (None)]

class CallbackTestRequest(TypedDict):
    metadata: NotRequired[dict[str, JsonValue_Input]]
    secret: NotRequired[(str) | (None)]
    url: str

class CompleteStageRequest(TypedDict):
    error: NotRequired[(ErrorDetail_Input) | (None)]
    lease_token: str
    result_uri: NotRequired[(str) | (None)]
    status: Literal['succeeded', 'failed']
    worker_id: str

class ComponentHealth(TypedDict):
    checked_at: str
    healthy: bool
    message: NotRequired[(str) | (None)]
    name: str

class ContentMetadata(TypedDict):
    attributes: NotRequired[dict[str, JsonValue_Output]]
    duration_ms: NotRequired[(int) | (None)]
    height_pixels: NotRequired[(int) | (None)]
    language: NotRequired[(str) | (None)]
    page_count: NotRequired[(int) | (None)]
    title: NotRequired[(str) | (None)]
    width_pixels: NotRequired[(int) | (None)]

class CreateApiKeyData(TypedDict):
    api_key: str
    summary: ApiKeySummary

class CreateApiKeyRequest(TypedDict):
    expires_at: NotRequired[(str) | (None)]
    kind: NotRequired[ApiKeyKind]
    name: str
    worker_id: NotRequired[(str) | (None)]

class CreateBackendRequest(TypedDict):
    capability: BackendCapability
    configuration: NotRequired[dict[str, JsonValue_Input]]
    default_timeout_seconds: int
    enabled: NotRequired[bool]
    execution_mode: BackendExecutionMode
    maximum_attempts: NotRequired[int]
    remote_url: NotRequired[(str) | (None)]
    scheduling_weight: NotRequired[int]

class CreatePipelineRequest(TypedDict):
    media_categories: list[MediaCategory]
    mime_types: NotRequired[list[str]]
    name: str
    pipeline_id: str
    routing_priority: NotRequired[int]
    stages: list[PipelineStageDefinition_Input]

class CreateTaskData(TypedDict):
    created_at: str
    estimated_wait_seconds: NotRequired[(int) | (None)]
    status: TaskStatus
    task_id: str

class CreateTaskRequest(TypedDict):
    callback: NotRequired[(CallbackConfig) | (None)]
    client_reference: NotRequired[(str) | (None)]
    options: NotRequired[TaskOptions]
    source: (UploadedFileSource) | (UrlSource) | (ObjectStorageSource) | (TextSource)

class DashboardData(TypedDict):
    backends: NotRequired[list[BackendMetric]]
    callbacks: CallbackDashboardSummary
    generated_at: str
    runtimes: NotRequired[list[RuntimeMetric]]
    series: NotRequired[list[NamedTimeSeries]]
    storage: StorageDashboardSummary
    tasks: TaskDashboardSummary
    workers: WorkerDashboardSummary

type DefaultCatalogAction = Literal['created', 'published', 'unchanged', 'draft_unavailable']

class DefaultCatalogInitializationData(TypedDict):
    backend_ids_created: NotRequired[list[str]]
    backend_ids_existing: NotRequired[list[str]]
    pipelines: list[DefaultPipelineInitialization]

class DefaultPipelineInitialization(TypedDict):
    action: DefaultCatalogAction
    pipeline_id: str
    status: PipelineStatus
    version: int
    violations: NotRequired[list[PipelineValidationViolation]]

class DeleteApiKeyData(TypedDict):
    api_key_id: str
    deleted: bool

class DeviceInfo(TypedDict):
    device_id: str
    driver_version: NotRequired[(str) | (None)]
    model: str
    runtime: DeviceRuntime
    runtime_version: NotRequired[(str) | (None)]
    total_memory_bytes: NotRequired[(int) | (None)]
    vendor: HardwareVendor

class DeviceRequirement(TypedDict):
    minimum_memory_bytes: NotRequired[(int) | (None)]
    runtimes: NotRequired[list[DeviceRuntime]]
    strategy: NotRequired[SchedulingStrategy]
    worker_labels: NotRequired[dict[str, str]]

type DeviceRuntime = Literal['cpu', 'cuda', 'ascend', 'mlu', 'dcu', 'musa', 'xpu']

class DeviceUsage(TypedDict):
    device_id: str
    memory_total_bytes: NotRequired[(int) | (None)]
    memory_used_bytes: NotRequired[(int) | (None)]
    temperature_celsius: NotRequired[(float) | (None)]
    utilization_percent: NotRequired[(float) | (None)]

type ErrorCode = Literal['VALIDATION_ERROR', 'AUTHENTICATION_FAILED', 'API_KEY_EXPIRED', 'NOT_FOUND', 'CONFLICT', 'UNSUPPORTED_MEDIA_TYPE', 'FILE_TOO_LARGE', 'TASK_NOT_CANCELLABLE', 'WORKER_NOT_AVAILABLE', 'BACKEND_NOT_AVAILABLE', 'TIMEOUT', 'RATE_LIMITED', 'DEPENDENCY_UNAVAILABLE', 'INTERNAL_ERROR']

class ErrorDetail_Input(TypedDict):
    code: ErrorCode
    context: NotRequired[dict[str, JsonValue_Input]]
    field_violations: NotRequired[list[FieldViolation]]
    message: str
    retryable: NotRequired[bool]

class ErrorDetail_Output(TypedDict):
    code: ErrorCode
    context: NotRequired[dict[str, JsonValue_Output]]
    field_violations: NotRequired[list[FieldViolation]]
    message: str
    retryable: NotRequired[bool]

class ErrorResponse(TypedDict):
    error: ErrorDetail_Output
    request_id: str

class EventEnvelope(TypedDict):
    event_id: str
    occurred_at: str
    payload: (TaskCreatedEvent) | (TaskRoutedEvent) | (TaskStatusChangedEvent) | (TaskProgressUpdatedEvent) | (WorkerStatusChangedEvent) | (CallbackDeliveryChangedEvent) | (SystemAlertEvent)
    schema_version: str

type EventSortField = Literal['occurred_at', 'type']

class FieldViolation(TypedDict):
    field: str
    reason: str

type HardwareVendor = Literal['generic', 'nvidia', 'huawei', 'cambricon', 'hygon', 'moore_threads', 'kunlun']

class HeadingBlock(TypedDict):
    block_id: str
    level: int
    location: NotRequired[(BlockLocation) | (None)]
    metadata: NotRequired[dict[str, JsonValue_Output]]
    text: str
    type: Literal['heading']

class HealthData(TypedDict):
    status: HealthStatus
    timestamp: str
    version: str

type HealthStatus = Literal['healthy', 'degraded', 'unhealthy']

class ImageBlock(TypedDict):
    artifact_id: str
    block_id: str
    caption: NotRequired[(str) | (None)]
    location: NotRequired[(BlockLocation) | (None)]
    metadata: NotRequired[dict[str, JsonValue_Output]]
    ocr_text: NotRequired[(str) | (None)]
    type: Literal['image']

class InitializeDefaultsRequest(TypedDict):
    include_builtin_backends: NotRequired[bool]
    publish_valid_pipelines: NotRequired[bool]

type JsonValue_Input = (str) | (int) | (float) | (bool) | (list[JsonValue_Input]) | (dict[str, JsonValue_Input]) | (None)

type JsonValue_Output = (str) | (int) | (float) | (bool) | (list[JsonValue_Output]) | (dict[str, JsonValue_Output]) | (None)

class KeyframeBlock(TypedDict):
    artifact_id: str
    block_id: str
    caption: NotRequired[(str) | (None)]
    metadata: NotRequired[dict[str, JsonValue_Output]]
    ocr_text: NotRequired[(str) | (None)]
    timestamp_ms: int
    type: Literal['keyframe']

class LeasedStage(TypedDict):
    attempt: int
    backend_candidates: list[str]
    backend_id: str
    backend_name: str
    backend_version: str
    device_id: NotRequired[(str) | (None)]
    lease_expires_at: str
    lease_token: str
    maximum_attempts: int
    parameters: NotRequired[dict[str, JsonValue_Output]]
    runtime: DeviceRuntime
    source: (UploadedFileSource) | (UrlSource) | (ObjectStorageSource) | (TextSource)
    source_metadata: SourceMetadata
    stage_id: str
    stage_name: str
    task_id: str
    task_options: TaskOptions
    timeout_seconds: int
    trace_context: NotRequired[(TraceContext) | (None)]

class LinkBlock(TypedDict):
    block_id: str
    metadata: NotRequired[dict[str, JsonValue_Output]]
    text: NotRequired[(str) | (None)]
    type: Literal['link']
    url: str

class ListResponse_ApiKeySummary_(TypedDict):
    items: NotRequired[list[ApiKeySummary]]
    page: PageInfo
    request_id: str

class ListResponse_Artifact_(TypedDict):
    items: NotRequired[list[Artifact]]
    page: PageInfo
    request_id: str

class ListResponse_BackendDetail_(TypedDict):
    items: NotRequired[list[BackendDetail]]
    page: PageInfo
    request_id: str

class ListResponse_CallbackAttempt_(TypedDict):
    items: NotRequired[list[CallbackAttempt]]
    page: PageInfo
    request_id: str

class ListResponse_CallbackDeliveryDetail_(TypedDict):
    items: NotRequired[list[CallbackDeliveryDetail]]
    page: PageInfo
    request_id: str

class ListResponse_EventEnvelope_(TypedDict):
    items: NotRequired[list[EventEnvelope]]
    page: PageInfo
    request_id: str

class ListResponse_PipelineDefinition_(TypedDict):
    items: NotRequired[list[PipelineDefinition]]
    page: PageInfo
    request_id: str

class ListResponse_StageDetail_(TypedDict):
    items: NotRequired[list[StageDetail]]
    page: PageInfo
    request_id: str

class ListResponse_TaskDetail_(TypedDict):
    items: NotRequired[list[TaskDetail]]
    page: PageInfo
    request_id: str

class ListResponse_WorkerDetail_(TypedDict):
    items: NotRequired[list[WorkerDetail]]
    page: PageInfo
    request_id: str

type MediaCategory = Literal['document', 'image', 'audio', 'video', 'web', 'text']

type MetricInterval = Literal['1m', '5m', '1h', '1d']

class NamedTimeSeries(TypedDict):
    name: str
    points: NotRequired[list[TimeSeriesPoint]]
    unit: str

class ObjectStorageSource(TypedDict):
    type: Literal['object_storage']
    uri: str
    version_id: NotRequired[(str) | (None)]

class PageInfo(TypedDict):
    has_more: bool
    next_cursor: NotRequired[(str) | (None)]

class ParseFeatures(TypedDict):
    extract_images: NotRequired[bool]
    extract_keyframes: NotRequired[bool]
    extract_tables: NotRequired[bool]
    extract_text: NotRequired[bool]
    generate_captions: NotRequired[bool]
    run_ocr: NotRequired[bool]
    transcribe_audio: NotRequired[bool]

class ParseResult(TypedDict):
    artifacts: NotRequired[list[Artifact]]
    blocks: NotRequired[list[(TextBlock) | (HeadingBlock) | (TableBlock) | (ImageBlock) | (TranscriptBlock) | (KeyframeBlock) | (LinkBlock)]]
    created_at: str
    metadata: ContentMetadata
    schema_version: str
    source: SourceMetadata
    task_id: str
    warnings: NotRequired[list[ParseWarning]]

class ParseWarning(TypedDict):
    code: str
    context: NotRequired[dict[str, JsonValue_Output]]
    message: str
    stage_id: NotRequired[(str) | (None)]

class ParserCapabilitiesData(TypedDict):
    backends: list[str]
    maximum_upload_bytes: int
    media_categories: list[MediaCategory]
    mime_types: list[str]
    pipelines: list[str]
    runtimes: list[RuntimeCapability]
    schema_version: str

class PipelineDefinition(TypedDict):
    created_at: str
    media_categories: list[MediaCategory]
    mime_types: NotRequired[list[str]]
    name: str
    pipeline_id: str
    published_at: NotRequired[(str) | (None)]
    routing_priority: NotRequired[int]
    stages: list[PipelineStageDefinition_Output]
    status: PipelineStatus
    version: int

type PipelineSortField = Literal['created_at', 'updated_at', 'name', 'version']

class PipelineStageDefinition_Input(TypedDict):
    backend: BackendSelector
    depends_on: NotRequired[list[str]]
    name: str
    optional: NotRequired[bool]
    parameters: NotRequired[dict[str, JsonValue_Input]]
    retry: NotRequired[RetryPolicy]
    timeout_seconds: int

class PipelineStageDefinition_Output(TypedDict):
    backend: BackendSelector
    depends_on: NotRequired[list[str]]
    name: str
    optional: NotRequired[bool]
    parameters: NotRequired[dict[str, JsonValue_Output]]
    retry: NotRequired[RetryPolicy]
    timeout_seconds: int

type PipelineStatus = Literal['draft', 'published', 'disabled', 'archived']

class PipelineTestOptions(TypedDict):
    backend_name: NotRequired[(str) | (None)]
    device: NotRequired[DeviceRequirement]
    features: NotRequired[ParseFeatures]
    priority: NotRequired[int]
    timeout_seconds: NotRequired[(int) | (None)]

class PipelineTestRequest(TypedDict):
    client_reference: NotRequired[(str) | (None)]
    options: NotRequired[PipelineTestOptions]
    source: (UploadedFileSource) | (UrlSource) | (ObjectStorageSource) | (TextSource)

class PipelineValidationData(TypedDict):
    valid: bool
    violations: NotRequired[list[PipelineValidationViolation]]

class PipelineValidationViolation(TypedDict):
    location: str
    message: str

class RenewStageLeaseData(TypedDict):
    lease_expires_at: str
    stage_id: str

class RenewStageLeaseRequest(TypedDict):
    lease_token: str
    worker_id: str

class RetentionRunData(TypedDict):
    artifacts_selected: int
    artifacts_skipped_active: int
    cutoff_time: str
    dry_run: bool
    events_selected: int
    storage_delete_failures: int
    uploaded_files_selected: int
    uploaded_files_skipped_active: int

class RetryPolicy(TypedDict):
    initial_delay_seconds: NotRequired[float]
    maximum_attempts: NotRequired[int]
    maximum_delay_seconds: NotRequired[float]
    multiplier: NotRequired[float]

class RotateApiKeyData(TypedDict):
    api_key: str
    previous_key_valid_until: NotRequired[(str) | (None)]
    summary: ApiKeySummary

class RunRetentionRequest(TypedDict):
    dry_run: NotRequired[bool]
    maximum_records: NotRequired[int]

class RuntimeCapability(TypedDict):
    available_devices: int
    available_workers: int
    runtime: DeviceRuntime
    vendor: HardwareVendor

class RuntimeMetric(TypedDict):
    average_utilization_percent: NotRequired[(float) | (None)]
    devices: int
    memory_total_bytes: NotRequired[(int) | (None)]
    memory_used_bytes: NotRequired[(int) | (None)]
    runtime: DeviceRuntime
    workers: int

type SchedulingStrategy = Literal['auto', 'prefer', 'require']

type SettingKey = Literal['maximum_upload_bytes', 'maximum_result_json_bytes', 'callback_maximum_attempts']

type SettingSource = Literal['deployment', 'database']

type SortDirection = Literal['asc', 'desc']

class SourceMetadata(TypedDict):
    attributes: NotRequired[dict[str, JsonValue_Output]]
    filename: NotRequired[(str) | (None)]
    media_category: MediaCategory
    mime_type: str
    sha256: NotRequired[(str) | (None)]
    size_bytes: NotRequired[(int) | (None)]

class StageDetail(TypedDict):
    attempt: NotRequired[int]
    backend_candidates: NotRequired[list[str]]
    backend_id: NotRequired[(str) | (None)]
    backend_version: NotRequired[(str) | (None)]
    completed_at: NotRequired[(str) | (None)]
    completion_device_id: NotRequired[(str) | (None)]
    completion_worker_id: NotRequired[(str) | (None)]
    created_at: str
    depends_on: NotRequired[list[str]]
    device_id: NotRequired[(str) | (None)]
    error: NotRequired[(ErrorDetail_Output) | (None)]
    maximum_attempts: NotRequired[int]
    name: str
    optional: NotRequired[bool]
    position: NotRequired[int]
    progress_percent: NotRequired[float]
    required_runtimes: NotRequired[list[DeviceRuntime]]
    result_uri: NotRequired[(str) | (None)]
    runtime: NotRequired[(DeviceRuntime) | (None)]
    stage_id: str
    started_at: NotRequired[(str) | (None)]
    status: StageStatus
    timeout_seconds: NotRequired[(int) | (None)]
    worker_id: NotRequired[(str) | (None)]

class StageExecutionData(TypedDict):
    lease_expires_at: NotRequired[(str) | (None)]
    progress_percent: float
    stage_id: str
    stage_status: StageStatus
    task_id: str
    task_status: TaskStatus

class StageProgressRequest(TypedDict):
    lease_token: str
    progress_percent: float
    worker_id: str

type StageSortField = Literal['position', 'created_at']

type StageStatus = Literal['pending', 'leased', 'running', 'succeeded', 'failed', 'cancelled', 'skipped']

class StartStageRequest(TypedDict):
    lease_token: str
    worker_id: str

class StorageDashboardSummary(TypedDict):
    artifact_bytes: int
    objects: int
    original_bytes: int
    result_bytes: int

class SystemAlertEvent(TypedDict):
    code: str
    error: NotRequired[(ErrorDetail_Output) | (None)]
    message: str
    severity: Literal['info', 'warning', 'critical']
    type: Literal['system.alert']

class SystemHealthData(TypedDict):
    components: list[ComponentHealth]
    healthy: bool

class SystemInfoData(TypedDict):
    api_version: str
    build_commit: NotRequired[(str) | (None)]
    build_time: NotRequired[(str) | (None)]
    name: str
    result_schema_version: str
    version: str

class SystemSetting(TypedDict):
    key: SettingKey
    source: SettingSource
    updated_at: NotRequired[(str) | (None)]
    value: JsonValue_Output

class SystemSettingsData(TypedDict):
    settings: list[SystemSetting]

class TableBlock(TypedDict):
    block_id: str
    location: NotRequired[(BlockLocation) | (None)]
    metadata: NotRequired[dict[str, JsonValue_Output]]
    rows: list[list[str]]
    type: Literal['table']

class TaskCancelledCallback(TypedDict):
    cancelled_at: str
    reason: NotRequired[(str) | (None)]
    type: Literal['task.cancelled']

class TaskCreatedCallback(TypedDict):
    created_at: str
    type: Literal['task.created']

class TaskCreatedEvent(TypedDict):
    task_id: str
    type: Literal['task.created']

class TaskDashboardSummary(TypedDict):
    average_execution_ms: float
    average_wait_ms: float
    cancelled_tasks: int
    failed_tasks: int
    p50_execution_ms: float
    p95_execution_ms: float
    p99_execution_ms: float
    pending_tasks: int
    running_tasks: int
    succeeded_tasks: int
    success_rate: float
    total_tasks: int

class TaskDetail(TypedDict):
    client_reference: NotRequired[(str) | (None)]
    completed_at: NotRequired[(str) | (None)]
    created_at: str
    error: NotRequired[(ErrorDetail_Output) | (None)]
    options: TaskOptions
    pipeline_id: NotRequired[(str) | (None)]
    pipeline_version: NotRequired[(int) | (None)]
    progress_percent: NotRequired[float]
    result_uri: NotRequired[(str) | (None)]
    source: (UploadedFileSource) | (UrlSource) | (ObjectStorageSource) | (TextSource)
    source_metadata: NotRequired[(SourceMetadata) | (None)]
    stages: NotRequired[list[StageDetail]]
    started_at: NotRequired[(str) | (None)]
    status: TaskStatus
    task_id: str

class TaskFailedCallback(TypedDict):
    error: ErrorDetail_Output
    failed_at: str
    type: Literal['task.failed']

class TaskOptions(TypedDict):
    backend_name: NotRequired[(str) | (None)]
    device: NotRequired[DeviceRequirement]
    features: NotRequired[ParseFeatures]
    pipeline_id: NotRequired[(str) | (None)]
    pipeline_version: NotRequired[(int) | (None)]
    priority: NotRequired[int]
    timeout_seconds: NotRequired[(int) | (None)]

class TaskProgressCallback(TypedDict):
    progress_percent: float
    stage_id: NotRequired[(str) | (None)]
    stage_name: NotRequired[(str) | (None)]
    type: Literal['task.progress']
    updated_at: str

class TaskProgressUpdatedEvent(TypedDict):
    progress_percent: float
    stage_id: NotRequired[(str) | (None)]
    stage_status: NotRequired[(StageStatus) | (None)]
    task_id: str
    type: Literal['task.progress_updated']

class TaskRoutedEvent(TypedDict):
    pipeline_id: str
    pipeline_version: int
    stage_ids: list[str]
    task_id: str
    type: Literal['task.routed']

class TaskRunningCallback(TypedDict):
    started_at: str
    type: Literal['task.running']

type TaskSortField = Literal['created_at', 'updated_at', 'priority']

type TaskStatus = Literal['pending', 'leased', 'running', 'succeeded', 'failed', 'cancelled']

class TaskStatusChangedEvent(TypedDict):
    current_status: TaskStatus
    previous_status: TaskStatus
    task_id: str
    type: Literal['task.status_changed']

class TaskSucceededCallback(TypedDict):
    completed_at: str
    result_uri: NotRequired[(str) | (None)]
    type: Literal['task.succeeded']

class TextBlock(TypedDict):
    block_id: str
    location: NotRequired[(BlockLocation) | (None)]
    metadata: NotRequired[dict[str, JsonValue_Output]]
    text: str
    type: Literal['text']

class TextSource(TypedDict):
    filename: NotRequired[(str) | (None)]
    mime_type: NotRequired[str]
    text: str
    type: Literal['text']

class TimeSeriesPoint(TypedDict):
    timestamp: str
    value: float

class TraceContext(TypedDict):
    traceparent: str
    tracestate: NotRequired[(str) | (None)]

class TranscriptBlock(TypedDict):
    block_id: str
    end_ms: int
    language: NotRequired[(str) | (None)]
    metadata: NotRequired[dict[str, JsonValue_Output]]
    speaker: NotRequired[(str) | (None)]
    start_ms: int
    text: str
    type: Literal['transcript']

class UpdateApiKeyRequest(TypedDict):
    enabled: NotRequired[(bool) | (None)]
    expires_at: NotRequired[(str) | (None)]
    name: NotRequired[(str) | (None)]

class UpdateBackendRequest(TypedDict):
    configuration: NotRequired[(dict[str, JsonValue_Input]) | (None)]
    default_timeout_seconds: NotRequired[(int) | (None)]
    enabled: NotRequired[(bool) | (None)]
    maximum_attempts: NotRequired[(int) | (None)]
    scheduling_weight: NotRequired[(int) | (None)]

class UpdateSetting(TypedDict):
    key: SettingKey
    value: JsonValue_Input

class UpdateSettingsRequest(TypedDict):
    settings: list[UpdateSetting]

class UpdateWorkerRequest(TypedDict):
    draining: NotRequired[(bool) | (None)]
    enabled: NotRequired[(bool) | (None)]
    labels: NotRequired[(dict[str, str]) | (None)]
    maximum_concurrency: NotRequired[(int) | (None)]
    scheduling_weight: NotRequired[(int) | (None)]

class UploadedFileDetail(TypedDict):
    created_at: str
    expires_at: NotRequired[(str) | (None)]
    file_id: str
    filename: str
    media_category: MediaCategory
    mime_type: str
    sha256: str
    size_bytes: int

class UploadedFileSource(TypedDict):
    file_id: str
    type: Literal['uploaded_file']

class UrlSource(TypedDict):
    type: Literal['url']
    url: str

class WorkerDashboardSummary(TypedDict):
    busy_workers: int
    draining_workers: int
    offline_workers: int
    online_workers: int
    total_concurrency: int
    total_workers: int
    unhealthy_workers: int
    used_concurrency: int

class WorkerDetail(TypedDict):
    backends: list[BackendCapability]
    created_at: str
    device_usage: NotRequired[list[DeviceUsage]]
    devices: list[DeviceInfo]
    enabled: bool
    hostname: str
    labels: NotRequired[dict[str, str]]
    last_heartbeat_at: NotRequired[(str) | (None)]
    maximum_concurrency: int
    name: str
    resources: NotRequired[(WorkerResourceUsage) | (None)]
    scheduling_weight: int
    status: WorkerStatus
    updated_at: str
    version: str
    worker_id: str

class WorkerHealthCheck(TypedDict):
    healthy: bool
    message: NotRequired[(str) | (None)]
    name: str

class WorkerHeartbeatData(TypedDict):
    accepted: bool
    next_heartbeat_seconds: int
    should_drain: NotRequired[bool]

class WorkerHeartbeatRequest(TypedDict):
    devices: NotRequired[list[DeviceUsage]]
    resources: WorkerResourceUsage
    sequence: int
    status: WorkerStatus
    timestamp: str
    worker_id: str

class WorkerLeaseData(TypedDict):
    leases: NotRequired[list[LeasedStage]]

class WorkerLeaseRequest(TypedDict):
    available_slots: int
    wait_seconds: NotRequired[float]
    worker_id: str

class WorkerReconcileData(TypedDict):
    offline_worker_ids: NotRequired[list[str]]
    requeued_stage_ids: NotRequired[list[str]]

class WorkerRegistrationData(TypedDict):
    accepted: bool
    heartbeat_interval_seconds: int
    lease_duration_seconds: int
    registered_at: str
    worker_id: str

class WorkerRegistrationRequest(TypedDict):
    backends: NotRequired[list[BackendCapability]]
    devices: list[DeviceInfo]
    hostname: str
    labels: NotRequired[dict[str, str]]
    maximum_concurrency: int
    name: str
    version: str
    worker_id: str

class WorkerResourceUsage(TypedDict):
    cpu_percent: float
    health_checks: NotRequired[list[WorkerHealthCheck]]
    leased_tasks: int
    memory_total_bytes: int
    memory_used_bytes: int
    running_tasks: int

type WorkerSortField = Literal['created_at', 'updated_at', 'name']

type WorkerStatus = Literal['online', 'busy', 'draining', 'offline', 'unhealthy']

class WorkerStatusChangedEvent(TypedDict):
    current_status: WorkerStatus
    previous_status: NotRequired[(WorkerStatus) | (None)]
    type: Literal['worker.status_changed']
    worker_id: str

class CancelTaskPath(TypedDict):
    task_id: str

class CancelTaskQuery(TypedDict):
    pass

class CancelTaskHeaders(TypedDict):
    pass

type CancelTaskBody = None

type CancelTaskResponse = ApiResponse_TaskDetail_

class CompleteStagePath(TypedDict):
    stage_id: str

class CompleteStageQuery(TypedDict):
    pass

class CompleteStageHeaders(TypedDict):
    pass

type CompleteStageBody = CompleteStageRequest

type CompleteStageResponse = ApiResponse_StageExecutionData_

class CreateApiKeyPath(TypedDict):
    pass

class CreateApiKeyQuery(TypedDict):
    pass

class CreateApiKeyHeaders(TypedDict):
    pass

type CreateApiKeyBody = CreateApiKeyRequest

type CreateApiKeyResponse = ApiResponse_CreateApiKeyData_

class CreateBackendPath(TypedDict):
    pass

class CreateBackendQuery(TypedDict):
    pass

class CreateBackendHeaders(TypedDict):
    pass

type CreateBackendBody = CreateBackendRequest

type CreateBackendResponse = ApiResponse_BackendDetail_

class CreatePipelinePath(TypedDict):
    pass

class CreatePipelineQuery(TypedDict):
    pass

class CreatePipelineHeaders(TypedDict):
    pass

type CreatePipelineBody = CreatePipelineRequest

type CreatePipelineResponse = ApiResponse_PipelineDefinition_

class CreateTaskPath(TypedDict):
    pass

class CreateTaskQuery(TypedDict):
    pass

CreateTaskHeaders = TypedDict(
    'CreateTaskHeaders',
    {
    'Idempotency-Key': typing.NotRequired[(str) | (None)],
    },
)

type CreateTaskBody = CreateTaskRequest

type CreateTaskResponse = ApiResponse_CreateTaskData_

class CreateTaskArtifactDownloadUrlPath(TypedDict):
    task_id: str
    artifact_id: str

class CreateTaskArtifactDownloadUrlQuery(TypedDict):
    pass

class CreateTaskArtifactDownloadUrlHeaders(TypedDict):
    pass

type CreateTaskArtifactDownloadUrlBody = None

type CreateTaskArtifactDownloadUrlResponse = ApiResponse_ArtifactDownload_

class DeleteApiKeyPath(TypedDict):
    api_key_id: str

class DeleteApiKeyQuery(TypedDict):
    pass

class DeleteApiKeyHeaders(TypedDict):
    pass

type DeleteApiKeyBody = None

type DeleteApiKeyResponse = ApiResponse_DeleteApiKeyData_

class DownloadTaskArtifactPath(TypedDict):
    task_id: str
    artifact_id: str

class DownloadTaskArtifactQuery(TypedDict):
    pass

class DownloadTaskArtifactHeaders(TypedDict):
    pass

type DownloadTaskArtifactBody = None

type DownloadTaskArtifactResponse = bytes

class DownloadTaskResultPath(TypedDict):
    task_id: str

class DownloadTaskResultQuery(TypedDict):
    pass

class DownloadTaskResultHeaders(TypedDict):
    pass

type DownloadTaskResultBody = None

type DownloadTaskResultResponse = bytes

class DownloadUploadedFilePath(TypedDict):
    file_id: str

class DownloadUploadedFileQuery(TypedDict):
    pass

class DownloadUploadedFileHeaders(TypedDict):
    pass

type DownloadUploadedFileBody = None

type DownloadUploadedFileResponse = bytes

class DownloadWorkerSourceFilePath(TypedDict):
    worker_id: str
    file_id: str

class DownloadWorkerSourceFileQuery(TypedDict):
    pass

class DownloadWorkerSourceFileHeaders(TypedDict):
    pass

type DownloadWorkerSourceFileBody = None

type DownloadWorkerSourceFileResponse = bytes

class DrainWorkerSelfPath(TypedDict):
    worker_id: str

class DrainWorkerSelfQuery(TypedDict):
    pass

class DrainWorkerSelfHeaders(TypedDict):
    pass

type DrainWorkerSelfBody = None

type DrainWorkerSelfResponse = ApiResponse_WorkerDetail_

class GetApiKeyPath(TypedDict):
    api_key_id: str

class GetApiKeyQuery(TypedDict):
    pass

class GetApiKeyHeaders(TypedDict):
    pass

type GetApiKeyBody = None

type GetApiKeyResponse = ApiResponse_ApiKeySummary_

class GetBackendPath(TypedDict):
    backend_id: str

class GetBackendQuery(TypedDict):
    pass

class GetBackendHeaders(TypedDict):
    pass

type GetBackendBody = None

type GetBackendResponse = ApiResponse_BackendDetail_

class GetCallbackDeliveryPath(TypedDict):
    delivery_id: str

class GetCallbackDeliveryQuery(TypedDict):
    pass

class GetCallbackDeliveryHeaders(TypedDict):
    pass

type GetCallbackDeliveryBody = None

type GetCallbackDeliveryResponse = ApiResponse_CallbackDeliveryDetail_

class GetCapabilitiesPath(TypedDict):
    pass

class GetCapabilitiesQuery(TypedDict):
    pass

class GetCapabilitiesHeaders(TypedDict):
    pass

type GetCapabilitiesBody = None

type GetCapabilitiesResponse = ApiResponse_ParserCapabilitiesData_

class GetDashboardSummaryPath(TypedDict):
    pass

class GetDashboardSummaryQuery(TypedDict):
    start_time: NotRequired[(str) | (None)]
    end_time: NotRequired[(str) | (None)]
    interval: NotRequired[MetricInterval]
    pipeline_id: NotRequired[(str) | (None)]
    backend_id: NotRequired[(str) | (None)]
    worker_id: NotRequired[(str) | (None)]
    runtime: NotRequired[(DeviceRuntime) | (None)]
    media_category: NotRequired[(MediaCategory) | (None)]

class GetDashboardSummaryHeaders(TypedDict):
    pass

type GetDashboardSummaryBody = None

type GetDashboardSummaryResponse = ApiResponse_DashboardData_

class GetHealthPath(TypedDict):
    pass

class GetHealthQuery(TypedDict):
    pass

class GetHealthHeaders(TypedDict):
    pass

type GetHealthBody = None

type GetHealthResponse = ApiResponse_HealthData_

class GetMetricsPath(TypedDict):
    pass

class GetMetricsQuery(TypedDict):
    pass

class GetMetricsHeaders(TypedDict):
    pass

type GetMetricsBody = None

type GetMetricsResponse = str

class GetPipelinePath(TypedDict):
    pipeline_id: str
    version: int

class GetPipelineQuery(TypedDict):
    pass

class GetPipelineHeaders(TypedDict):
    pass

type GetPipelineBody = None

type GetPipelineResponse = ApiResponse_PipelineDefinition_

class GetReadinessPath(TypedDict):
    pass

class GetReadinessQuery(TypedDict):
    pass

class GetReadinessHeaders(TypedDict):
    pass

type GetReadinessBody = None

type GetReadinessResponse = ApiResponse_SystemHealthData_

class GetSystemInfoPath(TypedDict):
    pass

class GetSystemInfoQuery(TypedDict):
    pass

class GetSystemInfoHeaders(TypedDict):
    pass

type GetSystemInfoBody = None

type GetSystemInfoResponse = ApiResponse_SystemInfoData_

class GetSystemSettingsPath(TypedDict):
    pass

class GetSystemSettingsQuery(TypedDict):
    pass

class GetSystemSettingsHeaders(TypedDict):
    pass

type GetSystemSettingsBody = None

type GetSystemSettingsResponse = ApiResponse_SystemSettingsData_

class GetTaskPath(TypedDict):
    task_id: str

class GetTaskQuery(TypedDict):
    pass

class GetTaskHeaders(TypedDict):
    pass

type GetTaskBody = None

type GetTaskResponse = ApiResponse_TaskDetail_

class GetTaskResultPath(TypedDict):
    task_id: str

class GetTaskResultQuery(TypedDict):
    pass

class GetTaskResultHeaders(TypedDict):
    pass

type GetTaskResultBody = None

type GetTaskResultResponse = ApiResponse_ParseResult_

class GetTaskStagePath(TypedDict):
    task_id: str
    stage_id: str

class GetTaskStageQuery(TypedDict):
    pass

class GetTaskStageHeaders(TypedDict):
    pass

type GetTaskStageBody = None

type GetTaskStageResponse = ApiResponse_StageDetail_

class GetUploadedFilePath(TypedDict):
    file_id: str

class GetUploadedFileQuery(TypedDict):
    pass

class GetUploadedFileHeaders(TypedDict):
    pass

type GetUploadedFileBody = None

type GetUploadedFileResponse = ApiResponse_UploadedFileDetail_

class GetWorkerPath(TypedDict):
    worker_id: str

class GetWorkerQuery(TypedDict):
    pass

class GetWorkerHeaders(TypedDict):
    pass

type GetWorkerBody = None

type GetWorkerResponse = ApiResponse_WorkerDetail_

class HeartbeatWorkerPath(TypedDict):
    pass

class HeartbeatWorkerQuery(TypedDict):
    pass

class HeartbeatWorkerHeaders(TypedDict):
    pass

type HeartbeatWorkerBody = WorkerHeartbeatRequest

type HeartbeatWorkerResponse = ApiResponse_WorkerHeartbeatData_

class InitializeDefaultCatalogPath(TypedDict):
    pass

class InitializeDefaultCatalogQuery(TypedDict):
    pass

class InitializeDefaultCatalogHeaders(TypedDict):
    pass

type InitializeDefaultCatalogBody = InitializeDefaultsRequest

type InitializeDefaultCatalogResponse = ApiResponse_DefaultCatalogInitializationData_

class LeaseStagesPath(TypedDict):
    pass

class LeaseStagesQuery(TypedDict):
    pass

class LeaseStagesHeaders(TypedDict):
    pass

type LeaseStagesBody = WorkerLeaseRequest

type LeaseStagesResponse = ApiResponse_WorkerLeaseData_

class ListApiKeysPath(TypedDict):
    pass

class ListApiKeysQuery(TypedDict):
    kinds: NotRequired[(list[ApiKeyKind]) | (None)]
    statuses: NotRequired[(list[ApiKeyStatus]) | (None)]
    name_contains: NotRequired[(str) | (None)]
    limit: NotRequired[int]
    cursor: NotRequired[(str) | (None)]
    sort_by: NotRequired[ApiKeySortField]
    sort_direction: NotRequired[SortDirection]

class ListApiKeysHeaders(TypedDict):
    pass

type ListApiKeysBody = None

type ListApiKeysResponse = ListResponse_ApiKeySummary_

class ListBackendsPath(TypedDict):
    pass

class ListBackendsQuery(TypedDict):
    statuses: NotRequired[(list[BackendStatus]) | (None)]
    runtimes: NotRequired[(list[DeviceRuntime]) | (None)]
    media_category: NotRequired[(MediaCategory) | (None)]
    execution_mode: NotRequired[(BackendExecutionMode) | (None)]
    name_contains: NotRequired[(str) | (None)]
    limit: NotRequired[int]
    cursor: NotRequired[(str) | (None)]
    sort_by: NotRequired[BackendSortField]
    sort_direction: NotRequired[SortDirection]

class ListBackendsHeaders(TypedDict):
    pass

type ListBackendsBody = None

type ListBackendsResponse = ListResponse_BackendDetail_

class ListCallbackAttemptsPath(TypedDict):
    delivery_id: str

class ListCallbackAttemptsQuery(TypedDict):
    delivered: NotRequired[(bool) | (None)]
    limit: NotRequired[int]
    cursor: NotRequired[(str) | (None)]
    sort_by: NotRequired[CallbackAttemptSortField]
    sort_direction: NotRequired[SortDirection]

class ListCallbackAttemptsHeaders(TypedDict):
    pass

type ListCallbackAttemptsBody = None

type ListCallbackAttemptsResponse = ListResponse_CallbackAttempt_

class ListCallbackDeliveriesPath(TypedDict):
    pass

class ListCallbackDeliveriesQuery(TypedDict):
    statuses: NotRequired[(list[CallbackDeliveryStatus]) | (None)]
    task_id: NotRequired[(str) | (None)]
    event_types: NotRequired[(list[CallbackEventType]) | (None)]
    created_after: NotRequired[(str) | (None)]
    created_before: NotRequired[(str) | (None)]
    limit: NotRequired[int]
    cursor: NotRequired[(str) | (None)]
    sort_by: NotRequired[CallbackSortField]
    sort_direction: NotRequired[SortDirection]

class ListCallbackDeliveriesHeaders(TypedDict):
    pass

type ListCallbackDeliveriesBody = None

type ListCallbackDeliveriesResponse = ListResponse_CallbackDeliveryDetail_

class ListEventsPath(TypedDict):
    pass

class ListEventsQuery(TypedDict):
    types: NotRequired[(list[str]) | (None)]
    task_id: NotRequired[(str) | (None)]
    worker_id: NotRequired[(str) | (None)]
    last_event_id: NotRequired[(str) | (None)]
    limit: NotRequired[int]
    sort_by: NotRequired[EventSortField]
    sort_direction: NotRequired[SortDirection]

class ListEventsHeaders(TypedDict):
    pass

type ListEventsBody = None

type ListEventsResponse = ListResponse_EventEnvelope_

class ListPipelinesPath(TypedDict):
    pass

class ListPipelinesQuery(TypedDict):
    statuses: NotRequired[(list[PipelineStatus]) | (None)]
    media_category: NotRequired[(MediaCategory) | (None)]
    name_contains: NotRequired[(str) | (None)]
    limit: NotRequired[int]
    cursor: NotRequired[(str) | (None)]
    sort_by: NotRequired[PipelineSortField]
    sort_direction: NotRequired[SortDirection]

class ListPipelinesHeaders(TypedDict):
    pass

type ListPipelinesBody = None

type ListPipelinesResponse = ListResponse_PipelineDefinition_

class ListTaskArtifactsPath(TypedDict):
    task_id: str

class ListTaskArtifactsQuery(TypedDict):
    types: NotRequired[(list[ArtifactType]) | (None)]
    mime_type: NotRequired[(str) | (None)]
    limit: NotRequired[int]
    cursor: NotRequired[(str) | (None)]
    sort_by: NotRequired[ArtifactSortField]
    sort_direction: NotRequired[SortDirection]

class ListTaskArtifactsHeaders(TypedDict):
    pass

type ListTaskArtifactsBody = None

type ListTaskArtifactsResponse = ListResponse_Artifact_

class ListTaskEventsPath(TypedDict):
    task_id: str

class ListTaskEventsQuery(TypedDict):
    types: NotRequired[(list[str]) | (None)]
    task_id: NotRequired[(str) | (None)]
    worker_id: NotRequired[(str) | (None)]
    last_event_id: NotRequired[(str) | (None)]
    limit: NotRequired[int]
    sort_by: NotRequired[EventSortField]
    sort_direction: NotRequired[SortDirection]

class ListTaskEventsHeaders(TypedDict):
    pass

type ListTaskEventsBody = None

type ListTaskEventsResponse = ListResponse_EventEnvelope_

class ListTaskStagesPath(TypedDict):
    task_id: str

class ListTaskStagesQuery(TypedDict):
    statuses: NotRequired[(list[StageStatus]) | (None)]
    backend_id: NotRequired[(str) | (None)]
    worker_id: NotRequired[(str) | (None)]
    limit: NotRequired[int]
    cursor: NotRequired[(str) | (None)]
    sort_by: NotRequired[StageSortField]
    sort_direction: NotRequired[SortDirection]

class ListTaskStagesHeaders(TypedDict):
    pass

type ListTaskStagesBody = None

type ListTaskStagesResponse = ListResponse_StageDetail_

class ListTasksPath(TypedDict):
    pass

class ListTasksQuery(TypedDict):
    statuses: NotRequired[(list[TaskStatus]) | (None)]
    media_category: NotRequired[(MediaCategory) | (None)]
    pipeline_id: NotRequired[(str) | (None)]
    backend_name: NotRequired[(str) | (None)]
    runtime: NotRequired[(DeviceRuntime) | (None)]
    created_after: NotRequired[(str) | (None)]
    created_before: NotRequired[(str) | (None)]
    limit: NotRequired[int]
    cursor: NotRequired[(str) | (None)]
    sort_by: NotRequired[TaskSortField]
    sort_direction: NotRequired[SortDirection]

class ListTasksHeaders(TypedDict):
    pass

type ListTasksBody = None

type ListTasksResponse = ListResponse_TaskDetail_

class ListWorkersPath(TypedDict):
    pass

class ListWorkersQuery(TypedDict):
    statuses: NotRequired[(list[WorkerStatus]) | (None)]
    runtimes: NotRequired[(list[DeviceRuntime]) | (None)]
    labels: NotRequired[(list[str]) | (None)]
    name_contains: NotRequired[(str) | (None)]
    limit: NotRequired[int]
    cursor: NotRequired[(str) | (None)]
    sort_by: NotRequired[WorkerSortField]
    sort_direction: NotRequired[SortDirection]

class ListWorkersHeaders(TypedDict):
    pass

type ListWorkersBody = None

type ListWorkersResponse = ListResponse_WorkerDetail_

class PublishPipelinePath(TypedDict):
    pipeline_id: str
    version: int

class PublishPipelineQuery(TypedDict):
    pass

class PublishPipelineHeaders(TypedDict):
    pass

type PublishPipelineBody = None

type PublishPipelineResponse = ApiResponse_PipelineDefinition_

class ReconcileWorkersPath(TypedDict):
    pass

class ReconcileWorkersQuery(TypedDict):
    pass

class ReconcileWorkersHeaders(TypedDict):
    pass

type ReconcileWorkersBody = None

type ReconcileWorkersResponse = ApiResponse_WorkerReconcileData_

class RegisterWorkerPath(TypedDict):
    pass

class RegisterWorkerQuery(TypedDict):
    pass

class RegisterWorkerHeaders(TypedDict):
    pass

type RegisterWorkerBody = WorkerRegistrationRequest

type RegisterWorkerResponse = ApiResponse_WorkerRegistrationData_

class RenewStageLeasePath(TypedDict):
    stage_id: str

class RenewStageLeaseQuery(TypedDict):
    pass

class RenewStageLeaseHeaders(TypedDict):
    pass

type RenewStageLeaseBody = RenewStageLeaseRequest

type RenewStageLeaseResponse = ApiResponse_RenewStageLeaseData_

class RetryCallbackDeliveryPath(TypedDict):
    delivery_id: str

class RetryCallbackDeliveryQuery(TypedDict):
    pass

class RetryCallbackDeliveryHeaders(TypedDict):
    pass

type RetryCallbackDeliveryBody = None

type RetryCallbackDeliveryResponse = ApiResponse_CallbackDeliveryDetail_

class RetryTaskPath(TypedDict):
    task_id: str

class RetryTaskQuery(TypedDict):
    pass

class RetryTaskHeaders(TypedDict):
    pass

type RetryTaskBody = None

type RetryTaskResponse = ApiResponse_TaskDetail_

class RotateApiKeyPath(TypedDict):
    api_key_id: str

class RotateApiKeyQuery(TypedDict):
    pass

class RotateApiKeyHeaders(TypedDict):
    pass

type RotateApiKeyBody = None

type RotateApiKeyResponse = ApiResponse_RotateApiKeyData_

class RouteTaskPath(TypedDict):
    task_id: str

class RouteTaskQuery(TypedDict):
    pass

class RouteTaskHeaders(TypedDict):
    pass

type RouteTaskBody = None

type RouteTaskResponse = ApiResponse_TaskDetail_

class RunRetentionCleanupPath(TypedDict):
    pass

class RunRetentionCleanupQuery(TypedDict):
    pass

class RunRetentionCleanupHeaders(TypedDict):
    pass

type RunRetentionCleanupBody = RunRetentionRequest

type RunRetentionCleanupResponse = ApiResponse_RetentionRunData_

class StartStagePath(TypedDict):
    stage_id: str

class StartStageQuery(TypedDict):
    pass

class StartStageHeaders(TypedDict):
    pass

type StartStageBody = StartStageRequest

type StartStageResponse = ApiResponse_StageExecutionData_

class StreamEventsPath(TypedDict):
    pass

class StreamEventsQuery(TypedDict):
    types: NotRequired[(list[str]) | (None)]
    task_id: NotRequired[(str) | (None)]
    worker_id: NotRequired[(str) | (None)]
    last_event_id: NotRequired[(str) | (None)]

StreamEventsHeaders = TypedDict(
    'StreamEventsHeaders',
    {
    'Last-Event-ID': typing.NotRequired[(str) | (None)],
    },
)

type StreamEventsBody = None

type StreamEventsResponse = Iterator[bytes]

class StreamTaskEventsPath(TypedDict):
    task_id: str

class StreamTaskEventsQuery(TypedDict):
    types: NotRequired[(list[str]) | (None)]
    task_id: NotRequired[(str) | (None)]
    worker_id: NotRequired[(str) | (None)]
    last_event_id: NotRequired[(str) | (None)]

StreamTaskEventsHeaders = TypedDict(
    'StreamTaskEventsHeaders',
    {
    'Last-Event-ID': typing.NotRequired[(str) | (None)],
    },
)

type StreamTaskEventsBody = None

type StreamTaskEventsResponse = Iterator[bytes]

class TestCallbackPath(TypedDict):
    pass

class TestCallbackQuery(TypedDict):
    pass

class TestCallbackHeaders(TypedDict):
    pass

type TestCallbackBody = CallbackTestRequest

type TestCallbackResponse = ApiResponse_CallbackTestData_

class TestPipelinePath(TypedDict):
    pipeline_id: str
    version: int

class TestPipelineQuery(TypedDict):
    pass

class TestPipelineHeaders(TypedDict):
    pass

type TestPipelineBody = PipelineTestRequest

type TestPipelineResponse = ApiResponse_TaskDetail_

class UpdateApiKeyPath(TypedDict):
    api_key_id: str

class UpdateApiKeyQuery(TypedDict):
    pass

class UpdateApiKeyHeaders(TypedDict):
    pass

type UpdateApiKeyBody = UpdateApiKeyRequest

type UpdateApiKeyResponse = ApiResponse_ApiKeySummary_

class UpdateBackendPath(TypedDict):
    backend_id: str

class UpdateBackendQuery(TypedDict):
    pass

class UpdateBackendHeaders(TypedDict):
    pass

type UpdateBackendBody = UpdateBackendRequest

type UpdateBackendResponse = ApiResponse_BackendDetail_

class UpdateStageProgressPath(TypedDict):
    stage_id: str

class UpdateStageProgressQuery(TypedDict):
    pass

class UpdateStageProgressHeaders(TypedDict):
    pass

type UpdateStageProgressBody = StageProgressRequest

type UpdateStageProgressResponse = ApiResponse_StageExecutionData_

class UpdateSystemSettingsPath(TypedDict):
    pass

class UpdateSystemSettingsQuery(TypedDict):
    pass

class UpdateSystemSettingsHeaders(TypedDict):
    pass

type UpdateSystemSettingsBody = UpdateSettingsRequest

type UpdateSystemSettingsResponse = ApiResponse_SystemSettingsData_

class UpdateWorkerPath(TypedDict):
    worker_id: str

class UpdateWorkerQuery(TypedDict):
    pass

class UpdateWorkerHeaders(TypedDict):
    pass

type UpdateWorkerBody = UpdateWorkerRequest

type UpdateWorkerResponse = ApiResponse_WorkerDetail_

class UploadFilePath(TypedDict):
    pass

class UploadFileQuery(TypedDict):
    pass

class UploadFileHeaders(TypedDict):
    pass

type UploadFileBody = Body_upload_file

type UploadFileResponse = ApiResponse_UploadedFileDetail_

class UploadStageArtifactPath(TypedDict):
    worker_id: str
    stage_id: str

class UploadStageArtifactQuery(TypedDict):
    pass

class UploadStageArtifactHeaders(TypedDict):
    pass

type UploadStageArtifactBody = Body_upload_stage_artifact

type UploadStageArtifactResponse = ApiResponse_Artifact_

class ValidatePipelinePath(TypedDict):
    pipeline_id: str
    version: int

class ValidatePipelineQuery(TypedDict):
    pass

class ValidatePipelineHeaders(TypedDict):
    pass

type ValidatePipelineBody = None

type ValidatePipelineResponse = ApiResponse_PipelineValidationData_

OperationId = Literal[
    'cancel_task',
    'complete_stage',
    'create_api_key',
    'create_backend',
    'create_pipeline',
    'create_task',
    'create_task_artifact_download_url',
    'delete_api_key',
    'download_task_artifact',
    'download_task_result',
    'download_uploaded_file',
    'download_worker_source_file',
    'drain_worker_self',
    'get_api_key',
    'get_backend',
    'get_callback_delivery',
    'get_capabilities',
    'get_dashboard_summary',
    'get_health',
    'get_metrics',
    'get_pipeline',
    'get_readiness',
    'get_system_info',
    'get_system_settings',
    'get_task',
    'get_task_result',
    'get_task_stage',
    'get_uploaded_file',
    'get_worker',
    'heartbeat_worker',
    'initialize_default_catalog',
    'lease_stages',
    'list_api_keys',
    'list_backends',
    'list_callback_attempts',
    'list_callback_deliveries',
    'list_events',
    'list_pipelines',
    'list_task_artifacts',
    'list_task_events',
    'list_task_stages',
    'list_tasks',
    'list_workers',
    'publish_pipeline',
    'reconcile_workers',
    'register_worker',
    'renew_stage_lease',
    'retry_callback_delivery',
    'retry_task',
    'rotate_api_key',
    'route_task',
    'run_retention_cleanup',
    'start_stage',
    'stream_events',
    'stream_task_events',
    'test_callback',
    'test_pipeline',
    'update_api_key',
    'update_backend',
    'update_stage_progress',
    'update_system_settings',
    'update_worker',
    'upload_file',
    'upload_stage_artifact',
    'validate_pipeline',
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


OPERATION_SPECS: dict[OperationId, OperationSpec] = {
    'cancel_task': OperationSpec('POST', '/api/v1/tasks/{task_id}/cancel'),
    'complete_stage': OperationSpec('POST', '/internal/v1/workers/stages/{stage_id}/complete'),
    'create_api_key': OperationSpec('POST', '/api/v1/management/api-keys'),
    'create_backend': OperationSpec('POST', '/api/v1/management/backends'),
    'create_pipeline': OperationSpec('POST', '/api/v1/management/pipelines'),
    'create_task': OperationSpec('POST', '/api/v1/tasks'),
    'create_task_artifact_download_url': OperationSpec('GET', '/api/v1/tasks/{task_id}/artifacts/{artifact_id}/download-url'),
    'delete_api_key': OperationSpec('DELETE', '/api/v1/management/api-keys/{api_key_id}'),
    'download_task_artifact': OperationSpec('GET', '/api/v1/tasks/{task_id}/artifacts/{artifact_id}/content'),
    'download_task_result': OperationSpec('GET', '/api/v1/tasks/{task_id}/result/content'),
    'download_uploaded_file': OperationSpec('GET', '/api/v1/files/{file_id}/content'),
    'download_worker_source_file': OperationSpec('GET', '/internal/v1/workers/{worker_id}/files/{file_id}/content'),
    'drain_worker_self': OperationSpec('POST', '/internal/v1/workers/{worker_id}/drain'),
    'get_api_key': OperationSpec('GET', '/api/v1/management/api-keys/{api_key_id}'),
    'get_backend': OperationSpec('GET', '/api/v1/management/backends/{backend_id}'),
    'get_callback_delivery': OperationSpec('GET', '/api/v1/management/callbacks/{delivery_id}'),
    'get_capabilities': OperationSpec('GET', '/api/v1/capabilities'),
    'get_dashboard_summary': OperationSpec('GET', '/api/v1/management/dashboard/summary'),
    'get_health': OperationSpec('GET', '/health'),
    'get_metrics': OperationSpec('GET', '/metrics'),
    'get_pipeline': OperationSpec('GET', '/api/v1/management/pipelines/{pipeline_id}/versions/{version}'),
    'get_readiness': OperationSpec('GET', '/ready'),
    'get_system_info': OperationSpec('GET', '/api/v1/system/info'),
    'get_system_settings': OperationSpec('GET', '/api/v1/management/settings'),
    'get_task': OperationSpec('GET', '/api/v1/tasks/{task_id}'),
    'get_task_result': OperationSpec('GET', '/api/v1/tasks/{task_id}/result'),
    'get_task_stage': OperationSpec('GET', '/api/v1/tasks/{task_id}/stages/{stage_id}'),
    'get_uploaded_file': OperationSpec('GET', '/api/v1/files/{file_id}'),
    'get_worker': OperationSpec('GET', '/api/v1/management/workers/{worker_id}'),
    'heartbeat_worker': OperationSpec('POST', '/internal/v1/workers/heartbeat'),
    'initialize_default_catalog': OperationSpec('POST', '/api/v1/management/defaults/initialize'),
    'lease_stages': OperationSpec('POST', '/internal/v1/workers/lease'),
    'list_api_keys': OperationSpec('GET', '/api/v1/management/api-keys'),
    'list_backends': OperationSpec('GET', '/api/v1/management/backends'),
    'list_callback_attempts': OperationSpec('GET', '/api/v1/management/callbacks/{delivery_id}/attempts'),
    'list_callback_deliveries': OperationSpec('GET', '/api/v1/management/callbacks'),
    'list_events': OperationSpec('GET', '/api/v1/events'),
    'list_pipelines': OperationSpec('GET', '/api/v1/management/pipelines'),
    'list_task_artifacts': OperationSpec('GET', '/api/v1/tasks/{task_id}/artifacts'),
    'list_task_events': OperationSpec('GET', '/api/v1/tasks/{task_id}/events'),
    'list_task_stages': OperationSpec('GET', '/api/v1/tasks/{task_id}/stages'),
    'list_tasks': OperationSpec('GET', '/api/v1/tasks'),
    'list_workers': OperationSpec('GET', '/api/v1/management/workers'),
    'publish_pipeline': OperationSpec('POST', '/api/v1/management/pipelines/{pipeline_id}/versions/{version}/publish'),
    'reconcile_workers': OperationSpec('POST', '/api/v1/management/workers/reconcile'),
    'register_worker': OperationSpec('POST', '/internal/v1/workers/register'),
    'renew_stage_lease': OperationSpec('POST', '/internal/v1/workers/stages/{stage_id}/renew'),
    'retry_callback_delivery': OperationSpec('POST', '/api/v1/management/callbacks/{delivery_id}/retry'),
    'retry_task': OperationSpec('POST', '/api/v1/tasks/{task_id}/retry'),
    'rotate_api_key': OperationSpec('POST', '/api/v1/management/api-keys/{api_key_id}/rotate'),
    'route_task': OperationSpec('POST', '/api/v1/management/tasks/{task_id}/route'),
    'run_retention_cleanup': OperationSpec('POST', '/api/v1/management/maintenance/retention/run'),
    'start_stage': OperationSpec('POST', '/internal/v1/workers/stages/{stage_id}/start'),
    'stream_events': OperationSpec('GET', '/api/v1/events/stream'),
    'stream_task_events': OperationSpec('GET', '/api/v1/tasks/{task_id}/events/stream'),
    'test_callback': OperationSpec('POST', '/api/v1/management/callbacks/test'),
    'test_pipeline': OperationSpec('POST', '/api/v1/management/pipelines/{pipeline_id}/versions/{version}/test'),
    'update_api_key': OperationSpec('PATCH', '/api/v1/management/api-keys/{api_key_id}'),
    'update_backend': OperationSpec('PATCH', '/api/v1/management/backends/{backend_id}'),
    'update_stage_progress': OperationSpec('POST', '/internal/v1/workers/stages/{stage_id}/progress'),
    'update_system_settings': OperationSpec('PATCH', '/api/v1/management/settings'),
    'update_worker': OperationSpec('PATCH', '/api/v1/management/workers/{worker_id}'),
    'upload_file': OperationSpec('POST', '/api/v1/files'),
    'upload_stage_artifact': OperationSpec('POST', '/internal/v1/workers/{worker_id}/stages/{stage_id}/artifacts'),
    'validate_pipeline': OperationSpec('POST', '/api/v1/management/pipelines/{pipeline_id}/versions/{version}/validate'),
}


class GeneratedSyncClientMixin:
    """All OpenAPI operations with operation-specific wire types."""

    def _generated_json(
        self, operation_id: OperationId, *, path: object, query: object,
        headers: object, body: object, body_media_type: str | None,
        response_type: object,
    ) -> object:
        raise NotImplementedError

    def _generated_bytes(
        self, operation_id: OperationId, *, path: object, query: object,
        headers: object, body: object, body_media_type: str | None,
    ) -> bytes:
        raise NotImplementedError

    def _generated_text(
        self, operation_id: OperationId, *, path: object, query: object,
        headers: object, body: object, body_media_type: str | None,
    ) -> str:
        raise NotImplementedError

    def _generated_stream(
        self, operation_id: OperationId, *, path: object, query: object,
        headers: object, body: object, body_media_type: str | None,
    ) -> Iterator[bytes]:
        raise NotImplementedError

    def _generated_none(
        self, operation_id: OperationId, *, path: object, query: object,
        headers: object, body: object, body_media_type: str | None,
    ) -> None:
        raise NotImplementedError

    def call_cancel_task(
        self,
        *,
        path: CancelTaskPath,
        query: CancelTaskQuery | None = None,
        headers: CancelTaskHeaders | None = None,
        body: CancelTaskBody | None = None,
    ) -> CancelTaskResponse:
        return cast(CancelTaskResponse, self._generated_json('cancel_task', path=path, query=query, headers=headers, body=body, body_media_type=None, response_type=CancelTaskResponse))

    def call_complete_stage(
        self,
        *,
        path: CompleteStagePath,
        query: CompleteStageQuery | None = None,
        headers: CompleteStageHeaders | None = None,
        body: CompleteStageBody,
    ) -> CompleteStageResponse:
        return cast(CompleteStageResponse, self._generated_json('complete_stage', path=path, query=query, headers=headers, body=body, body_media_type='application/json', response_type=CompleteStageResponse))

    def call_create_api_key(
        self,
        *,
        path: CreateApiKeyPath | None = None,
        query: CreateApiKeyQuery | None = None,
        headers: CreateApiKeyHeaders | None = None,
        body: CreateApiKeyBody,
    ) -> CreateApiKeyResponse:
        return cast(CreateApiKeyResponse, self._generated_json('create_api_key', path=path, query=query, headers=headers, body=body, body_media_type='application/json', response_type=CreateApiKeyResponse))

    def call_create_backend(
        self,
        *,
        path: CreateBackendPath | None = None,
        query: CreateBackendQuery | None = None,
        headers: CreateBackendHeaders | None = None,
        body: CreateBackendBody,
    ) -> CreateBackendResponse:
        return cast(CreateBackendResponse, self._generated_json('create_backend', path=path, query=query, headers=headers, body=body, body_media_type='application/json', response_type=CreateBackendResponse))

    def call_create_pipeline(
        self,
        *,
        path: CreatePipelinePath | None = None,
        query: CreatePipelineQuery | None = None,
        headers: CreatePipelineHeaders | None = None,
        body: CreatePipelineBody,
    ) -> CreatePipelineResponse:
        return cast(CreatePipelineResponse, self._generated_json('create_pipeline', path=path, query=query, headers=headers, body=body, body_media_type='application/json', response_type=CreatePipelineResponse))

    def call_create_task(
        self,
        *,
        path: CreateTaskPath | None = None,
        query: CreateTaskQuery | None = None,
        headers: CreateTaskHeaders | None = None,
        body: CreateTaskBody,
    ) -> CreateTaskResponse:
        return cast(CreateTaskResponse, self._generated_json('create_task', path=path, query=query, headers=headers, body=body, body_media_type='application/json', response_type=CreateTaskResponse))

    def call_create_task_artifact_download_url(
        self,
        *,
        path: CreateTaskArtifactDownloadUrlPath,
        query: CreateTaskArtifactDownloadUrlQuery | None = None,
        headers: CreateTaskArtifactDownloadUrlHeaders | None = None,
        body: CreateTaskArtifactDownloadUrlBody | None = None,
    ) -> CreateTaskArtifactDownloadUrlResponse:
        return cast(CreateTaskArtifactDownloadUrlResponse, self._generated_json('create_task_artifact_download_url', path=path, query=query, headers=headers, body=body, body_media_type=None, response_type=CreateTaskArtifactDownloadUrlResponse))

    def call_delete_api_key(
        self,
        *,
        path: DeleteApiKeyPath,
        query: DeleteApiKeyQuery | None = None,
        headers: DeleteApiKeyHeaders | None = None,
        body: DeleteApiKeyBody | None = None,
    ) -> DeleteApiKeyResponse:
        return cast(DeleteApiKeyResponse, self._generated_json('delete_api_key', path=path, query=query, headers=headers, body=body, body_media_type=None, response_type=DeleteApiKeyResponse))

    def call_download_task_artifact(
        self,
        *,
        path: DownloadTaskArtifactPath,
        query: DownloadTaskArtifactQuery | None = None,
        headers: DownloadTaskArtifactHeaders | None = None,
        body: DownloadTaskArtifactBody | None = None,
    ) -> DownloadTaskArtifactResponse:
        return cast(DownloadTaskArtifactResponse, self._generated_bytes('download_task_artifact', path=path, query=query, headers=headers, body=body, body_media_type=None))

    def call_download_task_result(
        self,
        *,
        path: DownloadTaskResultPath,
        query: DownloadTaskResultQuery | None = None,
        headers: DownloadTaskResultHeaders | None = None,
        body: DownloadTaskResultBody | None = None,
    ) -> DownloadTaskResultResponse:
        return cast(DownloadTaskResultResponse, self._generated_bytes('download_task_result', path=path, query=query, headers=headers, body=body, body_media_type=None))

    def call_download_uploaded_file(
        self,
        *,
        path: DownloadUploadedFilePath,
        query: DownloadUploadedFileQuery | None = None,
        headers: DownloadUploadedFileHeaders | None = None,
        body: DownloadUploadedFileBody | None = None,
    ) -> DownloadUploadedFileResponse:
        return cast(DownloadUploadedFileResponse, self._generated_bytes('download_uploaded_file', path=path, query=query, headers=headers, body=body, body_media_type=None))

    def call_download_worker_source_file(
        self,
        *,
        path: DownloadWorkerSourceFilePath,
        query: DownloadWorkerSourceFileQuery | None = None,
        headers: DownloadWorkerSourceFileHeaders | None = None,
        body: DownloadWorkerSourceFileBody | None = None,
    ) -> DownloadWorkerSourceFileResponse:
        return cast(DownloadWorkerSourceFileResponse, self._generated_bytes('download_worker_source_file', path=path, query=query, headers=headers, body=body, body_media_type=None))

    def call_drain_worker_self(
        self,
        *,
        path: DrainWorkerSelfPath,
        query: DrainWorkerSelfQuery | None = None,
        headers: DrainWorkerSelfHeaders | None = None,
        body: DrainWorkerSelfBody | None = None,
    ) -> DrainWorkerSelfResponse:
        return cast(DrainWorkerSelfResponse, self._generated_json('drain_worker_self', path=path, query=query, headers=headers, body=body, body_media_type=None, response_type=DrainWorkerSelfResponse))

    def call_get_api_key(
        self,
        *,
        path: GetApiKeyPath,
        query: GetApiKeyQuery | None = None,
        headers: GetApiKeyHeaders | None = None,
        body: GetApiKeyBody | None = None,
    ) -> GetApiKeyResponse:
        return cast(GetApiKeyResponse, self._generated_json('get_api_key', path=path, query=query, headers=headers, body=body, body_media_type=None, response_type=GetApiKeyResponse))

    def call_get_backend(
        self,
        *,
        path: GetBackendPath,
        query: GetBackendQuery | None = None,
        headers: GetBackendHeaders | None = None,
        body: GetBackendBody | None = None,
    ) -> GetBackendResponse:
        return cast(GetBackendResponse, self._generated_json('get_backend', path=path, query=query, headers=headers, body=body, body_media_type=None, response_type=GetBackendResponse))

    def call_get_callback_delivery(
        self,
        *,
        path: GetCallbackDeliveryPath,
        query: GetCallbackDeliveryQuery | None = None,
        headers: GetCallbackDeliveryHeaders | None = None,
        body: GetCallbackDeliveryBody | None = None,
    ) -> GetCallbackDeliveryResponse:
        return cast(GetCallbackDeliveryResponse, self._generated_json('get_callback_delivery', path=path, query=query, headers=headers, body=body, body_media_type=None, response_type=GetCallbackDeliveryResponse))

    def call_get_capabilities(
        self,
        *,
        path: GetCapabilitiesPath | None = None,
        query: GetCapabilitiesQuery | None = None,
        headers: GetCapabilitiesHeaders | None = None,
        body: GetCapabilitiesBody | None = None,
    ) -> GetCapabilitiesResponse:
        return cast(GetCapabilitiesResponse, self._generated_json('get_capabilities', path=path, query=query, headers=headers, body=body, body_media_type=None, response_type=GetCapabilitiesResponse))

    def call_get_dashboard_summary(
        self,
        *,
        path: GetDashboardSummaryPath | None = None,
        query: GetDashboardSummaryQuery | None = None,
        headers: GetDashboardSummaryHeaders | None = None,
        body: GetDashboardSummaryBody | None = None,
    ) -> GetDashboardSummaryResponse:
        return cast(GetDashboardSummaryResponse, self._generated_json('get_dashboard_summary', path=path, query=query, headers=headers, body=body, body_media_type=None, response_type=GetDashboardSummaryResponse))

    def call_get_health(
        self,
        *,
        path: GetHealthPath | None = None,
        query: GetHealthQuery | None = None,
        headers: GetHealthHeaders | None = None,
        body: GetHealthBody | None = None,
    ) -> GetHealthResponse:
        return cast(GetHealthResponse, self._generated_json('get_health', path=path, query=query, headers=headers, body=body, body_media_type=None, response_type=GetHealthResponse))

    def call_get_metrics(
        self,
        *,
        path: GetMetricsPath | None = None,
        query: GetMetricsQuery | None = None,
        headers: GetMetricsHeaders | None = None,
        body: GetMetricsBody | None = None,
    ) -> GetMetricsResponse:
        return cast(GetMetricsResponse, self._generated_text('get_metrics', path=path, query=query, headers=headers, body=body, body_media_type=None))

    def call_get_pipeline(
        self,
        *,
        path: GetPipelinePath,
        query: GetPipelineQuery | None = None,
        headers: GetPipelineHeaders | None = None,
        body: GetPipelineBody | None = None,
    ) -> GetPipelineResponse:
        return cast(GetPipelineResponse, self._generated_json('get_pipeline', path=path, query=query, headers=headers, body=body, body_media_type=None, response_type=GetPipelineResponse))

    def call_get_readiness(
        self,
        *,
        path: GetReadinessPath | None = None,
        query: GetReadinessQuery | None = None,
        headers: GetReadinessHeaders | None = None,
        body: GetReadinessBody | None = None,
    ) -> GetReadinessResponse:
        return cast(GetReadinessResponse, self._generated_json('get_readiness', path=path, query=query, headers=headers, body=body, body_media_type=None, response_type=GetReadinessResponse))

    def call_get_system_info(
        self,
        *,
        path: GetSystemInfoPath | None = None,
        query: GetSystemInfoQuery | None = None,
        headers: GetSystemInfoHeaders | None = None,
        body: GetSystemInfoBody | None = None,
    ) -> GetSystemInfoResponse:
        return cast(GetSystemInfoResponse, self._generated_json('get_system_info', path=path, query=query, headers=headers, body=body, body_media_type=None, response_type=GetSystemInfoResponse))

    def call_get_system_settings(
        self,
        *,
        path: GetSystemSettingsPath | None = None,
        query: GetSystemSettingsQuery | None = None,
        headers: GetSystemSettingsHeaders | None = None,
        body: GetSystemSettingsBody | None = None,
    ) -> GetSystemSettingsResponse:
        return cast(GetSystemSettingsResponse, self._generated_json('get_system_settings', path=path, query=query, headers=headers, body=body, body_media_type=None, response_type=GetSystemSettingsResponse))

    def call_get_task(
        self,
        *,
        path: GetTaskPath,
        query: GetTaskQuery | None = None,
        headers: GetTaskHeaders | None = None,
        body: GetTaskBody | None = None,
    ) -> GetTaskResponse:
        return cast(GetTaskResponse, self._generated_json('get_task', path=path, query=query, headers=headers, body=body, body_media_type=None, response_type=GetTaskResponse))

    def call_get_task_result(
        self,
        *,
        path: GetTaskResultPath,
        query: GetTaskResultQuery | None = None,
        headers: GetTaskResultHeaders | None = None,
        body: GetTaskResultBody | None = None,
    ) -> GetTaskResultResponse:
        return cast(GetTaskResultResponse, self._generated_json('get_task_result', path=path, query=query, headers=headers, body=body, body_media_type=None, response_type=GetTaskResultResponse))

    def call_get_task_stage(
        self,
        *,
        path: GetTaskStagePath,
        query: GetTaskStageQuery | None = None,
        headers: GetTaskStageHeaders | None = None,
        body: GetTaskStageBody | None = None,
    ) -> GetTaskStageResponse:
        return cast(GetTaskStageResponse, self._generated_json('get_task_stage', path=path, query=query, headers=headers, body=body, body_media_type=None, response_type=GetTaskStageResponse))

    def call_get_uploaded_file(
        self,
        *,
        path: GetUploadedFilePath,
        query: GetUploadedFileQuery | None = None,
        headers: GetUploadedFileHeaders | None = None,
        body: GetUploadedFileBody | None = None,
    ) -> GetUploadedFileResponse:
        return cast(GetUploadedFileResponse, self._generated_json('get_uploaded_file', path=path, query=query, headers=headers, body=body, body_media_type=None, response_type=GetUploadedFileResponse))

    def call_get_worker(
        self,
        *,
        path: GetWorkerPath,
        query: GetWorkerQuery | None = None,
        headers: GetWorkerHeaders | None = None,
        body: GetWorkerBody | None = None,
    ) -> GetWorkerResponse:
        return cast(GetWorkerResponse, self._generated_json('get_worker', path=path, query=query, headers=headers, body=body, body_media_type=None, response_type=GetWorkerResponse))

    def call_heartbeat_worker(
        self,
        *,
        path: HeartbeatWorkerPath | None = None,
        query: HeartbeatWorkerQuery | None = None,
        headers: HeartbeatWorkerHeaders | None = None,
        body: HeartbeatWorkerBody,
    ) -> HeartbeatWorkerResponse:
        return cast(HeartbeatWorkerResponse, self._generated_json('heartbeat_worker', path=path, query=query, headers=headers, body=body, body_media_type='application/json', response_type=HeartbeatWorkerResponse))

    def call_initialize_default_catalog(
        self,
        *,
        path: InitializeDefaultCatalogPath | None = None,
        query: InitializeDefaultCatalogQuery | None = None,
        headers: InitializeDefaultCatalogHeaders | None = None,
        body: InitializeDefaultCatalogBody,
    ) -> InitializeDefaultCatalogResponse:
        return cast(InitializeDefaultCatalogResponse, self._generated_json('initialize_default_catalog', path=path, query=query, headers=headers, body=body, body_media_type='application/json', response_type=InitializeDefaultCatalogResponse))

    def call_lease_stages(
        self,
        *,
        path: LeaseStagesPath | None = None,
        query: LeaseStagesQuery | None = None,
        headers: LeaseStagesHeaders | None = None,
        body: LeaseStagesBody,
    ) -> LeaseStagesResponse:
        return cast(LeaseStagesResponse, self._generated_json('lease_stages', path=path, query=query, headers=headers, body=body, body_media_type='application/json', response_type=LeaseStagesResponse))

    def call_list_api_keys(
        self,
        *,
        path: ListApiKeysPath | None = None,
        query: ListApiKeysQuery | None = None,
        headers: ListApiKeysHeaders | None = None,
        body: ListApiKeysBody | None = None,
    ) -> ListApiKeysResponse:
        return cast(ListApiKeysResponse, self._generated_json('list_api_keys', path=path, query=query, headers=headers, body=body, body_media_type=None, response_type=ListApiKeysResponse))

    def call_list_backends(
        self,
        *,
        path: ListBackendsPath | None = None,
        query: ListBackendsQuery | None = None,
        headers: ListBackendsHeaders | None = None,
        body: ListBackendsBody | None = None,
    ) -> ListBackendsResponse:
        return cast(ListBackendsResponse, self._generated_json('list_backends', path=path, query=query, headers=headers, body=body, body_media_type=None, response_type=ListBackendsResponse))

    def call_list_callback_attempts(
        self,
        *,
        path: ListCallbackAttemptsPath,
        query: ListCallbackAttemptsQuery | None = None,
        headers: ListCallbackAttemptsHeaders | None = None,
        body: ListCallbackAttemptsBody | None = None,
    ) -> ListCallbackAttemptsResponse:
        return cast(ListCallbackAttemptsResponse, self._generated_json('list_callback_attempts', path=path, query=query, headers=headers, body=body, body_media_type=None, response_type=ListCallbackAttemptsResponse))

    def call_list_callback_deliveries(
        self,
        *,
        path: ListCallbackDeliveriesPath | None = None,
        query: ListCallbackDeliveriesQuery | None = None,
        headers: ListCallbackDeliveriesHeaders | None = None,
        body: ListCallbackDeliveriesBody | None = None,
    ) -> ListCallbackDeliveriesResponse:
        return cast(ListCallbackDeliveriesResponse, self._generated_json('list_callback_deliveries', path=path, query=query, headers=headers, body=body, body_media_type=None, response_type=ListCallbackDeliveriesResponse))

    def call_list_events(
        self,
        *,
        path: ListEventsPath | None = None,
        query: ListEventsQuery | None = None,
        headers: ListEventsHeaders | None = None,
        body: ListEventsBody | None = None,
    ) -> ListEventsResponse:
        return cast(ListEventsResponse, self._generated_json('list_events', path=path, query=query, headers=headers, body=body, body_media_type=None, response_type=ListEventsResponse))

    def call_list_pipelines(
        self,
        *,
        path: ListPipelinesPath | None = None,
        query: ListPipelinesQuery | None = None,
        headers: ListPipelinesHeaders | None = None,
        body: ListPipelinesBody | None = None,
    ) -> ListPipelinesResponse:
        return cast(ListPipelinesResponse, self._generated_json('list_pipelines', path=path, query=query, headers=headers, body=body, body_media_type=None, response_type=ListPipelinesResponse))

    def call_list_task_artifacts(
        self,
        *,
        path: ListTaskArtifactsPath,
        query: ListTaskArtifactsQuery | None = None,
        headers: ListTaskArtifactsHeaders | None = None,
        body: ListTaskArtifactsBody | None = None,
    ) -> ListTaskArtifactsResponse:
        return cast(ListTaskArtifactsResponse, self._generated_json('list_task_artifacts', path=path, query=query, headers=headers, body=body, body_media_type=None, response_type=ListTaskArtifactsResponse))

    def call_list_task_events(
        self,
        *,
        path: ListTaskEventsPath,
        query: ListTaskEventsQuery | None = None,
        headers: ListTaskEventsHeaders | None = None,
        body: ListTaskEventsBody | None = None,
    ) -> ListTaskEventsResponse:
        return cast(ListTaskEventsResponse, self._generated_json('list_task_events', path=path, query=query, headers=headers, body=body, body_media_type=None, response_type=ListTaskEventsResponse))

    def call_list_task_stages(
        self,
        *,
        path: ListTaskStagesPath,
        query: ListTaskStagesQuery | None = None,
        headers: ListTaskStagesHeaders | None = None,
        body: ListTaskStagesBody | None = None,
    ) -> ListTaskStagesResponse:
        return cast(ListTaskStagesResponse, self._generated_json('list_task_stages', path=path, query=query, headers=headers, body=body, body_media_type=None, response_type=ListTaskStagesResponse))

    def call_list_tasks(
        self,
        *,
        path: ListTasksPath | None = None,
        query: ListTasksQuery | None = None,
        headers: ListTasksHeaders | None = None,
        body: ListTasksBody | None = None,
    ) -> ListTasksResponse:
        return cast(ListTasksResponse, self._generated_json('list_tasks', path=path, query=query, headers=headers, body=body, body_media_type=None, response_type=ListTasksResponse))

    def call_list_workers(
        self,
        *,
        path: ListWorkersPath | None = None,
        query: ListWorkersQuery | None = None,
        headers: ListWorkersHeaders | None = None,
        body: ListWorkersBody | None = None,
    ) -> ListWorkersResponse:
        return cast(ListWorkersResponse, self._generated_json('list_workers', path=path, query=query, headers=headers, body=body, body_media_type=None, response_type=ListWorkersResponse))

    def call_publish_pipeline(
        self,
        *,
        path: PublishPipelinePath,
        query: PublishPipelineQuery | None = None,
        headers: PublishPipelineHeaders | None = None,
        body: PublishPipelineBody | None = None,
    ) -> PublishPipelineResponse:
        return cast(PublishPipelineResponse, self._generated_json('publish_pipeline', path=path, query=query, headers=headers, body=body, body_media_type=None, response_type=PublishPipelineResponse))

    def call_reconcile_workers(
        self,
        *,
        path: ReconcileWorkersPath | None = None,
        query: ReconcileWorkersQuery | None = None,
        headers: ReconcileWorkersHeaders | None = None,
        body: ReconcileWorkersBody | None = None,
    ) -> ReconcileWorkersResponse:
        return cast(ReconcileWorkersResponse, self._generated_json('reconcile_workers', path=path, query=query, headers=headers, body=body, body_media_type=None, response_type=ReconcileWorkersResponse))

    def call_register_worker(
        self,
        *,
        path: RegisterWorkerPath | None = None,
        query: RegisterWorkerQuery | None = None,
        headers: RegisterWorkerHeaders | None = None,
        body: RegisterWorkerBody,
    ) -> RegisterWorkerResponse:
        return cast(RegisterWorkerResponse, self._generated_json('register_worker', path=path, query=query, headers=headers, body=body, body_media_type='application/json', response_type=RegisterWorkerResponse))

    def call_renew_stage_lease(
        self,
        *,
        path: RenewStageLeasePath,
        query: RenewStageLeaseQuery | None = None,
        headers: RenewStageLeaseHeaders | None = None,
        body: RenewStageLeaseBody,
    ) -> RenewStageLeaseResponse:
        return cast(RenewStageLeaseResponse, self._generated_json('renew_stage_lease', path=path, query=query, headers=headers, body=body, body_media_type='application/json', response_type=RenewStageLeaseResponse))

    def call_retry_callback_delivery(
        self,
        *,
        path: RetryCallbackDeliveryPath,
        query: RetryCallbackDeliveryQuery | None = None,
        headers: RetryCallbackDeliveryHeaders | None = None,
        body: RetryCallbackDeliveryBody | None = None,
    ) -> RetryCallbackDeliveryResponse:
        return cast(RetryCallbackDeliveryResponse, self._generated_json('retry_callback_delivery', path=path, query=query, headers=headers, body=body, body_media_type=None, response_type=RetryCallbackDeliveryResponse))

    def call_retry_task(
        self,
        *,
        path: RetryTaskPath,
        query: RetryTaskQuery | None = None,
        headers: RetryTaskHeaders | None = None,
        body: RetryTaskBody | None = None,
    ) -> RetryTaskResponse:
        return cast(RetryTaskResponse, self._generated_json('retry_task', path=path, query=query, headers=headers, body=body, body_media_type=None, response_type=RetryTaskResponse))

    def call_rotate_api_key(
        self,
        *,
        path: RotateApiKeyPath,
        query: RotateApiKeyQuery | None = None,
        headers: RotateApiKeyHeaders | None = None,
        body: RotateApiKeyBody | None = None,
    ) -> RotateApiKeyResponse:
        return cast(RotateApiKeyResponse, self._generated_json('rotate_api_key', path=path, query=query, headers=headers, body=body, body_media_type=None, response_type=RotateApiKeyResponse))

    def call_route_task(
        self,
        *,
        path: RouteTaskPath,
        query: RouteTaskQuery | None = None,
        headers: RouteTaskHeaders | None = None,
        body: RouteTaskBody | None = None,
    ) -> RouteTaskResponse:
        return cast(RouteTaskResponse, self._generated_json('route_task', path=path, query=query, headers=headers, body=body, body_media_type=None, response_type=RouteTaskResponse))

    def call_run_retention_cleanup(
        self,
        *,
        path: RunRetentionCleanupPath | None = None,
        query: RunRetentionCleanupQuery | None = None,
        headers: RunRetentionCleanupHeaders | None = None,
        body: RunRetentionCleanupBody,
    ) -> RunRetentionCleanupResponse:
        return cast(RunRetentionCleanupResponse, self._generated_json('run_retention_cleanup', path=path, query=query, headers=headers, body=body, body_media_type='application/json', response_type=RunRetentionCleanupResponse))

    def call_start_stage(
        self,
        *,
        path: StartStagePath,
        query: StartStageQuery | None = None,
        headers: StartStageHeaders | None = None,
        body: StartStageBody,
    ) -> StartStageResponse:
        return cast(StartStageResponse, self._generated_json('start_stage', path=path, query=query, headers=headers, body=body, body_media_type='application/json', response_type=StartStageResponse))

    def call_stream_events(
        self,
        *,
        path: StreamEventsPath | None = None,
        query: StreamEventsQuery | None = None,
        headers: StreamEventsHeaders | None = None,
        body: StreamEventsBody | None = None,
    ) -> StreamEventsResponse:
        return cast(StreamEventsResponse, self._generated_stream('stream_events', path=path, query=query, headers=headers, body=body, body_media_type=None))

    def call_stream_task_events(
        self,
        *,
        path: StreamTaskEventsPath,
        query: StreamTaskEventsQuery | None = None,
        headers: StreamTaskEventsHeaders | None = None,
        body: StreamTaskEventsBody | None = None,
    ) -> StreamTaskEventsResponse:
        return cast(StreamTaskEventsResponse, self._generated_stream('stream_task_events', path=path, query=query, headers=headers, body=body, body_media_type=None))

    def call_test_callback(
        self,
        *,
        path: TestCallbackPath | None = None,
        query: TestCallbackQuery | None = None,
        headers: TestCallbackHeaders | None = None,
        body: TestCallbackBody,
    ) -> TestCallbackResponse:
        return cast(TestCallbackResponse, self._generated_json('test_callback', path=path, query=query, headers=headers, body=body, body_media_type='application/json', response_type=TestCallbackResponse))

    def call_test_pipeline(
        self,
        *,
        path: TestPipelinePath,
        query: TestPipelineQuery | None = None,
        headers: TestPipelineHeaders | None = None,
        body: TestPipelineBody,
    ) -> TestPipelineResponse:
        return cast(TestPipelineResponse, self._generated_json('test_pipeline', path=path, query=query, headers=headers, body=body, body_media_type='application/json', response_type=TestPipelineResponse))

    def call_update_api_key(
        self,
        *,
        path: UpdateApiKeyPath,
        query: UpdateApiKeyQuery | None = None,
        headers: UpdateApiKeyHeaders | None = None,
        body: UpdateApiKeyBody,
    ) -> UpdateApiKeyResponse:
        return cast(UpdateApiKeyResponse, self._generated_json('update_api_key', path=path, query=query, headers=headers, body=body, body_media_type='application/json', response_type=UpdateApiKeyResponse))

    def call_update_backend(
        self,
        *,
        path: UpdateBackendPath,
        query: UpdateBackendQuery | None = None,
        headers: UpdateBackendHeaders | None = None,
        body: UpdateBackendBody,
    ) -> UpdateBackendResponse:
        return cast(UpdateBackendResponse, self._generated_json('update_backend', path=path, query=query, headers=headers, body=body, body_media_type='application/json', response_type=UpdateBackendResponse))

    def call_update_stage_progress(
        self,
        *,
        path: UpdateStageProgressPath,
        query: UpdateStageProgressQuery | None = None,
        headers: UpdateStageProgressHeaders | None = None,
        body: UpdateStageProgressBody,
    ) -> UpdateStageProgressResponse:
        return cast(UpdateStageProgressResponse, self._generated_json('update_stage_progress', path=path, query=query, headers=headers, body=body, body_media_type='application/json', response_type=UpdateStageProgressResponse))

    def call_update_system_settings(
        self,
        *,
        path: UpdateSystemSettingsPath | None = None,
        query: UpdateSystemSettingsQuery | None = None,
        headers: UpdateSystemSettingsHeaders | None = None,
        body: UpdateSystemSettingsBody,
    ) -> UpdateSystemSettingsResponse:
        return cast(UpdateSystemSettingsResponse, self._generated_json('update_system_settings', path=path, query=query, headers=headers, body=body, body_media_type='application/json', response_type=UpdateSystemSettingsResponse))

    def call_update_worker(
        self,
        *,
        path: UpdateWorkerPath,
        query: UpdateWorkerQuery | None = None,
        headers: UpdateWorkerHeaders | None = None,
        body: UpdateWorkerBody,
    ) -> UpdateWorkerResponse:
        return cast(UpdateWorkerResponse, self._generated_json('update_worker', path=path, query=query, headers=headers, body=body, body_media_type='application/json', response_type=UpdateWorkerResponse))

    def call_upload_file(
        self,
        *,
        path: UploadFilePath | None = None,
        query: UploadFileQuery | None = None,
        headers: UploadFileHeaders | None = None,
        body: UploadFileBody,
    ) -> UploadFileResponse:
        return cast(UploadFileResponse, self._generated_json('upload_file', path=path, query=query, headers=headers, body=body, body_media_type='multipart/form-data', response_type=UploadFileResponse))

    def call_upload_stage_artifact(
        self,
        *,
        path: UploadStageArtifactPath,
        query: UploadStageArtifactQuery | None = None,
        headers: UploadStageArtifactHeaders | None = None,
        body: UploadStageArtifactBody,
    ) -> UploadStageArtifactResponse:
        return cast(UploadStageArtifactResponse, self._generated_json('upload_stage_artifact', path=path, query=query, headers=headers, body=body, body_media_type='multipart/form-data', response_type=UploadStageArtifactResponse))

    def call_validate_pipeline(
        self,
        *,
        path: ValidatePipelinePath,
        query: ValidatePipelineQuery | None = None,
        headers: ValidatePipelineHeaders | None = None,
        body: ValidatePipelineBody | None = None,
    ) -> ValidatePipelineResponse:
        return cast(ValidatePipelineResponse, self._generated_json('validate_pipeline', path=path, query=query, headers=headers, body=body, body_media_type=None, response_type=ValidatePipelineResponse))

class GeneratedAsyncClientMixin:
    """Async variants of every typed OpenAPI operation."""

    async def _generated_json(
        self, operation_id: OperationId, *, path: object, query: object,
        headers: object, body: object, body_media_type: str | None,
        response_type: object,
    ) -> object:
        raise NotImplementedError

    async def _generated_bytes(
        self, operation_id: OperationId, *, path: object, query: object,
        headers: object, body: object, body_media_type: str | None,
    ) -> bytes:
        raise NotImplementedError

    async def _generated_text(
        self, operation_id: OperationId, *, path: object, query: object,
        headers: object, body: object, body_media_type: str | None,
    ) -> str:
        raise NotImplementedError

    def _generated_stream(
        self, operation_id: OperationId, *, path: object, query: object,
        headers: object, body: object, body_media_type: str | None,
    ) -> AsyncIterator[bytes]:
        raise NotImplementedError

    async def _generated_none(
        self, operation_id: OperationId, *, path: object, query: object,
        headers: object, body: object, body_media_type: str | None,
    ) -> None:
        raise NotImplementedError

    async def call_cancel_task(
        self,
        *,
        path: CancelTaskPath,
        query: CancelTaskQuery | None = None,
        headers: CancelTaskHeaders | None = None,
        body: CancelTaskBody | None = None,
    ) -> CancelTaskResponse:
        return cast(CancelTaskResponse, await self._generated_json('cancel_task', path=path, query=query, headers=headers, body=body, body_media_type=None, response_type=CancelTaskResponse))

    async def call_complete_stage(
        self,
        *,
        path: CompleteStagePath,
        query: CompleteStageQuery | None = None,
        headers: CompleteStageHeaders | None = None,
        body: CompleteStageBody,
    ) -> CompleteStageResponse:
        return cast(CompleteStageResponse, await self._generated_json('complete_stage', path=path, query=query, headers=headers, body=body, body_media_type='application/json', response_type=CompleteStageResponse))

    async def call_create_api_key(
        self,
        *,
        path: CreateApiKeyPath | None = None,
        query: CreateApiKeyQuery | None = None,
        headers: CreateApiKeyHeaders | None = None,
        body: CreateApiKeyBody,
    ) -> CreateApiKeyResponse:
        return cast(CreateApiKeyResponse, await self._generated_json('create_api_key', path=path, query=query, headers=headers, body=body, body_media_type='application/json', response_type=CreateApiKeyResponse))

    async def call_create_backend(
        self,
        *,
        path: CreateBackendPath | None = None,
        query: CreateBackendQuery | None = None,
        headers: CreateBackendHeaders | None = None,
        body: CreateBackendBody,
    ) -> CreateBackendResponse:
        return cast(CreateBackendResponse, await self._generated_json('create_backend', path=path, query=query, headers=headers, body=body, body_media_type='application/json', response_type=CreateBackendResponse))

    async def call_create_pipeline(
        self,
        *,
        path: CreatePipelinePath | None = None,
        query: CreatePipelineQuery | None = None,
        headers: CreatePipelineHeaders | None = None,
        body: CreatePipelineBody,
    ) -> CreatePipelineResponse:
        return cast(CreatePipelineResponse, await self._generated_json('create_pipeline', path=path, query=query, headers=headers, body=body, body_media_type='application/json', response_type=CreatePipelineResponse))

    async def call_create_task(
        self,
        *,
        path: CreateTaskPath | None = None,
        query: CreateTaskQuery | None = None,
        headers: CreateTaskHeaders | None = None,
        body: CreateTaskBody,
    ) -> CreateTaskResponse:
        return cast(CreateTaskResponse, await self._generated_json('create_task', path=path, query=query, headers=headers, body=body, body_media_type='application/json', response_type=CreateTaskResponse))

    async def call_create_task_artifact_download_url(
        self,
        *,
        path: CreateTaskArtifactDownloadUrlPath,
        query: CreateTaskArtifactDownloadUrlQuery | None = None,
        headers: CreateTaskArtifactDownloadUrlHeaders | None = None,
        body: CreateTaskArtifactDownloadUrlBody | None = None,
    ) -> CreateTaskArtifactDownloadUrlResponse:
        return cast(CreateTaskArtifactDownloadUrlResponse, await self._generated_json('create_task_artifact_download_url', path=path, query=query, headers=headers, body=body, body_media_type=None, response_type=CreateTaskArtifactDownloadUrlResponse))

    async def call_delete_api_key(
        self,
        *,
        path: DeleteApiKeyPath,
        query: DeleteApiKeyQuery | None = None,
        headers: DeleteApiKeyHeaders | None = None,
        body: DeleteApiKeyBody | None = None,
    ) -> DeleteApiKeyResponse:
        return cast(DeleteApiKeyResponse, await self._generated_json('delete_api_key', path=path, query=query, headers=headers, body=body, body_media_type=None, response_type=DeleteApiKeyResponse))

    async def call_download_task_artifact(
        self,
        *,
        path: DownloadTaskArtifactPath,
        query: DownloadTaskArtifactQuery | None = None,
        headers: DownloadTaskArtifactHeaders | None = None,
        body: DownloadTaskArtifactBody | None = None,
    ) -> DownloadTaskArtifactResponse:
        return cast(DownloadTaskArtifactResponse, await self._generated_bytes('download_task_artifact', path=path, query=query, headers=headers, body=body, body_media_type=None))

    async def call_download_task_result(
        self,
        *,
        path: DownloadTaskResultPath,
        query: DownloadTaskResultQuery | None = None,
        headers: DownloadTaskResultHeaders | None = None,
        body: DownloadTaskResultBody | None = None,
    ) -> DownloadTaskResultResponse:
        return cast(DownloadTaskResultResponse, await self._generated_bytes('download_task_result', path=path, query=query, headers=headers, body=body, body_media_type=None))

    async def call_download_uploaded_file(
        self,
        *,
        path: DownloadUploadedFilePath,
        query: DownloadUploadedFileQuery | None = None,
        headers: DownloadUploadedFileHeaders | None = None,
        body: DownloadUploadedFileBody | None = None,
    ) -> DownloadUploadedFileResponse:
        return cast(DownloadUploadedFileResponse, await self._generated_bytes('download_uploaded_file', path=path, query=query, headers=headers, body=body, body_media_type=None))

    async def call_download_worker_source_file(
        self,
        *,
        path: DownloadWorkerSourceFilePath,
        query: DownloadWorkerSourceFileQuery | None = None,
        headers: DownloadWorkerSourceFileHeaders | None = None,
        body: DownloadWorkerSourceFileBody | None = None,
    ) -> DownloadWorkerSourceFileResponse:
        return cast(DownloadWorkerSourceFileResponse, await self._generated_bytes('download_worker_source_file', path=path, query=query, headers=headers, body=body, body_media_type=None))

    async def call_drain_worker_self(
        self,
        *,
        path: DrainWorkerSelfPath,
        query: DrainWorkerSelfQuery | None = None,
        headers: DrainWorkerSelfHeaders | None = None,
        body: DrainWorkerSelfBody | None = None,
    ) -> DrainWorkerSelfResponse:
        return cast(DrainWorkerSelfResponse, await self._generated_json('drain_worker_self', path=path, query=query, headers=headers, body=body, body_media_type=None, response_type=DrainWorkerSelfResponse))

    async def call_get_api_key(
        self,
        *,
        path: GetApiKeyPath,
        query: GetApiKeyQuery | None = None,
        headers: GetApiKeyHeaders | None = None,
        body: GetApiKeyBody | None = None,
    ) -> GetApiKeyResponse:
        return cast(GetApiKeyResponse, await self._generated_json('get_api_key', path=path, query=query, headers=headers, body=body, body_media_type=None, response_type=GetApiKeyResponse))

    async def call_get_backend(
        self,
        *,
        path: GetBackendPath,
        query: GetBackendQuery | None = None,
        headers: GetBackendHeaders | None = None,
        body: GetBackendBody | None = None,
    ) -> GetBackendResponse:
        return cast(GetBackendResponse, await self._generated_json('get_backend', path=path, query=query, headers=headers, body=body, body_media_type=None, response_type=GetBackendResponse))

    async def call_get_callback_delivery(
        self,
        *,
        path: GetCallbackDeliveryPath,
        query: GetCallbackDeliveryQuery | None = None,
        headers: GetCallbackDeliveryHeaders | None = None,
        body: GetCallbackDeliveryBody | None = None,
    ) -> GetCallbackDeliveryResponse:
        return cast(GetCallbackDeliveryResponse, await self._generated_json('get_callback_delivery', path=path, query=query, headers=headers, body=body, body_media_type=None, response_type=GetCallbackDeliveryResponse))

    async def call_get_capabilities(
        self,
        *,
        path: GetCapabilitiesPath | None = None,
        query: GetCapabilitiesQuery | None = None,
        headers: GetCapabilitiesHeaders | None = None,
        body: GetCapabilitiesBody | None = None,
    ) -> GetCapabilitiesResponse:
        return cast(GetCapabilitiesResponse, await self._generated_json('get_capabilities', path=path, query=query, headers=headers, body=body, body_media_type=None, response_type=GetCapabilitiesResponse))

    async def call_get_dashboard_summary(
        self,
        *,
        path: GetDashboardSummaryPath | None = None,
        query: GetDashboardSummaryQuery | None = None,
        headers: GetDashboardSummaryHeaders | None = None,
        body: GetDashboardSummaryBody | None = None,
    ) -> GetDashboardSummaryResponse:
        return cast(GetDashboardSummaryResponse, await self._generated_json('get_dashboard_summary', path=path, query=query, headers=headers, body=body, body_media_type=None, response_type=GetDashboardSummaryResponse))

    async def call_get_health(
        self,
        *,
        path: GetHealthPath | None = None,
        query: GetHealthQuery | None = None,
        headers: GetHealthHeaders | None = None,
        body: GetHealthBody | None = None,
    ) -> GetHealthResponse:
        return cast(GetHealthResponse, await self._generated_json('get_health', path=path, query=query, headers=headers, body=body, body_media_type=None, response_type=GetHealthResponse))

    async def call_get_metrics(
        self,
        *,
        path: GetMetricsPath | None = None,
        query: GetMetricsQuery | None = None,
        headers: GetMetricsHeaders | None = None,
        body: GetMetricsBody | None = None,
    ) -> GetMetricsResponse:
        return cast(GetMetricsResponse, await self._generated_text('get_metrics', path=path, query=query, headers=headers, body=body, body_media_type=None))

    async def call_get_pipeline(
        self,
        *,
        path: GetPipelinePath,
        query: GetPipelineQuery | None = None,
        headers: GetPipelineHeaders | None = None,
        body: GetPipelineBody | None = None,
    ) -> GetPipelineResponse:
        return cast(GetPipelineResponse, await self._generated_json('get_pipeline', path=path, query=query, headers=headers, body=body, body_media_type=None, response_type=GetPipelineResponse))

    async def call_get_readiness(
        self,
        *,
        path: GetReadinessPath | None = None,
        query: GetReadinessQuery | None = None,
        headers: GetReadinessHeaders | None = None,
        body: GetReadinessBody | None = None,
    ) -> GetReadinessResponse:
        return cast(GetReadinessResponse, await self._generated_json('get_readiness', path=path, query=query, headers=headers, body=body, body_media_type=None, response_type=GetReadinessResponse))

    async def call_get_system_info(
        self,
        *,
        path: GetSystemInfoPath | None = None,
        query: GetSystemInfoQuery | None = None,
        headers: GetSystemInfoHeaders | None = None,
        body: GetSystemInfoBody | None = None,
    ) -> GetSystemInfoResponse:
        return cast(GetSystemInfoResponse, await self._generated_json('get_system_info', path=path, query=query, headers=headers, body=body, body_media_type=None, response_type=GetSystemInfoResponse))

    async def call_get_system_settings(
        self,
        *,
        path: GetSystemSettingsPath | None = None,
        query: GetSystemSettingsQuery | None = None,
        headers: GetSystemSettingsHeaders | None = None,
        body: GetSystemSettingsBody | None = None,
    ) -> GetSystemSettingsResponse:
        return cast(GetSystemSettingsResponse, await self._generated_json('get_system_settings', path=path, query=query, headers=headers, body=body, body_media_type=None, response_type=GetSystemSettingsResponse))

    async def call_get_task(
        self,
        *,
        path: GetTaskPath,
        query: GetTaskQuery | None = None,
        headers: GetTaskHeaders | None = None,
        body: GetTaskBody | None = None,
    ) -> GetTaskResponse:
        return cast(GetTaskResponse, await self._generated_json('get_task', path=path, query=query, headers=headers, body=body, body_media_type=None, response_type=GetTaskResponse))

    async def call_get_task_result(
        self,
        *,
        path: GetTaskResultPath,
        query: GetTaskResultQuery | None = None,
        headers: GetTaskResultHeaders | None = None,
        body: GetTaskResultBody | None = None,
    ) -> GetTaskResultResponse:
        return cast(GetTaskResultResponse, await self._generated_json('get_task_result', path=path, query=query, headers=headers, body=body, body_media_type=None, response_type=GetTaskResultResponse))

    async def call_get_task_stage(
        self,
        *,
        path: GetTaskStagePath,
        query: GetTaskStageQuery | None = None,
        headers: GetTaskStageHeaders | None = None,
        body: GetTaskStageBody | None = None,
    ) -> GetTaskStageResponse:
        return cast(GetTaskStageResponse, await self._generated_json('get_task_stage', path=path, query=query, headers=headers, body=body, body_media_type=None, response_type=GetTaskStageResponse))

    async def call_get_uploaded_file(
        self,
        *,
        path: GetUploadedFilePath,
        query: GetUploadedFileQuery | None = None,
        headers: GetUploadedFileHeaders | None = None,
        body: GetUploadedFileBody | None = None,
    ) -> GetUploadedFileResponse:
        return cast(GetUploadedFileResponse, await self._generated_json('get_uploaded_file', path=path, query=query, headers=headers, body=body, body_media_type=None, response_type=GetUploadedFileResponse))

    async def call_get_worker(
        self,
        *,
        path: GetWorkerPath,
        query: GetWorkerQuery | None = None,
        headers: GetWorkerHeaders | None = None,
        body: GetWorkerBody | None = None,
    ) -> GetWorkerResponse:
        return cast(GetWorkerResponse, await self._generated_json('get_worker', path=path, query=query, headers=headers, body=body, body_media_type=None, response_type=GetWorkerResponse))

    async def call_heartbeat_worker(
        self,
        *,
        path: HeartbeatWorkerPath | None = None,
        query: HeartbeatWorkerQuery | None = None,
        headers: HeartbeatWorkerHeaders | None = None,
        body: HeartbeatWorkerBody,
    ) -> HeartbeatWorkerResponse:
        return cast(HeartbeatWorkerResponse, await self._generated_json('heartbeat_worker', path=path, query=query, headers=headers, body=body, body_media_type='application/json', response_type=HeartbeatWorkerResponse))

    async def call_initialize_default_catalog(
        self,
        *,
        path: InitializeDefaultCatalogPath | None = None,
        query: InitializeDefaultCatalogQuery | None = None,
        headers: InitializeDefaultCatalogHeaders | None = None,
        body: InitializeDefaultCatalogBody,
    ) -> InitializeDefaultCatalogResponse:
        return cast(InitializeDefaultCatalogResponse, await self._generated_json('initialize_default_catalog', path=path, query=query, headers=headers, body=body, body_media_type='application/json', response_type=InitializeDefaultCatalogResponse))

    async def call_lease_stages(
        self,
        *,
        path: LeaseStagesPath | None = None,
        query: LeaseStagesQuery | None = None,
        headers: LeaseStagesHeaders | None = None,
        body: LeaseStagesBody,
    ) -> LeaseStagesResponse:
        return cast(LeaseStagesResponse, await self._generated_json('lease_stages', path=path, query=query, headers=headers, body=body, body_media_type='application/json', response_type=LeaseStagesResponse))

    async def call_list_api_keys(
        self,
        *,
        path: ListApiKeysPath | None = None,
        query: ListApiKeysQuery | None = None,
        headers: ListApiKeysHeaders | None = None,
        body: ListApiKeysBody | None = None,
    ) -> ListApiKeysResponse:
        return cast(ListApiKeysResponse, await self._generated_json('list_api_keys', path=path, query=query, headers=headers, body=body, body_media_type=None, response_type=ListApiKeysResponse))

    async def call_list_backends(
        self,
        *,
        path: ListBackendsPath | None = None,
        query: ListBackendsQuery | None = None,
        headers: ListBackendsHeaders | None = None,
        body: ListBackendsBody | None = None,
    ) -> ListBackendsResponse:
        return cast(ListBackendsResponse, await self._generated_json('list_backends', path=path, query=query, headers=headers, body=body, body_media_type=None, response_type=ListBackendsResponse))

    async def call_list_callback_attempts(
        self,
        *,
        path: ListCallbackAttemptsPath,
        query: ListCallbackAttemptsQuery | None = None,
        headers: ListCallbackAttemptsHeaders | None = None,
        body: ListCallbackAttemptsBody | None = None,
    ) -> ListCallbackAttemptsResponse:
        return cast(ListCallbackAttemptsResponse, await self._generated_json('list_callback_attempts', path=path, query=query, headers=headers, body=body, body_media_type=None, response_type=ListCallbackAttemptsResponse))

    async def call_list_callback_deliveries(
        self,
        *,
        path: ListCallbackDeliveriesPath | None = None,
        query: ListCallbackDeliveriesQuery | None = None,
        headers: ListCallbackDeliveriesHeaders | None = None,
        body: ListCallbackDeliveriesBody | None = None,
    ) -> ListCallbackDeliveriesResponse:
        return cast(ListCallbackDeliveriesResponse, await self._generated_json('list_callback_deliveries', path=path, query=query, headers=headers, body=body, body_media_type=None, response_type=ListCallbackDeliveriesResponse))

    async def call_list_events(
        self,
        *,
        path: ListEventsPath | None = None,
        query: ListEventsQuery | None = None,
        headers: ListEventsHeaders | None = None,
        body: ListEventsBody | None = None,
    ) -> ListEventsResponse:
        return cast(ListEventsResponse, await self._generated_json('list_events', path=path, query=query, headers=headers, body=body, body_media_type=None, response_type=ListEventsResponse))

    async def call_list_pipelines(
        self,
        *,
        path: ListPipelinesPath | None = None,
        query: ListPipelinesQuery | None = None,
        headers: ListPipelinesHeaders | None = None,
        body: ListPipelinesBody | None = None,
    ) -> ListPipelinesResponse:
        return cast(ListPipelinesResponse, await self._generated_json('list_pipelines', path=path, query=query, headers=headers, body=body, body_media_type=None, response_type=ListPipelinesResponse))

    async def call_list_task_artifacts(
        self,
        *,
        path: ListTaskArtifactsPath,
        query: ListTaskArtifactsQuery | None = None,
        headers: ListTaskArtifactsHeaders | None = None,
        body: ListTaskArtifactsBody | None = None,
    ) -> ListTaskArtifactsResponse:
        return cast(ListTaskArtifactsResponse, await self._generated_json('list_task_artifacts', path=path, query=query, headers=headers, body=body, body_media_type=None, response_type=ListTaskArtifactsResponse))

    async def call_list_task_events(
        self,
        *,
        path: ListTaskEventsPath,
        query: ListTaskEventsQuery | None = None,
        headers: ListTaskEventsHeaders | None = None,
        body: ListTaskEventsBody | None = None,
    ) -> ListTaskEventsResponse:
        return cast(ListTaskEventsResponse, await self._generated_json('list_task_events', path=path, query=query, headers=headers, body=body, body_media_type=None, response_type=ListTaskEventsResponse))

    async def call_list_task_stages(
        self,
        *,
        path: ListTaskStagesPath,
        query: ListTaskStagesQuery | None = None,
        headers: ListTaskStagesHeaders | None = None,
        body: ListTaskStagesBody | None = None,
    ) -> ListTaskStagesResponse:
        return cast(ListTaskStagesResponse, await self._generated_json('list_task_stages', path=path, query=query, headers=headers, body=body, body_media_type=None, response_type=ListTaskStagesResponse))

    async def call_list_tasks(
        self,
        *,
        path: ListTasksPath | None = None,
        query: ListTasksQuery | None = None,
        headers: ListTasksHeaders | None = None,
        body: ListTasksBody | None = None,
    ) -> ListTasksResponse:
        return cast(ListTasksResponse, await self._generated_json('list_tasks', path=path, query=query, headers=headers, body=body, body_media_type=None, response_type=ListTasksResponse))

    async def call_list_workers(
        self,
        *,
        path: ListWorkersPath | None = None,
        query: ListWorkersQuery | None = None,
        headers: ListWorkersHeaders | None = None,
        body: ListWorkersBody | None = None,
    ) -> ListWorkersResponse:
        return cast(ListWorkersResponse, await self._generated_json('list_workers', path=path, query=query, headers=headers, body=body, body_media_type=None, response_type=ListWorkersResponse))

    async def call_publish_pipeline(
        self,
        *,
        path: PublishPipelinePath,
        query: PublishPipelineQuery | None = None,
        headers: PublishPipelineHeaders | None = None,
        body: PublishPipelineBody | None = None,
    ) -> PublishPipelineResponse:
        return cast(PublishPipelineResponse, await self._generated_json('publish_pipeline', path=path, query=query, headers=headers, body=body, body_media_type=None, response_type=PublishPipelineResponse))

    async def call_reconcile_workers(
        self,
        *,
        path: ReconcileWorkersPath | None = None,
        query: ReconcileWorkersQuery | None = None,
        headers: ReconcileWorkersHeaders | None = None,
        body: ReconcileWorkersBody | None = None,
    ) -> ReconcileWorkersResponse:
        return cast(ReconcileWorkersResponse, await self._generated_json('reconcile_workers', path=path, query=query, headers=headers, body=body, body_media_type=None, response_type=ReconcileWorkersResponse))

    async def call_register_worker(
        self,
        *,
        path: RegisterWorkerPath | None = None,
        query: RegisterWorkerQuery | None = None,
        headers: RegisterWorkerHeaders | None = None,
        body: RegisterWorkerBody,
    ) -> RegisterWorkerResponse:
        return cast(RegisterWorkerResponse, await self._generated_json('register_worker', path=path, query=query, headers=headers, body=body, body_media_type='application/json', response_type=RegisterWorkerResponse))

    async def call_renew_stage_lease(
        self,
        *,
        path: RenewStageLeasePath,
        query: RenewStageLeaseQuery | None = None,
        headers: RenewStageLeaseHeaders | None = None,
        body: RenewStageLeaseBody,
    ) -> RenewStageLeaseResponse:
        return cast(RenewStageLeaseResponse, await self._generated_json('renew_stage_lease', path=path, query=query, headers=headers, body=body, body_media_type='application/json', response_type=RenewStageLeaseResponse))

    async def call_retry_callback_delivery(
        self,
        *,
        path: RetryCallbackDeliveryPath,
        query: RetryCallbackDeliveryQuery | None = None,
        headers: RetryCallbackDeliveryHeaders | None = None,
        body: RetryCallbackDeliveryBody | None = None,
    ) -> RetryCallbackDeliveryResponse:
        return cast(RetryCallbackDeliveryResponse, await self._generated_json('retry_callback_delivery', path=path, query=query, headers=headers, body=body, body_media_type=None, response_type=RetryCallbackDeliveryResponse))

    async def call_retry_task(
        self,
        *,
        path: RetryTaskPath,
        query: RetryTaskQuery | None = None,
        headers: RetryTaskHeaders | None = None,
        body: RetryTaskBody | None = None,
    ) -> RetryTaskResponse:
        return cast(RetryTaskResponse, await self._generated_json('retry_task', path=path, query=query, headers=headers, body=body, body_media_type=None, response_type=RetryTaskResponse))

    async def call_rotate_api_key(
        self,
        *,
        path: RotateApiKeyPath,
        query: RotateApiKeyQuery | None = None,
        headers: RotateApiKeyHeaders | None = None,
        body: RotateApiKeyBody | None = None,
    ) -> RotateApiKeyResponse:
        return cast(RotateApiKeyResponse, await self._generated_json('rotate_api_key', path=path, query=query, headers=headers, body=body, body_media_type=None, response_type=RotateApiKeyResponse))

    async def call_route_task(
        self,
        *,
        path: RouteTaskPath,
        query: RouteTaskQuery | None = None,
        headers: RouteTaskHeaders | None = None,
        body: RouteTaskBody | None = None,
    ) -> RouteTaskResponse:
        return cast(RouteTaskResponse, await self._generated_json('route_task', path=path, query=query, headers=headers, body=body, body_media_type=None, response_type=RouteTaskResponse))

    async def call_run_retention_cleanup(
        self,
        *,
        path: RunRetentionCleanupPath | None = None,
        query: RunRetentionCleanupQuery | None = None,
        headers: RunRetentionCleanupHeaders | None = None,
        body: RunRetentionCleanupBody,
    ) -> RunRetentionCleanupResponse:
        return cast(RunRetentionCleanupResponse, await self._generated_json('run_retention_cleanup', path=path, query=query, headers=headers, body=body, body_media_type='application/json', response_type=RunRetentionCleanupResponse))

    async def call_start_stage(
        self,
        *,
        path: StartStagePath,
        query: StartStageQuery | None = None,
        headers: StartStageHeaders | None = None,
        body: StartStageBody,
    ) -> StartStageResponse:
        return cast(StartStageResponse, await self._generated_json('start_stage', path=path, query=query, headers=headers, body=body, body_media_type='application/json', response_type=StartStageResponse))

    def call_stream_events(
        self,
        *,
        path: StreamEventsPath | None = None,
        query: StreamEventsQuery | None = None,
        headers: StreamEventsHeaders | None = None,
        body: StreamEventsBody | None = None,
    ) -> AsyncIterator[bytes]:
        return cast(AsyncIterator[bytes], self._generated_stream('stream_events', path=path, query=query, headers=headers, body=body, body_media_type=None))

    def call_stream_task_events(
        self,
        *,
        path: StreamTaskEventsPath,
        query: StreamTaskEventsQuery | None = None,
        headers: StreamTaskEventsHeaders | None = None,
        body: StreamTaskEventsBody | None = None,
    ) -> AsyncIterator[bytes]:
        return cast(AsyncIterator[bytes], self._generated_stream('stream_task_events', path=path, query=query, headers=headers, body=body, body_media_type=None))

    async def call_test_callback(
        self,
        *,
        path: TestCallbackPath | None = None,
        query: TestCallbackQuery | None = None,
        headers: TestCallbackHeaders | None = None,
        body: TestCallbackBody,
    ) -> TestCallbackResponse:
        return cast(TestCallbackResponse, await self._generated_json('test_callback', path=path, query=query, headers=headers, body=body, body_media_type='application/json', response_type=TestCallbackResponse))

    async def call_test_pipeline(
        self,
        *,
        path: TestPipelinePath,
        query: TestPipelineQuery | None = None,
        headers: TestPipelineHeaders | None = None,
        body: TestPipelineBody,
    ) -> TestPipelineResponse:
        return cast(TestPipelineResponse, await self._generated_json('test_pipeline', path=path, query=query, headers=headers, body=body, body_media_type='application/json', response_type=TestPipelineResponse))

    async def call_update_api_key(
        self,
        *,
        path: UpdateApiKeyPath,
        query: UpdateApiKeyQuery | None = None,
        headers: UpdateApiKeyHeaders | None = None,
        body: UpdateApiKeyBody,
    ) -> UpdateApiKeyResponse:
        return cast(UpdateApiKeyResponse, await self._generated_json('update_api_key', path=path, query=query, headers=headers, body=body, body_media_type='application/json', response_type=UpdateApiKeyResponse))

    async def call_update_backend(
        self,
        *,
        path: UpdateBackendPath,
        query: UpdateBackendQuery | None = None,
        headers: UpdateBackendHeaders | None = None,
        body: UpdateBackendBody,
    ) -> UpdateBackendResponse:
        return cast(UpdateBackendResponse, await self._generated_json('update_backend', path=path, query=query, headers=headers, body=body, body_media_type='application/json', response_type=UpdateBackendResponse))

    async def call_update_stage_progress(
        self,
        *,
        path: UpdateStageProgressPath,
        query: UpdateStageProgressQuery | None = None,
        headers: UpdateStageProgressHeaders | None = None,
        body: UpdateStageProgressBody,
    ) -> UpdateStageProgressResponse:
        return cast(UpdateStageProgressResponse, await self._generated_json('update_stage_progress', path=path, query=query, headers=headers, body=body, body_media_type='application/json', response_type=UpdateStageProgressResponse))

    async def call_update_system_settings(
        self,
        *,
        path: UpdateSystemSettingsPath | None = None,
        query: UpdateSystemSettingsQuery | None = None,
        headers: UpdateSystemSettingsHeaders | None = None,
        body: UpdateSystemSettingsBody,
    ) -> UpdateSystemSettingsResponse:
        return cast(UpdateSystemSettingsResponse, await self._generated_json('update_system_settings', path=path, query=query, headers=headers, body=body, body_media_type='application/json', response_type=UpdateSystemSettingsResponse))

    async def call_update_worker(
        self,
        *,
        path: UpdateWorkerPath,
        query: UpdateWorkerQuery | None = None,
        headers: UpdateWorkerHeaders | None = None,
        body: UpdateWorkerBody,
    ) -> UpdateWorkerResponse:
        return cast(UpdateWorkerResponse, await self._generated_json('update_worker', path=path, query=query, headers=headers, body=body, body_media_type='application/json', response_type=UpdateWorkerResponse))

    async def call_upload_file(
        self,
        *,
        path: UploadFilePath | None = None,
        query: UploadFileQuery | None = None,
        headers: UploadFileHeaders | None = None,
        body: UploadFileBody,
    ) -> UploadFileResponse:
        return cast(UploadFileResponse, await self._generated_json('upload_file', path=path, query=query, headers=headers, body=body, body_media_type='multipart/form-data', response_type=UploadFileResponse))

    async def call_upload_stage_artifact(
        self,
        *,
        path: UploadStageArtifactPath,
        query: UploadStageArtifactQuery | None = None,
        headers: UploadStageArtifactHeaders | None = None,
        body: UploadStageArtifactBody,
    ) -> UploadStageArtifactResponse:
        return cast(UploadStageArtifactResponse, await self._generated_json('upload_stage_artifact', path=path, query=query, headers=headers, body=body, body_media_type='multipart/form-data', response_type=UploadStageArtifactResponse))

    async def call_validate_pipeline(
        self,
        *,
        path: ValidatePipelinePath,
        query: ValidatePipelineQuery | None = None,
        headers: ValidatePipelineHeaders | None = None,
        body: ValidatePipelineBody | None = None,
    ) -> ValidatePipelineResponse:
        return cast(ValidatePipelineResponse, await self._generated_json('validate_pipeline', path=path, query=query, headers=headers, body=body, body_media_type=None, response_type=ValidatePipelineResponse))

__all__ = [
    "GeneratedAsyncClientMixin",
    "GeneratedSyncClientMixin",
    "HttpMethod",
    "OPERATION_SPECS",
    "OperationId",
    "OperationSpec",
    "UploadContent",
    "UploadFile",
    'CancelTaskBody',
    'CancelTaskHeaders',
    'CancelTaskPath',
    'CancelTaskQuery',
    'CancelTaskResponse',
    'CompleteStageBody',
    'CompleteStageHeaders',
    'CompleteStagePath',
    'CompleteStageQuery',
    'CompleteStageResponse',
    'CreateApiKeyBody',
    'CreateApiKeyHeaders',
    'CreateApiKeyPath',
    'CreateApiKeyQuery',
    'CreateApiKeyResponse',
    'CreateBackendBody',
    'CreateBackendHeaders',
    'CreateBackendPath',
    'CreateBackendQuery',
    'CreateBackendResponse',
    'CreatePipelineBody',
    'CreatePipelineHeaders',
    'CreatePipelinePath',
    'CreatePipelineQuery',
    'CreatePipelineResponse',
    'CreateTaskBody',
    'CreateTaskHeaders',
    'CreateTaskPath',
    'CreateTaskQuery',
    'CreateTaskResponse',
    'CreateTaskArtifactDownloadUrlBody',
    'CreateTaskArtifactDownloadUrlHeaders',
    'CreateTaskArtifactDownloadUrlPath',
    'CreateTaskArtifactDownloadUrlQuery',
    'CreateTaskArtifactDownloadUrlResponse',
    'DeleteApiKeyBody',
    'DeleteApiKeyHeaders',
    'DeleteApiKeyPath',
    'DeleteApiKeyQuery',
    'DeleteApiKeyResponse',
    'DownloadTaskArtifactBody',
    'DownloadTaskArtifactHeaders',
    'DownloadTaskArtifactPath',
    'DownloadTaskArtifactQuery',
    'DownloadTaskArtifactResponse',
    'DownloadTaskResultBody',
    'DownloadTaskResultHeaders',
    'DownloadTaskResultPath',
    'DownloadTaskResultQuery',
    'DownloadTaskResultResponse',
    'DownloadUploadedFileBody',
    'DownloadUploadedFileHeaders',
    'DownloadUploadedFilePath',
    'DownloadUploadedFileQuery',
    'DownloadUploadedFileResponse',
    'DownloadWorkerSourceFileBody',
    'DownloadWorkerSourceFileHeaders',
    'DownloadWorkerSourceFilePath',
    'DownloadWorkerSourceFileQuery',
    'DownloadWorkerSourceFileResponse',
    'DrainWorkerSelfBody',
    'DrainWorkerSelfHeaders',
    'DrainWorkerSelfPath',
    'DrainWorkerSelfQuery',
    'DrainWorkerSelfResponse',
    'GetApiKeyBody',
    'GetApiKeyHeaders',
    'GetApiKeyPath',
    'GetApiKeyQuery',
    'GetApiKeyResponse',
    'GetBackendBody',
    'GetBackendHeaders',
    'GetBackendPath',
    'GetBackendQuery',
    'GetBackendResponse',
    'GetCallbackDeliveryBody',
    'GetCallbackDeliveryHeaders',
    'GetCallbackDeliveryPath',
    'GetCallbackDeliveryQuery',
    'GetCallbackDeliveryResponse',
    'GetCapabilitiesBody',
    'GetCapabilitiesHeaders',
    'GetCapabilitiesPath',
    'GetCapabilitiesQuery',
    'GetCapabilitiesResponse',
    'GetDashboardSummaryBody',
    'GetDashboardSummaryHeaders',
    'GetDashboardSummaryPath',
    'GetDashboardSummaryQuery',
    'GetDashboardSummaryResponse',
    'GetHealthBody',
    'GetHealthHeaders',
    'GetHealthPath',
    'GetHealthQuery',
    'GetHealthResponse',
    'GetMetricsBody',
    'GetMetricsHeaders',
    'GetMetricsPath',
    'GetMetricsQuery',
    'GetMetricsResponse',
    'GetPipelineBody',
    'GetPipelineHeaders',
    'GetPipelinePath',
    'GetPipelineQuery',
    'GetPipelineResponse',
    'GetReadinessBody',
    'GetReadinessHeaders',
    'GetReadinessPath',
    'GetReadinessQuery',
    'GetReadinessResponse',
    'GetSystemInfoBody',
    'GetSystemInfoHeaders',
    'GetSystemInfoPath',
    'GetSystemInfoQuery',
    'GetSystemInfoResponse',
    'GetSystemSettingsBody',
    'GetSystemSettingsHeaders',
    'GetSystemSettingsPath',
    'GetSystemSettingsQuery',
    'GetSystemSettingsResponse',
    'GetTaskBody',
    'GetTaskHeaders',
    'GetTaskPath',
    'GetTaskQuery',
    'GetTaskResponse',
    'GetTaskResultBody',
    'GetTaskResultHeaders',
    'GetTaskResultPath',
    'GetTaskResultQuery',
    'GetTaskResultResponse',
    'GetTaskStageBody',
    'GetTaskStageHeaders',
    'GetTaskStagePath',
    'GetTaskStageQuery',
    'GetTaskStageResponse',
    'GetUploadedFileBody',
    'GetUploadedFileHeaders',
    'GetUploadedFilePath',
    'GetUploadedFileQuery',
    'GetUploadedFileResponse',
    'GetWorkerBody',
    'GetWorkerHeaders',
    'GetWorkerPath',
    'GetWorkerQuery',
    'GetWorkerResponse',
    'HeartbeatWorkerBody',
    'HeartbeatWorkerHeaders',
    'HeartbeatWorkerPath',
    'HeartbeatWorkerQuery',
    'HeartbeatWorkerResponse',
    'InitializeDefaultCatalogBody',
    'InitializeDefaultCatalogHeaders',
    'InitializeDefaultCatalogPath',
    'InitializeDefaultCatalogQuery',
    'InitializeDefaultCatalogResponse',
    'LeaseStagesBody',
    'LeaseStagesHeaders',
    'LeaseStagesPath',
    'LeaseStagesQuery',
    'LeaseStagesResponse',
    'ListApiKeysBody',
    'ListApiKeysHeaders',
    'ListApiKeysPath',
    'ListApiKeysQuery',
    'ListApiKeysResponse',
    'ListBackendsBody',
    'ListBackendsHeaders',
    'ListBackendsPath',
    'ListBackendsQuery',
    'ListBackendsResponse',
    'ListCallbackAttemptsBody',
    'ListCallbackAttemptsHeaders',
    'ListCallbackAttemptsPath',
    'ListCallbackAttemptsQuery',
    'ListCallbackAttemptsResponse',
    'ListCallbackDeliveriesBody',
    'ListCallbackDeliveriesHeaders',
    'ListCallbackDeliveriesPath',
    'ListCallbackDeliveriesQuery',
    'ListCallbackDeliveriesResponse',
    'ListEventsBody',
    'ListEventsHeaders',
    'ListEventsPath',
    'ListEventsQuery',
    'ListEventsResponse',
    'ListPipelinesBody',
    'ListPipelinesHeaders',
    'ListPipelinesPath',
    'ListPipelinesQuery',
    'ListPipelinesResponse',
    'ListTaskArtifactsBody',
    'ListTaskArtifactsHeaders',
    'ListTaskArtifactsPath',
    'ListTaskArtifactsQuery',
    'ListTaskArtifactsResponse',
    'ListTaskEventsBody',
    'ListTaskEventsHeaders',
    'ListTaskEventsPath',
    'ListTaskEventsQuery',
    'ListTaskEventsResponse',
    'ListTaskStagesBody',
    'ListTaskStagesHeaders',
    'ListTaskStagesPath',
    'ListTaskStagesQuery',
    'ListTaskStagesResponse',
    'ListTasksBody',
    'ListTasksHeaders',
    'ListTasksPath',
    'ListTasksQuery',
    'ListTasksResponse',
    'ListWorkersBody',
    'ListWorkersHeaders',
    'ListWorkersPath',
    'ListWorkersQuery',
    'ListWorkersResponse',
    'PublishPipelineBody',
    'PublishPipelineHeaders',
    'PublishPipelinePath',
    'PublishPipelineQuery',
    'PublishPipelineResponse',
    'ReconcileWorkersBody',
    'ReconcileWorkersHeaders',
    'ReconcileWorkersPath',
    'ReconcileWorkersQuery',
    'ReconcileWorkersResponse',
    'RegisterWorkerBody',
    'RegisterWorkerHeaders',
    'RegisterWorkerPath',
    'RegisterWorkerQuery',
    'RegisterWorkerResponse',
    'RenewStageLeaseBody',
    'RenewStageLeaseHeaders',
    'RenewStageLeasePath',
    'RenewStageLeaseQuery',
    'RenewStageLeaseResponse',
    'RetryCallbackDeliveryBody',
    'RetryCallbackDeliveryHeaders',
    'RetryCallbackDeliveryPath',
    'RetryCallbackDeliveryQuery',
    'RetryCallbackDeliveryResponse',
    'RetryTaskBody',
    'RetryTaskHeaders',
    'RetryTaskPath',
    'RetryTaskQuery',
    'RetryTaskResponse',
    'RotateApiKeyBody',
    'RotateApiKeyHeaders',
    'RotateApiKeyPath',
    'RotateApiKeyQuery',
    'RotateApiKeyResponse',
    'RouteTaskBody',
    'RouteTaskHeaders',
    'RouteTaskPath',
    'RouteTaskQuery',
    'RouteTaskResponse',
    'RunRetentionCleanupBody',
    'RunRetentionCleanupHeaders',
    'RunRetentionCleanupPath',
    'RunRetentionCleanupQuery',
    'RunRetentionCleanupResponse',
    'StartStageBody',
    'StartStageHeaders',
    'StartStagePath',
    'StartStageQuery',
    'StartStageResponse',
    'StreamEventsBody',
    'StreamEventsHeaders',
    'StreamEventsPath',
    'StreamEventsQuery',
    'StreamEventsResponse',
    'StreamTaskEventsBody',
    'StreamTaskEventsHeaders',
    'StreamTaskEventsPath',
    'StreamTaskEventsQuery',
    'StreamTaskEventsResponse',
    'TestCallbackBody',
    'TestCallbackHeaders',
    'TestCallbackPath',
    'TestCallbackQuery',
    'TestCallbackResponse',
    'TestPipelineBody',
    'TestPipelineHeaders',
    'TestPipelinePath',
    'TestPipelineQuery',
    'TestPipelineResponse',
    'UpdateApiKeyBody',
    'UpdateApiKeyHeaders',
    'UpdateApiKeyPath',
    'UpdateApiKeyQuery',
    'UpdateApiKeyResponse',
    'UpdateBackendBody',
    'UpdateBackendHeaders',
    'UpdateBackendPath',
    'UpdateBackendQuery',
    'UpdateBackendResponse',
    'UpdateStageProgressBody',
    'UpdateStageProgressHeaders',
    'UpdateStageProgressPath',
    'UpdateStageProgressQuery',
    'UpdateStageProgressResponse',
    'UpdateSystemSettingsBody',
    'UpdateSystemSettingsHeaders',
    'UpdateSystemSettingsPath',
    'UpdateSystemSettingsQuery',
    'UpdateSystemSettingsResponse',
    'UpdateWorkerBody',
    'UpdateWorkerHeaders',
    'UpdateWorkerPath',
    'UpdateWorkerQuery',
    'UpdateWorkerResponse',
    'UploadFileBody',
    'UploadFileHeaders',
    'UploadFilePath',
    'UploadFileQuery',
    'UploadFileResponse',
    'UploadStageArtifactBody',
    'UploadStageArtifactHeaders',
    'UploadStageArtifactPath',
    'UploadStageArtifactQuery',
    'UploadStageArtifactResponse',
    'ValidatePipelineBody',
    'ValidatePipelineHeaders',
    'ValidatePipelinePath',
    'ValidatePipelineQuery',
    'ValidatePipelineResponse',
]

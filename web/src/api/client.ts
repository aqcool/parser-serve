import { useConnectionStore } from "@/stores/connection"
import {
  GeneratedApiError,
  ParserServeClient,
  type GeneratedOperationArgs,
} from "./generated-client"
import type {
  components,
  OperationId,
  OperationResponse,
  operations,
} from "./generated"

type OperationBody<T extends OperationId> = Exclude<
  operations[T]["requestBody"],
  undefined
>

export type PageInfo = { has_more: boolean; next_cursor: string | null }
export type ApiResponse<T> = { request_id: string; data: T }
export type ListResponse<T> = { request_id: string; items: T[]; page: PageInfo }
export type TaskStatus =
  | "pending"
  | "leased"
  | "running"
  | "succeeded"
  | "failed"
  | "cancelled"

export type Task = {
  task_id: string
  status: TaskStatus
  progress_percent: number
  source: TaskSource
  source_metadata: SourceMetadata | null
  options: TaskOptions
  pipeline_id: string | null
  pipeline_version: number | null
  stages: Stage[]
  client_reference: string | null
  created_at: string
  started_at: string | null
  completed_at: string | null
  result_uri: string | null
  error: ErrorDetail | null
}

export type TaskSource = OperationBody<"create_task">["source"]

export type ErrorDetail = {
  code: string
  message: string
  retryable: boolean
  field_violations: Array<{ field: string; reason: string }>
  context: Record<string, unknown>
}

export type SourceMetadata = {
  filename: string | null
  mime_type: string
  media_category: string
  size_bytes: number | null
  sha256: string | null
  attributes: Record<string, unknown>
}

export type StageStatus =
  | "pending"
  | "leased"
  | "running"
  | "succeeded"
  | "failed"
  | "cancelled"
  | "skipped"

export type Stage = {
  stage_id: string
  name: string
  position: number
  depends_on: string[]
  optional: boolean
  timeout_seconds: number | null
  status: StageStatus
  progress_percent: number
  backend_id: string | null
  backend_version: string | null
  backend_candidates: string[]
  worker_id: string | null
  runtime: string | null
  required_runtimes: string[]
  attempt: number
  total_attempts: number
  maximum_attempts: number
  created_at: string
  started_at: string | null
  completed_at: string | null
  result_uri: string | null
  error: ErrorDetail | null
}

export type StageListParams = {
  statuses?: StageStatus[]
  backend_id?: string
  worker_id?: string
  limit?: number
  cursor?: string
  sort_by?: "position" | "created_at"
  sort_direction?: "asc" | "desc"
}

export type Artifact = {
  artifact_id: string
  type:
    | "original"
    | "converted_document"
    | "extracted_image"
    | "keyframe"
    | "audio_track"
    | "subtitle"
    | "result_json"
    | "result_text"
    | "result_markdown"
    | "other"
  filename: string
  mime_type: string
  size_bytes: number
  sha256: string
  storage_uri: string
  created_at: string
  expires_at: string | null
  metadata: Record<string, unknown>
}

export type ArtifactListParams = {
  types?: Artifact["type"][]
  mime_type?: string
  limit?: number
  cursor?: string
  sort_by?: "created_at" | "filename" | "size_bytes"
  sort_direction?: "asc" | "desc"
}

export type ArtifactDownload = {
  url: string
  method: "GET"
  expires_at: string
}

export type BlockLocation = {
  page_number?: number
  slide_number?: number
  sheet_name?: string
  bounding_box?: {
    left: number
    top: number
    right: number
    bottom: number
  }
  start_ms?: number
  end_ms?: number
}

type BaseBlock = {
  block_id: string
  metadata: Record<string, unknown>
}

export type ContentBlock =
  | (BaseBlock & {
      type: "text"
      text: string
      location: BlockLocation | null
    })
  | (BaseBlock & {
      type: "heading"
      text: string
      level: number
      location: BlockLocation | null
    })
  | (BaseBlock & {
      type: "table"
      rows: string[][]
      location: BlockLocation | null
    })
  | (BaseBlock & {
      type: "image"
      artifact_id: string
      caption: string | null
      ocr_text: string | null
      location: BlockLocation | null
    })
  | (BaseBlock & {
      type: "transcript"
      text: string
      start_ms: number
      end_ms: number
      speaker: string | null
      language: string | null
    })
  | (BaseBlock & {
      type: "keyframe"
      artifact_id: string
      timestamp_ms: number
      caption: string | null
      ocr_text: string | null
    })
  | (BaseBlock & { type: "link"; url: string; text: string | null })

export type ParseResult = {
  schema_version: string
  task_id: string
  source: SourceMetadata
  metadata: {
    title: string | null
    language: string | null
    page_count: number | null
    duration_ms: number | null
    width_pixels: number | null
    height_pixels: number | null
    attributes: Record<string, unknown>
  }
  blocks: ContentBlock[]
  artifacts: Artifact[]
  warnings: Array<{
    code: string
    message: string
    stage_id: string | null
    context: Record<string, unknown>
  }>
  created_at: string
}

export type TaskOptionsInput = NonNullable<
  OperationBody<"create_task">["options"]
>

export type TaskOptions = {
  pipeline_id: string | null
  pipeline_version: number | null
  backend_name: string | null
  priority: number
  timeout_seconds: number | null
  device: {
    strategy: "auto" | "prefer" | "require"
    runtimes: string[]
    minimum_memory_bytes: number | null
    worker_labels: Record<string, string>
  }
  features: TaskOptionsInput["features"]
}

export type CreateTaskInput = OperationBody<"create_task">

export type PipelineTestInput = OperationBody<"test_pipeline">

export type Worker = {
  worker_id: string
  name: string
  status: string
  enabled: boolean
  maximum_concurrency: number
  scheduling_weight: number
  hostname: string
  devices: Array<{ runtime: string; vendor: string; model: string }>
  backends: Array<{ name: string; version: string }>
  resources: {
    cpu_percent: number
    memory_used_bytes: number
    memory_total_bytes: number
    running_tasks: number
    leased_tasks: number
    health_checks: Array<{
      name: string
      healthy: boolean
      message: string | null
    }>
  } | null
  last_heartbeat_at: string | null
}

export type WorkerListParams =
  operations["list_workers"]["parameters"]["query"]

export type BackendCapability = components["schemas"]["BackendCapability"]

export type Backend = {
  backend_id: string
  capability: BackendCapability
  status: "enabled" | "disabled" | "unhealthy"
  execution_mode: "local" | "remote"
  default_timeout_seconds: number
  maximum_attempts: number
  scheduling_weight: number
  remote_url: string | null
  configuration: Record<string, unknown>
  created_at: string
  updated_at: string
}

export type BackendListParams =
  operations["list_backends"]["parameters"]["query"]

export type PipelineStage = {
  name: string
  backend: {
    preferred: string
    fallbacks: string[]
    required_runtimes: string[]
  }
  depends_on: string[]
  timeout_seconds: number
  retry: {
    maximum_attempts: number
    initial_delay_seconds: number
    maximum_delay_seconds: number
    multiplier: number
  }
  optional: boolean
  parameters: Record<string, unknown>
}

export type Pipeline = {
  pipeline_id: string
  name: string
  version: number
  status: "draft" | "published" | "disabled" | "archived"
  media_categories: string[]
  mime_types: string[]
  routing_priority: number
  stages: PipelineStage[]
  created_at: string
  published_at: string | null
}

export type PipelineListParams =
  operations["list_pipelines"]["parameters"]["query"]

export type CreatePipeline = OperationBody<"create_pipeline">

export type PipelineValidation = {
  valid: boolean
  violations: Array<{ location: string; message: string }>
}

export type DefaultCatalogResult = {
  backend_ids_created: string[]
  backend_ids_existing: string[]
  pipelines: Array<{
    pipeline_id: string
    version: number
    status: Pipeline["status"]
    action: "created" | "published" | "unchanged" | "draft_unavailable"
    violations: Array<{ location: string; message: string }>
  }>
}

export type CallbackDelivery = {
  delivery_id: string
  event: {
    type: string
    task_id: string
    occurred_at: string
    payload: { type: string }
  }
  target_url: string
  status:
    | "pending"
    | "delivering"
    | "succeeded"
    | "retry_wait"
    | "failed"
    | "cancelled"
  attempt: number
  maximum_attempts: number
  response_status_code: number | null
  response_summary: string | null
  next_attempt_at: string | null
  created_at: string
  updated_at: string
}

export type CallbackAttempt = {
  attempt_id: string
  delivery_id: string
  sequence: number
  attempt_number: number
  delivered: boolean
  response_status_code: number | null
  response_summary: string | null
  duration_ms: number
  error: { code: string; message: string; retryable: boolean } | null
  started_at: string
  completed_at: string
}

export type CallbackListParams =
  operations["list_callback_deliveries"]["parameters"]["query"]

export type CallbackAttemptListParams =
  operations["list_callback_attempts"]["parameters"]["query"]

export type CallbackTestResult = {
  delivered: boolean
  response_status_code: number | null
  duration_ms: number
  error: { code: string; message: string; retryable: boolean } | null
}

export type ApiKeySummary = {
  api_key_id: string
  name: string
  kind: "ordinary" | "worker"
  worker_id: string | null
  prefix: string
  status: "active" | "disabled" | "expired"
  created_at: string
  updated_at: string
  expires_at: string | null
  last_used_at: string | null
}

export type ApiKeyListParams =
  operations["list_api_keys"]["parameters"]["query"]

export type NewApiKey = {
  api_key: string
  summary: ApiKeySummary
}

export type SystemInfo = {
  name: string
  version: string
  api_version: string
  result_schema_version: string
  build_commit: string | null
  build_time: string | null
}

export type SettingKey =
  | "maximum_upload_bytes"
  | "maximum_result_json_bytes"
  | "callback_maximum_attempts"

export type SystemSetting = {
  key: SettingKey
  value: number
  source: "deployment" | "database"
  updated_at: string | null
}

export type RetentionRun = {
  dry_run: boolean
  cutoff_time: string
  uploaded_files_selected: number
  uploaded_files_skipped_active: number
  artifacts_selected: number
  artifacts_skipped_active: number
  events_selected: number
  storage_delete_failures: number
}

export type Capabilities = {
  schema_version: string
  media_categories: string[]
  mime_types: string[]
  runtimes: Array<{
    runtime: string
    vendor: string
    available_workers: number
    available_devices: number
  }>
  pipelines: string[]
  backends: string[]
  maximum_upload_bytes: number
}

export type Dashboard = {
  generated_at: string
  tasks: {
    total_tasks: number
    pending_tasks: number
    running_tasks: number
    succeeded_tasks: number
    failed_tasks: number
    cancelled_tasks: number
    success_rate: number
    average_wait_ms: number
    average_execution_ms: number
    p50_execution_ms: number
    p95_execution_ms: number
    p99_execution_ms: number
  }
  workers: {
    total_workers: number
    online_workers: number
    busy_workers: number
    draining_workers: number
    offline_workers: number
    unhealthy_workers: number
    total_concurrency: number
    used_concurrency: number
  }
  callbacks: {
    total_deliveries: number
    successful_deliveries: number
    failed_deliveries: number
    pending_retries: number
    success_rate: number
  }
  storage: {
    objects: number
    original_bytes: number
    artifact_bytes: number
    result_bytes: number
  }
  backends: Array<{
    backend_id: string
    calls: number
    failures: number
    timeouts: number
    fallbacks: number
    average_duration_ms: number
  }>
  runtimes: Array<{
    runtime: string
    workers: number
    devices: number
    average_utilization_percent: number | null
    memory_used_bytes: number | null
    memory_total_bytes: number | null
  }>
  series: Array<{
    name: string
    unit: string
    points: Array<{ timestamp: string; value: number }>
  }>
}

export { GeneratedApiError as ApiClientError }

function generatedRequest<T extends OperationId>(
  operationId: T,
  args: GeneratedOperationArgs<T> = {},
): Promise<OperationResponse<T>> {
  const connection = useConnectionStore()
  return new ParserServeClient({
    baseUrl: connection.apiUrl,
    apiKey: connection.apiKey,
  }).request(operationId, args)
}

export async function apiFetch(path: string, init: RequestInit = {}) {
  const connection = useConnectionStore()
  const headers = new Headers(init.headers)
  headers.set("Authorization", `Bearer ${connection.apiKey}`)
  return fetch(`${connection.apiUrl}${path}`, { ...init, headers })
}

export async function downloadAuthenticated(path: string, filename: string) {
  const response = await apiFetch(path)
  if (!response.ok) {
    throw new GeneratedApiError(
      response.status,
      "DOWNLOAD_FAILED",
      `Download failed with HTTP ${response.status}`,
    )
  }
  const objectUrl = URL.createObjectURL(await response.blob())
  const anchor = document.createElement("a")
  anchor.href = objectUrl
  anchor.download = filename
  anchor.click()
  URL.revokeObjectURL(objectUrl)
}

function downloadBlob(blob: Blob, filename: string) {
  const objectUrl = URL.createObjectURL(blob)
  const anchor = document.createElement("a")
  anchor.href = objectUrl
  anchor.download = filename
  anchor.click()
  URL.revokeObjectURL(objectUrl)
}

function createTaskRequest(request: CreateTaskInput) {
  return generatedRequest("create_task", { body: request })
}

export const parserApi = {
  capabilities: () => generatedRequest("get_capabilities"),
  dashboard: () =>
    generatedRequest("get_dashboard_summary", { query: { interval: "1h" } }),
  tasks: (limit = 50) => generatedRequest("list_tasks", { query: { limit } }),
  task: (taskId: string) =>
    generatedRequest("get_task", { path: { task_id: taskId } }),
  taskStages: (taskId: string, params: StageListParams = { limit: 200 }) =>
    generatedRequest("list_task_stages", {
      path: { task_id: taskId },
      query: params,
    }),
  taskArtifacts: (
    taskId: string,
    params: ArtifactListParams = { limit: 200 },
  ) =>
    generatedRequest("list_task_artifacts", {
      path: { task_id: taskId },
      query: params,
    }),
  taskResult: (taskId: string) =>
    generatedRequest("get_task_result", { path: { task_id: taskId } }),
  cancelTask: (taskId: string) =>
    generatedRequest("cancel_task", { path: { task_id: taskId } }),
  retryTask: (taskId: string) =>
    generatedRequest("retry_task", { path: { task_id: taskId } }),
  downloadArtifact: (taskId: string, artifact: Artifact) =>
    generatedRequest("download_task_artifact", {
      path: { task_id: taskId, artifact_id: artifact.artifact_id },
    }).then((blob) => downloadBlob(blob, artifact.filename)),
  artifactDownloadUrl: (taskId: string, artifactId: string) =>
    generatedRequest("create_task_artifact_download_url", {
      path: { task_id: taskId, artifact_id: artifactId },
    }),
  workers: (params: WorkerListParams = { limit: 100 }) =>
    generatedRequest("list_workers", { query: params }),
  backends: (params: BackendListParams = { limit: 100 }) =>
    generatedRequest("list_backends", { query: params }),
  createBackend: (request: {
    capability: BackendCapability
    execution_mode: "local" | "remote"
    default_timeout_seconds: number
    maximum_attempts: number
    scheduling_weight: number
    remote_url?: string
  }) =>
    generatedRequest("create_backend", { body: request }),
  updateBackend: (
    backendId: string,
    update: {
      enabled?: boolean
      default_timeout_seconds?: number
      maximum_attempts?: number
      scheduling_weight?: number
    },
  ) =>
    generatedRequest("update_backend", {
      path: { backend_id: backendId },
      body: update,
    }),
  pipelines: (params: PipelineListParams = { limit: 100 }) =>
    generatedRequest("list_pipelines", { query: params }),
  createPipeline: (request: CreatePipeline) =>
    generatedRequest("create_pipeline", { body: request }),
  validatePipeline: (pipelineId: string, version: number) =>
    generatedRequest("validate_pipeline", {
      path: { pipeline_id: pipelineId, version },
    }),
  testPipeline: (
    pipelineId: string,
    version: number,
    request: PipelineTestInput,
  ) =>
    generatedRequest("test_pipeline", {
      path: { pipeline_id: pipelineId, version },
      body: request,
    }),
  publishPipeline: (pipelineId: string, version: number) =>
    generatedRequest("publish_pipeline", {
      path: { pipeline_id: pipelineId, version },
    }),
  initializeDefaults: () =>
    generatedRequest("initialize_default_catalog", {
      body: {
        include_builtin_backends: true,
        publish_valid_pipelines: true,
      },
    }),
  callbacks: (params: CallbackListParams = { limit: 100 }) =>
    generatedRequest("list_callback_deliveries", { query: params }),
  retryCallback: (deliveryId: string) =>
    generatedRequest("retry_callback_delivery", {
      path: { delivery_id: deliveryId },
    }),
  callbackAttempts: (
    deliveryId: string,
    params: CallbackAttemptListParams = { limit: 100 },
  ) =>
    generatedRequest("list_callback_attempts", {
      path: { delivery_id: deliveryId },
      query: params,
    }),
  testCallback: (url: string, secret?: string) =>
    generatedRequest("test_callback", {
      body: {
        url,
        ...(secret ? { secret } : {}),
        metadata: { source: "parser-serve-web" },
      },
    }),
  apiKeys: (params: ApiKeyListParams = { limit: 100 }) =>
    generatedRequest("list_api_keys", { query: params }),
  createApiKey: (request: {
    name: string
    kind: "ordinary" | "worker"
    worker_id?: string
    expires_at?: string
  }) =>
    generatedRequest("create_api_key", { body: request }),
  updateApiKey: (apiKeyId: string, update: { enabled?: boolean; name?: string }) =>
    generatedRequest("update_api_key", {
      path: { api_key_id: apiKeyId },
      body: update,
    }),
  rotateApiKey: (apiKeyId: string) =>
    generatedRequest("rotate_api_key", { path: { api_key_id: apiKeyId } }),
  deleteApiKey: (apiKeyId: string) =>
    generatedRequest("delete_api_key", { path: { api_key_id: apiKeyId } }),
  systemInfo: () => generatedRequest("get_system_info"),
  systemSettings: () => generatedRequest("get_system_settings"),
  updateSystemSettings: (
    settings: Array<{ key: SettingKey; value: number }>,
  ) =>
    generatedRequest("update_system_settings", { body: { settings } }),
  runRetention: (dryRun: boolean, maximumRecords = 500) =>
    generatedRequest("run_retention_cleanup", {
      body: {
        dry_run: dryRun,
        maximum_records: maximumRecords,
      },
    }),
  updateWorker: (
    workerId: string,
    update: {
      enabled?: boolean
      draining?: boolean
      maximum_concurrency?: number
      scheduling_weight?: number
      labels?: Record<string, string>
    },
  ) =>
    generatedRequest("update_worker", {
      path: { worker_id: workerId },
      body: update,
    }),
  createTask: createTaskRequest,
  createTextTask: (text: string, filename: string) =>
    createTaskRequest({
      source: { type: "text", text, filename, mime_type: "text/plain" },
      options: {
        priority: 0,
        device: { strategy: "auto", runtimes: [], worker_labels: {} },
        features: {
          extract_text: true,
          extract_tables: true,
          extract_images: false,
          run_ocr: false,
          generate_captions: false,
          transcribe_audio: false,
          extract_keyframes: false,
        },
      },
    }),
  uploadFile: (file: File) => {
    const body = new FormData()
    body.set("file", file)
    return generatedRequest("upload_file", { body })
  },
  createFileTask: (fileId: string) =>
    createTaskRequest({
      source: { type: "uploaded_file", file_id: fileId },
      options: {
        priority: 0,
        device: { strategy: "auto", runtimes: [], worker_labels: {} },
        features: {
          extract_text: true,
          extract_tables: true,
          extract_images: false,
          run_ocr: false,
          generate_captions: false,
          transcribe_audio: false,
          extract_keyframes: false,
        },
      },
    }),
}

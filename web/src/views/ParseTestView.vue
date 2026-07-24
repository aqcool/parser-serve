<script setup lang="ts">
import { useQuery } from "@tanstack/vue-query"
import {
  Copy,
  Database,
  FileUp,
  Globe2,
  Play,
  RotateCcw,
  SlidersHorizontal,
  Type,
} from "lucide-vue-next"
import { computed, reactive, ref } from "vue"
import { useRouter } from "vue-router"

import {
  parserApi,
  type CreateTaskInput,
  type TaskSource,
} from "@/api/client"
import Badge from "@/components/ui/Badge.vue"
import Button from "@/components/ui/Button.vue"
import Card from "@/components/ui/Card.vue"
import Input from "@/components/ui/Input.vue"
import { useConnectionStore } from "@/stores/connection"

type SourceMode = "text" | "file" | "url" | "object_storage"

const router = useRouter()
const connection = useConnectionStore()
const mode = ref<SourceMode>("text")
const text = ref("")
const filename = ref("input.txt")
const textMimeType = ref("text/plain")
const file = ref<File | null>(null)
const sourceUrl = ref("")
const objectUri = ref("s3://bucket/path/to/file.pdf")
const objectVersionId = ref("")
const pipeline = ref("")
const backend = ref("")
const strategy = ref<"auto" | "prefer" | "require">("auto")
const selectedRuntimes = ref<string[]>([])
const priority = ref("0")
const timeoutSeconds = ref("")
const clientReference = ref("")
const features = reactive({
  extract_text: true,
  extract_tables: true,
  extract_images: false,
  run_ocr: false,
  generate_captions: false,
  transcribe_audio: false,
  extract_keyframes: false,
})
const featureOptions = [
  { key: "extract_text", label: "提取文本" },
  { key: "extract_tables", label: "提取表格" },
  { key: "extract_images", label: "提取图片" },
  { key: "run_ocr", label: "运行 OCR" },
  { key: "generate_captions", label: "生成描述" },
  { key: "transcribe_audio", label: "语音转写" },
  { key: "extract_keyframes", label: "提取关键帧" },
] as const
const submitting = ref(false)
const error = ref("")
const message = ref("")
const createdTaskId = ref("")

const pipelines = useQuery({
  queryKey: ["pipelines", "parse-test"],
  queryFn: parserApi.pipelines,
})
const backends = useQuery({
  queryKey: ["backends", "parse-test"],
  queryFn: parserApi.backends,
})
const capabilities = useQuery({
  queryKey: ["capabilities"],
  queryFn: parserApi.capabilities,
})
const publishedPipelines = computed(() =>
  (pipelines.data.value?.items ?? []).filter(
    (item) => item.status === "published",
  ),
)
const enabledBackends = computed(() =>
  (backends.data.value?.items ?? []).filter(
    (item) => item.status === "enabled",
  ),
)
const runtimes = computed(
  () => capabilities.data.value?.data.runtimes ?? [],
)

const sourcePayload = computed<TaskSource>(() => {
  if (mode.value === "text") {
    return {
      type: "text",
      text: text.value,
      filename: filename.value || undefined,
      mime_type: textMimeType.value,
    }
  }
  if (mode.value === "url") {
    return { type: "url", url: sourceUrl.value }
  }
  if (mode.value === "object_storage") {
    return {
      type: "object_storage",
      uri: objectUri.value,
      ...(objectVersionId.value
        ? { version_id: objectVersionId.value }
        : {}),
    }
  }
  return { type: "uploaded_file", file_id: "<UPLOADED_FILE_ID>" }
})

const requestPayload = computed<CreateTaskInput>(() => {
  const selectedPipeline = publishedPipelines.value.find(
    (item) => `${item.pipeline_id}@${item.version}` === pipeline.value,
  )
  return {
    source: sourcePayload.value,
    options: {
      ...(selectedPipeline
        ? {
            pipeline_id: selectedPipeline.pipeline_id,
            pipeline_version: selectedPipeline.version,
          }
        : {}),
      ...(backend.value ? { backend_name: backend.value } : {}),
      priority: Number(priority.value || 0),
      ...(timeoutSeconds.value
        ? { timeout_seconds: Number(timeoutSeconds.value) }
        : {}),
      device: {
        strategy: strategy.value,
        runtimes:
          strategy.value === "auto" ? [] : [...selectedRuntimes.value],
        worker_labels: {},
      },
      features: { ...features },
    },
    ...(clientReference.value
      ? { client_reference: clientReference.value }
      : {}),
  }
})

const requestJson = computed(() =>
  JSON.stringify(requestPayload.value, null, 2),
)
const curlCommand = computed(() => {
  const taskCommand = [
    `curl -X POST '${connection.apiUrl}/api/v1/tasks'`,
    "  -H 'Authorization: Bearer <API_KEY>'",
    "  -H 'Content-Type: application/json'",
    `  --data-raw '${requestJson.value.replaceAll("'", "'\"'\"'")}'`,
  ].join(" \\\n")
  if (mode.value !== "file") return taskCommand
  return [
    `curl -X POST '${connection.apiUrl}/api/v1/files' \\`,
    "  -H 'Authorization: Bearer <API_KEY>' \\",
    "  -F 'file=@/path/to/local-file'",
    "",
    "# 将上传响应中的 data.file_id 替换到下面请求的 <UPLOADED_FILE_ID>",
    taskCommand,
  ].join("\n")
})

function pickFile(event: Event) {
  file.value = (event.target as HTMLInputElement).files?.[0] ?? null
}

function validateRequest() {
  if (mode.value === "text" && !text.value.trim()) {
    throw new Error("请输入要解析的文本")
  }
  if (mode.value === "file" && !file.value) {
    throw new Error("请选择文件")
  }
  if (mode.value === "url" && !sourceUrl.value) {
    throw new Error("请输入网页 URL")
  }
  if (mode.value === "object_storage" && !objectUri.value.startsWith("s3://")) {
    throw new Error("对象存储 URI 必须使用 s3://")
  }
  if (
    strategy.value !== "auto" &&
    selectedRuntimes.value.length === 0
  ) {
    throw new Error("Prefer 或 Require 策略至少选择一个 Runtime")
  }
}

async function submit() {
  error.value = ""
  message.value = ""
  createdTaskId.value = ""
  submitting.value = true
  try {
    validateRequest()
    const request = JSON.parse(requestJson.value) as CreateTaskInput
    if (mode.value === "file" && file.value) {
      const uploaded = await parserApi.uploadFile(file.value)
      request.source = {
        type: "uploaded_file",
        file_id: uploaded.data.file_id,
      }
    }
    createdTaskId.value = (await parserApi.createTask(request)).data.task_id
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "提交失败"
  } finally {
    submitting.value = false
  }
}

async function copy(value: string, label: string) {
  try {
    await navigator.clipboard.writeText(value)
    message.value = `${label}已复制`
  } catch {
    error.value = "浏览器未授予剪贴板权限"
  }
}

function resetSource() {
  text.value = ""
  file.value = null
  sourceUrl.value = ""
  objectVersionId.value = ""
  error.value = ""
  message.value = ""
}
</script>

<template>
  <div class="space-y-7">
    <header>
      <p class="eyebrow">Parser laboratory</p>
      <h1 class="page-title">解析测试</h1>
      <p class="page-subtitle">提交文本、文件、网页或对象存储内容，并验证路由与异构 Worker 链路。</p>
    </header>

    <div class="grid gap-5 xl:grid-cols-[minmax(0,1fr)_480px]">
      <div class="space-y-5">
        <Card class="overflow-hidden">
          <div class="flex flex-wrap gap-1 border-b border-border bg-muted/35 p-2">
            <button type="button" class="tab-button" :class="{ 'tab-active': mode === 'text' }" @click="mode = 'text'"><Type class="size-4" />文本</button>
            <button type="button" class="tab-button" :class="{ 'tab-active': mode === 'file' }" @click="mode = 'file'"><FileUp class="size-4" />文件</button>
            <button type="button" class="tab-button" :class="{ 'tab-active': mode === 'url' }" @click="mode = 'url'"><Globe2 class="size-4" />网页 URL</button>
            <button type="button" class="tab-button" :class="{ 'tab-active': mode === 'object_storage' }" @click="mode = 'object_storage'"><Database class="size-4" />S3 / MinIO</button>
          </div>
          <form class="space-y-5 p-5 md:p-7" @submit.prevent="submit">
            <template v-if="mode === 'text'">
              <div class="grid gap-4 md:grid-cols-2">
                <label class="block text-sm font-semibold">文件名<Input v-model="filename" class="mt-2" placeholder="input.txt" /></label>
                <label class="block text-sm font-semibold">MIME<select v-model="textMimeType" class="mt-2 h-10 w-full rounded-lg border border-input bg-background px-3 text-sm outline-none focus:ring-2 focus:ring-ring"><option value="text/plain">text/plain</option><option value="text/markdown">text/markdown</option><option value="text/html">text/html</option><option value="application/json">application/json</option></select></label>
              </div>
              <label class="block text-sm font-semibold">文本内容<textarea v-model="text" rows="12" class="mt-2 w-full resize-y rounded-xl border border-input bg-background p-4 font-mono text-sm leading-6 outline-none focus:ring-2 focus:ring-ring" placeholder="粘贴 Markdown、纯文本、HTML 或 JSON…" /></label>
            </template>
            <template v-else-if="mode === 'file'">
              <label class="grid min-h-72 cursor-pointer place-items-center rounded-2xl border-2 border-dashed border-border bg-muted/25 p-8 text-center transition hover:border-primary/50 hover:bg-primary/[0.03]">
                <input type="file" class="sr-only" @change="pickFile" />
                <div><div class="mx-auto grid size-14 place-items-center rounded-2xl bg-primary text-primary-foreground"><FileUp class="size-6" /></div><p class="mt-4 font-semibold">{{ file?.name ?? "选择待解析文件" }}</p><p class="mt-2 text-sm text-muted-foreground">Office、PDF、图片、音频或视频</p><Badge v-if="file" class="mt-3">{{ (file.size / 1024 / 1024).toFixed(2) }} MB</Badge></div>
              </label>
            </template>
            <template v-else-if="mode === 'url'">
              <label class="block text-sm font-semibold">公开网页 URL<Input v-model="sourceUrl" type="url" class="mt-2" placeholder="https://example.com/article" /></label>
              <p class="rounded-xl bg-muted p-3 text-xs leading-5 text-muted-foreground">服务端会执行逐跳重定向和公网地址校验；不允许凭证、localhost 或私网目标。</p>
            </template>
            <template v-else>
              <label class="block text-sm font-semibold">S3 URI<Input v-model="objectUri" class="mt-2" placeholder="s3://bucket/path/to/file.pdf" /></label>
              <label class="block text-sm font-semibold">Version ID（可选）<Input v-model="objectVersionId" class="mt-2" placeholder="对象版本 ID" /></label>
              <p class="rounded-xl bg-muted p-3 text-xs leading-5 text-muted-foreground">目标 Bucket 必须位于 Worker 的 `allowed_s3_buckets` 白名单中；MinIO Endpoint 由 Worker 部署配置提供。</p>
            </template>

            <p v-if="error" role="alert" class="rounded-xl bg-red-50 p-3 text-sm text-red-700">{{ error }}</p>
            <p v-if="message" class="rounded-xl bg-emerald-50 p-3 text-sm text-emerald-800">{{ message }}</p>
            <div v-if="createdTaskId" class="flex flex-col gap-3 rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-900 sm:flex-row sm:items-center sm:justify-between">
              <span>任务已提交：<strong class="font-mono">{{ createdTaskId }}</strong></span>
              <Button size="sm" variant="outline" @click="router.push('/tasks')">查看任务</Button>
            </div>
            <div class="flex justify-end gap-2">
              <Button variant="ghost" @click="resetSource"><RotateCcw class="size-4" />清空 Source</Button>
              <Button type="submit" :disabled="submitting"><Play class="size-4" />{{ submitting ? "正在提交…" : "开始解析" }}</Button>
            </div>
          </form>
        </Card>

        <Card class="p-5 md:p-7">
          <div class="flex items-center gap-3"><div class="rounded-xl bg-primary/8 p-2.5 text-primary"><SlidersHorizontal class="size-5" /></div><div><h2 class="section-title">路由与解析选项</h2><p class="text-sm text-muted-foreground">留空时使用服务端自动路由。</p></div></div>
          <div class="mt-5 grid gap-4 md:grid-cols-2">
            <label class="text-sm font-semibold">Pipeline<select v-model="pipeline" class="mt-2 h-10 w-full rounded-lg border border-input bg-background px-3 text-sm"><option value="">自动选择</option><option v-for="item in publishedPipelines" :key="`${item.pipeline_id}@${item.version}`" :value="`${item.pipeline_id}@${item.version}`">{{ item.name }} · {{ item.pipeline_id }}@{{ item.version }}</option></select></label>
            <label class="text-sm font-semibold">Backend<select v-model="backend" class="mt-2 h-10 w-full rounded-lg border border-input bg-background px-3 text-sm"><option value="">Pipeline 默认</option><option v-for="item in enabledBackends" :key="item.backend_id" :value="item.capability.name">{{ item.capability.name }}@{{ item.capability.version }}</option></select></label>
            <label class="text-sm font-semibold">硬件策略<select v-model="strategy" class="mt-2 h-10 w-full rounded-lg border border-input bg-background px-3 text-sm"><option value="auto">Auto</option><option value="prefer">Prefer</option><option value="require">Require</option></select></label>
            <div><p class="text-sm font-semibold">Runtime</p><div class="mt-2 flex min-h-10 flex-wrap items-center gap-3 rounded-lg border border-input px-3"><label v-for="runtime in runtimes" :key="runtime.runtime" class="flex items-center gap-1.5 text-xs"><input v-model="selectedRuntimes" type="checkbox" :value="runtime.runtime" :disabled="strategy === 'auto'" />{{ runtime.runtime }} ({{ runtime.available_devices }})</label><span v-if="!runtimes.length" class="text-xs text-muted-foreground">暂无在线 Runtime</span></div></div>
            <label class="text-sm font-semibold">优先级（-100 至 100）<Input v-model="priority" type="number" class="mt-2" /></label>
            <label class="text-sm font-semibold">任务超时秒数（可选）<Input v-model="timeoutSeconds" type="number" class="mt-2" placeholder="使用 Pipeline 默认值" /></label>
            <label class="text-sm font-semibold md:col-span-2">外部引用（可选）<Input v-model="clientReference" class="mt-2" placeholder="来自业务系统的追踪 ID" /></label>
          </div>
          <div class="mt-5 border-t border-border pt-5"><p class="text-sm font-semibold">解析特性</p><div class="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4"><label v-for="option in featureOptions" :key="option.key" class="flex items-center gap-2 rounded-lg bg-muted/45 px-3 py-2 text-xs"><input v-model="features[option.key]" type="checkbox" />{{ option.label }}</label></div></div>
        </Card>
      </div>

      <div class="space-y-5">
        <Card class="overflow-hidden">
          <div class="flex items-center justify-between border-b border-border p-4"><div><h2 class="section-title">请求 JSON</h2><p class="text-xs text-muted-foreground">严格对应 CreateTaskRequest</p></div><Button size="sm" variant="outline" @click="copy(requestJson, '请求 JSON')"><Copy class="size-3.5" />复制</Button></div>
          <pre class="max-h-[480px] overflow-auto bg-[oklch(.16_.025_165)] p-4 text-xs leading-5 text-emerald-100">{{ requestJson }}</pre>
        </Card>
        <Card class="overflow-hidden">
          <div class="flex items-center justify-between border-b border-border p-4"><div><h2 class="section-title">cURL</h2><p class="text-xs text-muted-foreground">不会写入当前会话的真实 API Key</p></div><Button size="sm" variant="outline" @click="copy(curlCommand, 'cURL')"><Copy class="size-3.5" />复制</Button></div>
          <pre class="max-h-[360px] overflow-auto whitespace-pre-wrap bg-muted/45 p-4 text-xs leading-5">{{ curlCommand }}</pre>
        </Card>
      </div>
    </div>
  </div>
</template>

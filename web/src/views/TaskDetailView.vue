<script setup lang="ts">
import { useQuery, useQueryClient } from "@tanstack/vue-query"
import {
  ArrowLeft,
  Ban,
  Download,
  Eye,
  FileJson,
  Radio,
  RefreshCw,
  RotateCcw,
} from "lucide-vue-next"
import { computed, onBeforeUnmount, ref } from "vue"
import { RouterLink, useRoute } from "vue-router"

import {
  apiFetch,
  parserApi,
  type Artifact,
  type ContentBlock,
  type StageStatus,
  type TaskStatus,
} from "@/api/client"
import Badge from "@/components/ui/Badge.vue"
import Button from "@/components/ui/Button.vue"
import Card from "@/components/ui/Card.vue"
import { useTaskEvents } from "@/composables/useTaskEvents"

const route = useRoute()
const queryClient = useQueryClient()
const taskId = computed(() => String(route.params.taskId))
const taskQuery = useQuery({
  queryKey: computed(() => ["tasks", "detail", taskId.value]),
  queryFn: () => parserApi.task(taskId.value),
  refetchInterval: 5_000,
})
const stagesQuery = useQuery({
  queryKey: computed(() => ["tasks", taskId.value, "stages"]),
  queryFn: () => parserApi.taskStages(taskId.value),
  refetchInterval: 5_000,
})
const artifactsQuery = useQuery({
  queryKey: computed(() => ["tasks", taskId.value, "artifacts"]),
  queryFn: () => parserApi.taskArtifacts(taskId.value),
  refetchInterval: 10_000,
})
const status = computed(() => taskQuery.data.value?.data.status)
const resultQuery = useQuery({
  queryKey: computed(() => ["tasks", taskId.value, "result"]),
  queryFn: () => parserApi.taskResult(taskId.value),
  enabled: computed(() => status.value === "succeeded"),
  retry: false,
})
const stream = useTaskEvents(taskId, status, () => {
  void queryClient.invalidateQueries({ queryKey: ["tasks", "detail", taskId.value] })
  void queryClient.invalidateQueries({ queryKey: ["tasks", taskId.value, "stages"] })
  void queryClient.invalidateQueries({ queryKey: ["tasks", taskId.value, "artifacts"] })
  if (status.value === "succeeded") {
    void queryClient.invalidateQueries({ queryKey: ["tasks", taskId.value, "result"] })
  }
})

const resultMode = ref<"blocks" | "json">("blocks")
const actionPending = ref(false)
const actionError = ref<string | null>(null)
const preview = ref<{
  filename: string
  mimeType: string
  url: string | null
  text: string | null
} | null>(null)
const previewError = ref<string | null>(null)

function tone(
  value: TaskStatus | StageStatus,
): "neutral" | "success" | "danger" | "info" | "warning" {
  if (value === "succeeded") return "success"
  if (value === "failed" || value === "cancelled") return "danger"
  if (value === "running" || value === "leased") return "info"
  if (value === "skipped") return "warning"
  return "neutral"
}

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KiB`
  return `${(bytes / 1024 ** 2).toFixed(1)} MiB`
}

function formatTime(milliseconds: number) {
  const totalSeconds = Math.floor(milliseconds / 1000)
  const hours = Math.floor(totalSeconds / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)
  const seconds = totalSeconds % 60
  return [hours, minutes, seconds]
    .map((part) => part.toString().padStart(2, "0"))
    .join(":")
}

function locationLabel(block: ContentBlock) {
  if (block.type === "transcript") {
    return `${formatTime(block.start_ms)} – ${formatTime(block.end_ms)}`
  }
  if (block.type === "keyframe") return formatTime(block.timestamp_ms)
  const location = "location" in block ? block.location : undefined
  if (location?.page_number) return `第 ${location.page_number} 页`
  if (location?.slide_number) return `第 ${location.slide_number} 张`
  if (location?.sheet_name) return `工作表 ${location.sheet_name}`
  return null
}

function closePreview() {
  if (preview.value?.url) URL.revokeObjectURL(preview.value.url)
  preview.value = null
}

async function runTaskAction(action: "cancel" | "retry") {
  if (
    action === "cancel" &&
    !window.confirm("确认取消这个任务？正在执行的 Worker 会在下一次状态同步时停止。")
  ) {
    return
  }
  actionPending.value = true
  actionError.value = null
  try {
    if (action === "cancel") await parserApi.cancelTask(taskId.value)
    else await parserApi.retryTask(taskId.value)
    await Promise.all([
      taskQuery.refetch(),
      stagesQuery.refetch(),
      artifactsQuery.refetch(),
    ])
  } catch (reason) {
    actionError.value = reason instanceof Error ? reason.message : "任务操作失败"
  } finally {
    actionPending.value = false
  }
}

async function previewArtifact(artifact: Artifact) {
  closePreview()
  previewError.value = null
  try {
    const response = await apiFetch(
      `/api/v1/tasks/${encodeURIComponent(taskId.value)}/artifacts/${encodeURIComponent(artifact.artifact_id)}/content`,
    )
    if (!response.ok) throw new Error(`Preview failed with HTTP ${response.status}`)
    if (
      artifact.mime_type.startsWith("text/") ||
      artifact.mime_type === "application/json"
    ) {
      preview.value = {
        filename: artifact.filename,
        mimeType: artifact.mime_type,
        url: null,
        text: await response.text(),
      }
    } else if (
      artifact.mime_type.startsWith("image/") ||
      artifact.mime_type.startsWith("audio/") ||
      artifact.mime_type.startsWith("video/") ||
      artifact.mime_type === "application/pdf"
    ) {
      preview.value = {
        filename: artifact.filename,
        mimeType: artifact.mime_type,
        url: URL.createObjectURL(await response.blob()),
        text: null,
      }
    } else {
      throw new Error("该文件类型不支持浏览器内预览，请下载查看")
    }
  } catch (reason) {
    previewError.value = reason instanceof Error ? reason.message : "预览失败"
  }
}

onBeforeUnmount(closePreview)
</script>

<template>
  <div class="space-y-7">
    <header>
      <RouterLink class="mb-4 inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground" :to="{ name: 'tasks' }">
        <ArrowLeft class="size-4" />返回任务
      </RouterLink>
      <div class="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p class="eyebrow">Task detail</p>
          <h1 class="break-all font-mono text-2xl font-bold">{{ taskId }}</h1>
          <p class="page-subtitle">Stage 执行、结构化结果和产物文件。</p>
        </div>
        <div class="flex items-center gap-2">
          <Badge :tone="stream.connected.value ? 'success' : 'warning'">
            <Radio class="mr-1 size-3" />{{ stream.connected.value ? "实时事件已连接" : "轮询兜底" }}
          </Badge>
          <Button variant="outline" size="sm" @click="taskQuery.refetch()">
            <RefreshCw class="size-3.5" />刷新
          </Button>
          <Button
            v-if="status === 'pending' || status === 'leased' || status === 'running'"
            variant="destructive"
            size="sm"
            :disabled="actionPending"
            @click="runTaskAction('cancel')"
          >
            <Ban class="size-3.5" />取消
          </Button>
          <Button
            v-if="status === 'failed' || status === 'cancelled'"
            size="sm"
            :disabled="actionPending"
            @click="runTaskAction('retry')"
          >
            <RotateCcw class="size-3.5" />重试
          </Button>
        </div>
      </div>
      <p v-if="actionError" class="mt-3 text-sm text-red-700">{{ actionError }}</p>
    </header>

    <Card v-if="taskQuery.isPending.value" class="p-8 text-center text-muted-foreground">正在加载任务…</Card>
    <Card v-else-if="taskQuery.isError.value" class="border-red-200 p-8 text-red-700">任务加载失败：{{ taskQuery.error.value }}</Card>

    <template v-if="taskQuery.data.value?.data">
      <Card class="p-5">
        <div class="grid gap-5 sm:grid-cols-2 xl:grid-cols-4">
          <div><p class="text-xs text-muted-foreground">状态</p><Badge class="mt-2" :tone="tone(taskQuery.data.value.data.status)">{{ taskQuery.data.value.data.status }}</Badge></div>
          <div><p class="text-xs text-muted-foreground">总进度</p><div class="mt-2 flex items-center gap-3"><div class="h-2 flex-1 overflow-hidden rounded-full bg-muted"><div class="h-full bg-primary" :style="{ width: `${taskQuery.data.value.data.progress_percent}%` }" /></div><span class="text-sm">{{ taskQuery.data.value.data.progress_percent.toFixed(0) }}%</span></div></div>
          <div><p class="text-xs text-muted-foreground">Pipeline</p><p class="mt-2 font-mono text-sm">{{ taskQuery.data.value.data.pipeline_id ? `${taskQuery.data.value.data.pipeline_id}@${taskQuery.data.value.data.pipeline_version}` : "等待自动路由" }}</p></div>
          <div><p class="text-xs text-muted-foreground">创建时间</p><p class="mt-2 text-sm">{{ new Date(taskQuery.data.value.data.created_at).toLocaleString() }}</p></div>
        </div>
        <div v-if="taskQuery.data.value.data.error" class="mt-5 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800">
          <strong>{{ taskQuery.data.value.data.error.code }}</strong>：{{ taskQuery.data.value.data.error.message }}
        </div>
      </Card>

      <section>
        <div class="mb-3 flex items-center justify-between"><h2 class="section-title">Stage 执行</h2><span class="text-xs text-muted-foreground">{{ stagesQuery.data.value?.items.length ?? 0 }} 个阶段</span></div>
        <Card class="overflow-hidden">
          <div v-if="!stagesQuery.data.value?.items.length" class="p-8 text-center text-sm text-muted-foreground">任务尚未生成 Stage，后台路由器会自动重试。</div>
          <div v-else class="divide-y divide-border">
            <div v-for="stage in stagesQuery.data.value.items" :key="stage.stage_id" class="grid gap-3 p-5 lg:grid-cols-[2rem_1fr_10rem_8rem] lg:items-center">
              <div class="flex size-7 items-center justify-center rounded-full bg-muted font-mono text-xs font-bold">{{ stage.position + 1 }}</div>
              <div>
                <div class="flex flex-wrap items-center gap-2"><p class="font-semibold">{{ stage.name }}</p><Badge :tone="tone(stage.status)">{{ stage.status }}</Badge><span v-if="stage.optional" class="text-xs text-muted-foreground">可选</span></div>
                <p class="mt-1 font-mono text-xs text-muted-foreground">{{ stage.backend_id ?? "等待 Backend" }}<span v-if="stage.worker_id"> · {{ stage.worker_id }}</span></p>
                <p v-if="stage.depends_on.length" class="mt-1 text-xs text-muted-foreground">依赖：{{ stage.depends_on.join(", ") }}</p>
                <p v-if="stage.error" class="mt-2 text-xs text-red-700">{{ stage.error.code }}：{{ stage.error.message }}</p>
              </div>
              <div><div class="h-1.5 overflow-hidden rounded-full bg-muted"><div class="h-full bg-primary" :style="{ width: `${stage.progress_percent}%` }" /></div><p class="mt-1 text-right text-xs text-muted-foreground">{{ stage.progress_percent.toFixed(0) }}%</p></div>
              <p class="text-xs text-muted-foreground">尝试 {{ stage.attempt }}/{{ stage.maximum_attempts }}<br />{{ stage.runtime ?? "未分配设备" }}</p>
            </div>
          </div>
        </Card>
      </section>

      <section>
        <div class="mb-3 flex items-center justify-between">
          <h2 class="section-title">解析结果</h2>
          <div v-if="resultQuery.data.value" class="flex gap-1 rounded-lg bg-muted p-1">
            <button class="tab-button !px-3 !py-1.5" :class="{ 'tab-active': resultMode === 'blocks' }" @click="resultMode = 'blocks'">内容</button>
            <button class="tab-button !px-3 !py-1.5" :class="{ 'tab-active': resultMode === 'json' }" @click="resultMode = 'json'"><FileJson class="size-3.5" />JSON</button>
          </div>
        </div>
        <Card class="p-5">
          <p v-if="status !== 'succeeded'" class="py-8 text-center text-sm text-muted-foreground">任务成功后显示强类型 ParseResult。</p>
          <p v-else-if="resultQuery.isPending.value" class="py-8 text-center text-sm text-muted-foreground">正在加载结果…</p>
          <p v-else-if="resultQuery.isError.value" class="py-8 text-center text-sm text-red-700">结果暂不可用：{{ resultQuery.error.value }}</p>
          <pre v-else-if="resultMode === 'json'" class="max-h-[42rem] overflow-auto rounded-xl bg-slate-950 p-5 text-xs leading-6 text-slate-100">{{ JSON.stringify(resultQuery.data.value?.data, null, 2) }}</pre>
          <div v-else-if="resultQuery.data.value" class="space-y-4">
            <div v-if="!resultQuery.data.value.data.blocks.length" class="py-8 text-center text-sm text-muted-foreground">结果不包含内容块。</div>
            <article v-for="block in resultQuery.data.value.data.blocks" :key="block.block_id" class="rounded-xl border border-border p-4">
              <div class="mb-2 flex items-center justify-between text-xs text-muted-foreground"><span>{{ block.type }}</span><span>{{ locationLabel(block) }}</span></div>
              <h2 v-if="block.type === 'heading' && block.level === 1" class="text-2xl font-bold">{{ block.text }}</h2>
              <h3 v-else-if="block.type === 'heading'" class="text-lg font-bold">{{ block.text }}</h3>
              <p v-else-if="block.type === 'text'" class="whitespace-pre-wrap leading-7">{{ block.text }}</p>
              <div v-else-if="block.type === 'table'" class="overflow-x-auto"><table class="w-full border-collapse text-sm"><tbody><tr v-for="(row, rowIndex) in block.rows" :key="rowIndex"><td v-for="(cell, cellIndex) in row" :key="cellIndex" class="border border-border px-3 py-2">{{ cell }}</td></tr></tbody></table></div>
              <div v-else-if="block.type === 'transcript'" class="flex gap-4"><span class="font-mono text-xs text-primary">{{ formatTime(block.start_ms) }}</span><div><p class="leading-6">{{ block.text }}</p><p v-if="block.speaker || block.language" class="mt-1 text-xs text-muted-foreground">{{ block.speaker ?? "未知说话人" }} · {{ block.language ?? "未知语言" }}</p></div></div>
              <div v-else-if="block.type === 'image'"><p class="font-mono text-xs">{{ block.artifact_id }}</p><p v-if="block.caption" class="mt-2">{{ block.caption }}</p><p v-if="block.ocr_text" class="mt-2 whitespace-pre-wrap text-sm text-muted-foreground">{{ block.ocr_text }}</p></div>
              <div v-else-if="block.type === 'keyframe'"><p class="font-mono text-xs">{{ formatTime(block.timestamp_ms) }} · {{ block.artifact_id }}</p><p v-if="block.caption" class="mt-2">{{ block.caption }}</p><p v-if="block.ocr_text" class="mt-2 whitespace-pre-wrap text-sm text-muted-foreground">{{ block.ocr_text }}</p></div>
              <a v-else-if="block.type === 'link'" class="break-all text-primary underline" :href="block.url" target="_blank" rel="noopener noreferrer">{{ block.text || block.url }}</a>
            </article>
            <div v-if="resultQuery.data.value.data.warnings.length" class="rounded-xl bg-amber-50 p-4 text-sm text-amber-900"><p v-for="warning in resultQuery.data.value.data.warnings" :key="`${warning.code}-${warning.stage_id}`"><strong>{{ warning.code }}</strong>：{{ warning.message }}</p></div>
          </div>
        </Card>
      </section>

      <section>
        <div class="mb-3 flex items-center justify-between"><h2 class="section-title">Artifacts</h2><span class="text-xs text-muted-foreground">{{ artifactsQuery.data.value?.items.length ?? 0 }} 个文件</span></div>
        <Card class="overflow-hidden">
          <div v-if="!artifactsQuery.data.value?.items.length" class="p-8 text-center text-sm text-muted-foreground">暂无产物。</div>
          <div v-else class="divide-y divide-border">
            <div v-for="artifact in artifactsQuery.data.value.items" :key="artifact.artifact_id" class="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
              <div class="min-w-0"><p class="truncate font-semibold">{{ artifact.filename }}</p><p class="mt-1 text-xs text-muted-foreground">{{ artifact.type }} · {{ artifact.mime_type }} · {{ formatBytes(artifact.size_bytes) }}</p><p class="mt-1 truncate font-mono text-[11px] text-muted-foreground">sha256:{{ artifact.sha256 }}</p></div>
              <div class="flex shrink-0 gap-2"><Button variant="outline" size="sm" @click="previewArtifact(artifact)"><Eye class="size-3.5" />预览</Button><Button size="sm" @click="parserApi.downloadArtifact(taskId, artifact)"><Download class="size-3.5" />下载</Button></div>
            </div>
          </div>
        </Card>
        <p v-if="previewError" class="mt-3 text-sm text-red-700">{{ previewError }}</p>
        <Card v-if="preview" class="mt-4 p-5">
          <div class="mb-4 flex items-center justify-between"><div><h3 class="font-semibold">{{ preview.filename }}</h3><p class="text-xs text-muted-foreground">{{ preview.mimeType }}</p></div><Button variant="ghost" size="sm" @click="closePreview">关闭</Button></div>
          <pre v-if="preview.text !== null" class="max-h-[36rem] overflow-auto whitespace-pre-wrap rounded-xl bg-muted p-4 text-sm leading-6">{{ preview.text }}</pre>
          <img v-else-if="preview.mimeType.startsWith('image/')" class="max-h-[40rem] max-w-full rounded-xl object-contain" :src="preview.url ?? undefined" alt="Artifact preview" />
          <audio v-else-if="preview.mimeType.startsWith('audio/')" class="w-full" :src="preview.url ?? undefined" controls />
          <video v-else-if="preview.mimeType.startsWith('video/')" class="max-h-[40rem] w-full rounded-xl bg-black" :src="preview.url ?? undefined" controls />
          <iframe v-else-if="preview.mimeType === 'application/pdf'" class="h-[42rem] w-full rounded-xl border border-border" :src="preview.url ?? undefined" title="PDF preview" />
        </Card>
      </section>
    </template>
  </div>
</template>

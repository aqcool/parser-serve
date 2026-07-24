<script setup lang="ts">
import { useQuery, useQueryClient } from "@tanstack/vue-query"
import { CheckCircle2, FlaskConical, GitBranch, RefreshCw, Rocket, ShieldCheck } from "lucide-vue-next"
import { computed, ref } from "vue"
import { useRouter } from "vue-router"

import {
  ApiClientError,
  parserApi,
  type CreatePipeline,
  type Pipeline,
  type PipelineTestInput,
  type PipelineValidation,
} from "@/api/client"
import Badge from "@/components/ui/Badge.vue"
import Button from "@/components/ui/Button.vue"
import Card from "@/components/ui/Card.vue"

const queryClient = useQueryClient()
const router = useRouter()
const query = useQuery({
  queryKey: ["pipelines", "management"],
  queryFn: parserApi.pipelines,
})
const items = computed(() => query.data.value?.items ?? [])
const validations = ref<Record<string, PipelineValidation>>({})
const busy = ref<string | null>(null)
const error = ref("")
const showCreate = ref(false)
const testTarget = ref<string | null>(null)
const testRequest = ref("")
const definition = ref(
  JSON.stringify(
    {
      pipeline_id: "pipeline_custom001",
      name: "custom.pipeline",
      media_categories: ["document"],
      mime_types: [],
      routing_priority: 50,
      stages: [
        {
          name: "parse",
          backend: {
            preferred: "mineru",
            fallbacks: ["builtin_pdf"],
            required_runtimes: [],
          },
          depends_on: [],
          timeout_seconds: 600,
          retry: {
            maximum_attempts: 2,
            initial_delay_seconds: 2,
            maximum_delay_seconds: 30,
            multiplier: 2,
          },
          optional: false,
          parameters: {},
        },
      ],
    },
    null,
    2,
  ),
)

function key(pipelineId: string, version: number) {
  return `${pipelineId}@${version}`
}

function defaultTestRequest(pipeline: Pipeline): PipelineTestInput {
  const media = pipeline.media_categories[0]
  if (media === "web") {
    return {
      source: { type: "url", url: "https://example.com" },
      options: {},
      client_reference: `web-pipeline-test-${pipeline.version}`,
    }
  }
  if (media === "text") {
    return {
      source: {
        type: "text",
        text: "Parser Serve Pipeline test",
        mime_type: "text/plain",
      },
      options: {},
      client_reference: `text-pipeline-test-${pipeline.version}`,
    }
  }
  return {
    source: { type: "uploaded_file", file_id: "file_replace_with_uploaded_id" },
    options: {},
    client_reference: `${media ?? "parser"}-pipeline-test-${pipeline.version}`,
  }
}

function toggleTest(pipeline: Pipeline) {
  const identity = key(pipeline.pipeline_id, pipeline.version)
  if (testTarget.value === identity) {
    testTarget.value = null
    return
  }
  testTarget.value = identity
  testRequest.value = JSON.stringify(defaultTestRequest(pipeline), null, 2)
}

async function runTest(pipeline: Pipeline) {
  const identity = key(pipeline.pipeline_id, pipeline.version)
  busy.value = `test:${identity}`
  error.value = ""
  try {
    const request = JSON.parse(testRequest.value) as PipelineTestInput
    const response = await parserApi.testPipeline(
      pipeline.pipeline_id,
      pipeline.version,
      request,
    )
    await router.push(`/tasks/${response.data.task_id}`)
  } catch (caught) {
    error.value =
      caught instanceof ApiClientError
        ? caught.message
        : caught instanceof SyntaxError
          ? "测试请求 JSON 格式无效"
          : "Pipeline 测试任务创建失败"
  } finally {
    busy.value = null
  }
}

async function validate(pipelineId: string, version: number) {
  const identity = key(pipelineId, version)
  busy.value = identity
  error.value = ""
  try {
    const response = await parserApi.validatePipeline(pipelineId, version)
    validations.value[identity] = response.data
  } catch (caught) {
    error.value =
      caught instanceof ApiClientError ? caught.message : "Pipeline 校验失败"
  } finally {
    busy.value = null
  }
}

async function publish(pipelineId: string, version: number) {
  const identity = key(pipelineId, version)
  busy.value = identity
  error.value = ""
  try {
    await parserApi.publishPipeline(pipelineId, version)
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["pipelines"] }),
      queryClient.invalidateQueries({ queryKey: ["capabilities"] }),
    ])
  } catch (caught) {
    error.value =
      caught instanceof ApiClientError ? caught.message : "Pipeline 发布失败"
    await validate(pipelineId, version)
  } finally {
    busy.value = null
  }
}

async function create() {
  busy.value = "create"
  error.value = ""
  try {
    const request = JSON.parse(definition.value) as CreatePipeline
    await parserApi.createPipeline(request)
    showCreate.value = false
    await queryClient.invalidateQueries({ queryKey: ["pipelines"] })
  } catch (caught) {
    error.value =
      caught instanceof ApiClientError
        ? caught.message
        : caught instanceof SyntaxError
          ? "Pipeline JSON 格式无效"
          : "Pipeline 创建失败"
  } finally {
    busy.value = null
  }
}
</script>

<template>
  <div class="space-y-4">
    <div class="flex justify-end gap-2"><Button size="sm" variant="outline" @click="query.refetch()"><RefreshCw class="size-3.5" />刷新</Button><Button size="sm" @click="showCreate = !showCreate">{{ showCreate ? "收起" : "新建版本" }}</Button></div>
    <Card v-if="showCreate" class="p-5">
      <h2 class="section-title">创建 Pipeline 草稿</h2>
      <p class="mt-1 text-sm text-muted-foreground">相同 Pipeline ID 会自动生成递增版本；创建后先校验，再发布。</p>
      <textarea v-model="definition" class="mt-4 min-h-80 w-full rounded-xl border border-input bg-background p-4 font-mono text-xs leading-5 outline-none focus:ring-2 focus:ring-ring" spellcheck="false" />
      <div class="mt-3 flex justify-end"><Button :disabled="busy !== null" @click="create">创建草稿</Button></div>
    </Card>
    <p v-if="error" class="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">{{ error }}</p>
    <div class="grid gap-4 xl:grid-cols-2">
      <Card v-for="pipeline in items" :key="key(pipeline.pipeline_id, pipeline.version)" class="p-5">
        <div class="flex items-start justify-between gap-4">
          <div class="flex min-w-0 gap-3"><div class="rounded-xl bg-violet-100 p-2.5 text-violet-700"><GitBranch class="size-5" /></div><div class="min-w-0"><h2 class="truncate font-semibold">{{ pipeline.name }}</h2><p class="mt-1 truncate font-mono text-xs text-muted-foreground">{{ pipeline.pipeline_id }}@{{ pipeline.version }}</p></div></div>
          <Badge :tone="pipeline.status === 'published' ? 'success' : pipeline.status === 'draft' ? 'warning' : 'neutral'">{{ pipeline.status }}</Badge>
        </div>
        <div class="mt-5 flex flex-wrap gap-2"><Badge v-for="media in pipeline.media_categories" :key="media">{{ media }}</Badge><Badge tone="info">优先级 {{ pipeline.routing_priority }}</Badge></div>
        <ol class="mt-5 space-y-2">
          <li v-for="(stage, index) in pipeline.stages" :key="stage.name" class="rounded-xl bg-muted/55 p-3 text-sm">
            <div class="flex items-center justify-between"><span class="font-semibold">{{ index + 1 }}. {{ stage.name }}</span><span class="text-xs text-muted-foreground">{{ stage.timeout_seconds }}s</span></div>
            <p class="mt-1 text-xs text-muted-foreground">{{ stage.backend.preferred }}<span v-if="stage.backend.fallbacks.length"> → {{ stage.backend.fallbacks.join(" → ") }}</span></p>
          </li>
        </ol>
        <div v-if="validations[key(pipeline.pipeline_id, pipeline.version)]" class="mt-4 rounded-xl border p-3 text-xs" :class="validations[key(pipeline.pipeline_id, pipeline.version)].valid ? 'border-emerald-200 bg-emerald-50 text-emerald-800' : 'border-amber-200 bg-amber-50 text-amber-900'">
          <p class="flex items-center gap-2 font-semibold"><CheckCircle2 class="size-3.5" />{{ validations[key(pipeline.pipeline_id, pipeline.version)].valid ? "校验通过" : "暂不可发布" }}</p>
          <ul v-if="!validations[key(pipeline.pipeline_id, pipeline.version)].valid" class="mt-2 list-disc space-y-1 pl-4"><li v-for="violation in validations[key(pipeline.pipeline_id, pipeline.version)].violations" :key="violation.location">{{ violation.location }}：{{ violation.message }}</li></ul>
        </div>
        <div v-if="testTarget === key(pipeline.pipeline_id, pipeline.version)" class="mt-4 rounded-xl border border-violet-200 bg-violet-50/50 p-3">
          <p class="text-xs text-muted-foreground">测试会创建并执行真实任务，但不会发布或修改此 Pipeline。文件类输入请先上传，并替换 `file_id`。</p>
          <textarea v-model="testRequest" class="mt-3 min-h-48 w-full rounded-lg border border-input bg-background p-3 font-mono text-xs leading-5 outline-none focus:ring-2 focus:ring-ring" spellcheck="false" />
          <div class="mt-3 flex justify-end"><Button size="sm" :disabled="busy !== null" @click="runTest(pipeline)"><FlaskConical class="size-3.5" />创建测试任务</Button></div>
        </div>
        <div class="mt-5 flex justify-end gap-2">
          <Button size="sm" variant="outline" :disabled="busy === key(pipeline.pipeline_id, pipeline.version)" @click="validate(pipeline.pipeline_id, pipeline.version)"><ShieldCheck class="size-3.5" />校验</Button>
          <Button size="sm" variant="outline" :disabled="busy !== null" @click="toggleTest(pipeline)"><FlaskConical class="size-3.5" />测试</Button>
          <Button v-if="pipeline.status !== 'published'" size="sm" :disabled="busy === key(pipeline.pipeline_id, pipeline.version)" @click="publish(pipeline.pipeline_id, pipeline.version)"><Rocket class="size-3.5" />发布</Button>
        </div>
      </Card>
    </div>
    <Card v-if="!items.length" class="grid min-h-72 place-items-center border-dashed p-8 text-center text-sm text-muted-foreground">{{ query.isPending.value ? "正在读取 Pipeline…" : "尚无 Pipeline；请先在 Backend 页面初始化默认目录。" }}</Card>
  </div>
</template>

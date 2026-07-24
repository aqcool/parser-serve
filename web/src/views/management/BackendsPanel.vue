<script setup lang="ts">
import { useQuery, useQueryClient } from "@tanstack/vue-query"
import { Boxes, Power, RefreshCw, Sparkles } from "lucide-vue-next"
import { computed, ref } from "vue"

import { ApiClientError, parserApi } from "@/api/client"
import Badge from "@/components/ui/Badge.vue"
import Button from "@/components/ui/Button.vue"
import Card from "@/components/ui/Card.vue"
import Input from "@/components/ui/Input.vue"

const queryClient = useQueryClient()
const query = useQuery({
  queryKey: ["backends", "management"],
  queryFn: parserApi.backends,
})
const items = computed(() => query.data.value?.items ?? [])
const busy = ref<string | null>(null)
const message = ref("")
const error = ref("")
const backendName = ref("")
const backendVersion = ref("1.0")
const mediaCategories = ref("image")
const runtimes = ref("cpu")
const concurrency = ref("1")

function commaValues(value: string) {
  return [...new Set(value.split(",").map((item) => item.trim()).filter(Boolean))]
}

async function createBackend() {
  busy.value = "create"
  error.value = ""
  message.value = ""
  try {
    await parserApi.createBackend({
      capability: {
        name: backendName.value,
        version: backendVersion.value,
        media_categories: commaValues(mediaCategories.value),
        mime_types: [],
        runtimes: commaValues(runtimes.value),
        maximum_concurrency: Number(concurrency.value),
      },
      execution_mode: "local",
      default_timeout_seconds: 600,
      maximum_attempts: 2,
      scheduling_weight: 100,
    })
    message.value = `Backend ${backendName.value}@${backendVersion.value} 已注册。`
    backendName.value = ""
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["backends"] }),
      queryClient.invalidateQueries({ queryKey: ["pipelines"] }),
    ])
  } catch (caught) {
    error.value =
      caught instanceof ApiClientError ? caught.message : "Backend 创建失败"
  } finally {
    busy.value = null
  }
}

async function toggle(backendId: string, enabled: boolean) {
  busy.value = backendId
  error.value = ""
  try {
    await parserApi.updateBackend(backendId, { enabled })
    await queryClient.invalidateQueries({ queryKey: ["backends"] })
  } catch (caught) {
    error.value =
      caught instanceof ApiClientError ? caught.message : "Backend 更新失败"
  } finally {
    busy.value = null
  }
}

async function initializeDefaults() {
  busy.value = "defaults"
  error.value = ""
  message.value = ""
  try {
    const response = await parserApi.initializeDefaults()
    message.value = `新增 ${response.data.backend_ids_created.length} 个 Backend；${response.data.pipelines.filter((item) => item.status === "published").length} 个 Pipeline 已发布。`
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["backends"] }),
      queryClient.invalidateQueries({ queryKey: ["pipelines"] }),
      queryClient.invalidateQueries({ queryKey: ["capabilities"] }),
    ])
  } catch (caught) {
    error.value =
      caught instanceof ApiClientError ? caught.message : "默认目录初始化失败"
  } finally {
    busy.value = null
  }
}
</script>

<template>
  <div class="space-y-5">
  <Card class="p-5">
    <div><h2 class="section-title">注册 Backend</h2><p class="mt-1 text-sm text-muted-foreground">用于 Worker 本地实现或 Worker 内远程协议适配器；名称、版本和 Runtime 必须与 Worker 上报一致。</p></div>
    <form class="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-[1.2fr_.7fr_1fr_1fr_.55fr_auto]" @submit.prevent="createBackend">
      <Input v-model="backendName" placeholder="paddleocr" />
      <Input v-model="backendVersion" placeholder="1.0" />
      <Input v-model="mediaCategories" placeholder="image,document" />
      <Input v-model="runtimes" placeholder="cuda,ascend" />
      <Input v-model="concurrency" type="number" placeholder="并发" />
      <Button type="submit" :disabled="!backendName || !backendVersion || busy !== null">注册</Button>
    </form>
  </Card>
  <Card class="overflow-hidden">
    <div class="flex flex-col gap-3 border-b border-border p-4 sm:flex-row sm:items-center sm:justify-between">
      <div>
        <p class="text-sm font-semibold">{{ items.length }} 个 Backend 定义</p>
        <p class="mt-1 text-xs text-muted-foreground">逻辑定义需与 Worker 实际上报的名称、版本和 Runtime 一致。</p>
      </div>
      <div class="flex gap-2">
        <Button size="sm" variant="outline" :disabled="busy !== null" @click="query.refetch()"><RefreshCw class="size-3.5" />刷新</Button>
        <Button size="sm" :disabled="busy !== null" @click="initializeDefaults"><Sparkles class="size-3.5" />初始化默认目录</Button>
      </div>
    </div>
    <p v-if="message" class="border-b border-border bg-emerald-50 px-4 py-3 text-sm text-emerald-800">{{ message }}</p>
    <p v-if="error" class="border-b border-border bg-red-50 px-4 py-3 text-sm text-red-800">{{ error }}</p>
    <div class="overflow-x-auto">
      <table class="w-full min-w-[860px] text-left text-sm">
        <thead class="bg-muted/55 text-xs uppercase tracking-wide text-muted-foreground">
          <tr><th class="px-4 py-3">Backend</th><th class="px-4 py-3">媒体</th><th class="px-4 py-3">Runtime</th><th class="px-4 py-3">并发</th><th class="px-4 py-3">执行</th><th class="px-4 py-3 text-right">操作</th></tr>
        </thead>
        <tbody class="divide-y divide-border">
          <tr v-for="backend in items" :key="backend.backend_id">
            <td class="px-4 py-4"><div class="flex items-center gap-3"><div class="rounded-lg bg-primary/8 p-2 text-primary"><Boxes class="size-4" /></div><div><p class="font-semibold">{{ backend.capability.name }} <span class="font-mono text-xs text-muted-foreground">@{{ backend.capability.version }}</span></p><p class="mt-1 font-mono text-xs text-muted-foreground">{{ backend.backend_id }}</p></div></div></td>
            <td class="px-4 py-4"><div class="flex flex-wrap gap-1"><Badge v-for="media in backend.capability.media_categories" :key="media">{{ media }}</Badge></div></td>
            <td class="px-4 py-4">{{ backend.capability.runtimes.join(", ") }}</td>
            <td class="px-4 py-4">{{ backend.capability.maximum_concurrency }}</td>
            <td class="px-4 py-4"><Badge :tone="backend.status === 'enabled' ? 'success' : backend.status === 'unhealthy' ? 'danger' : 'neutral'">{{ backend.status }}</Badge></td>
            <td class="px-4 py-4 text-right"><Button size="sm" :variant="backend.status === 'enabled' ? 'outline' : 'default'" :disabled="busy === backend.backend_id" @click="toggle(backend.backend_id, backend.status !== 'enabled')"><Power class="size-3.5" />{{ backend.status === "enabled" ? "停用" : "启用" }}</Button></td>
          </tr>
        </tbody>
      </table>
      <div v-if="!items.length" class="grid min-h-64 place-items-center p-8 text-center text-sm text-muted-foreground">{{ query.isPending.value ? "正在读取 Backend…" : "尚无 Backend；可初始化默认目录。" }}</div>
    </div>
  </Card>
  </div>
</template>

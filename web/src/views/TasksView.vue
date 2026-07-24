<script setup lang="ts">
import { useQuery } from "@tanstack/vue-query"
import { RefreshCw, Search } from "lucide-vue-next"
import { computed, ref } from "vue"
import { RouterLink } from "vue-router"

import { parserApi } from "@/api/client"
import Badge from "@/components/ui/Badge.vue"
import Button from "@/components/ui/Button.vue"
import Card from "@/components/ui/Card.vue"
import Input from "@/components/ui/Input.vue"

const search = ref("")
const query = useQuery({ queryKey: ["tasks", "list"], queryFn: () => parserApi.tasks(100), refetchInterval: 10_000 })
const items = computed(() => (query.data.value?.items ?? []).filter((task) => task.task_id.includes(search.value.trim()) || (task.client_reference ?? "").includes(search.value.trim())))
const pending = computed(() => query.isPending.value)
const fetching = computed(() => query.isFetching.value)

function tone(
  status: string,
): "neutral" | "success" | "danger" | "info" {
  if (status === "succeeded") return "success"
  if (status === "failed" || status === "cancelled") return "danger"
  if (status === "running" || status === "leased") return "info"
  return "neutral"
}
</script>

<template>
  <div class="space-y-7">
    <header><p class="eyebrow">Execution ledger</p><h1 class="page-title">任务管理</h1><p class="page-subtitle">查询状态、进度、Pipeline 版本与最终结果。</p></header>
    <Card class="overflow-hidden">
      <div class="flex flex-col gap-3 border-b border-border p-4 sm:flex-row sm:items-center sm:justify-between">
        <div class="relative w-full sm:max-w-sm"><Search class="absolute left-3 top-3 size-4 text-muted-foreground" /><Input v-model="search" class="pl-9" placeholder="搜索 Task ID 或外部引用" /></div>
        <Button variant="outline" @click="query.refetch()"><RefreshCw class="size-4" :class="{ 'animate-spin': fetching }" />刷新</Button>
      </div>
      <div class="overflow-x-auto">
        <table class="w-full min-w-[820px] text-left text-sm">
          <thead class="bg-muted/40 text-xs uppercase tracking-wide text-muted-foreground"><tr><th class="px-5 py-3 font-semibold">Task</th><th class="px-5 py-3 font-semibold">状态</th><th class="px-5 py-3 font-semibold">进度</th><th class="px-5 py-3 font-semibold">Pipeline</th><th class="px-5 py-3 font-semibold">创建时间</th></tr></thead>
          <tbody class="divide-y divide-border">
            <tr v-for="task in items" :key="task.task_id" class="hover:bg-muted/25">
              <td class="px-5 py-4"><RouterLink class="font-mono font-semibold text-primary hover:underline" :to="{ name: 'task-detail', params: { taskId: task.task_id } }">{{ task.task_id }}</RouterLink><p class="mt-1 text-xs text-muted-foreground">{{ task.client_reference ?? "—" }}</p></td>
              <td class="px-5 py-4"><Badge :tone="tone(task.status)">{{ task.status }}</Badge></td>
              <td class="px-5 py-4"><div class="flex items-center gap-3"><div class="h-1.5 w-24 overflow-hidden rounded-full bg-muted"><div class="h-full rounded-full bg-primary" :style="{ width: `${task.progress_percent}%` }" /></div><span class="text-xs text-muted-foreground">{{ task.progress_percent.toFixed(0) }}%</span></div></td>
              <td class="px-5 py-4 text-muted-foreground">{{ task.pipeline_id ? `${task.pipeline_id}@${task.pipeline_version}` : "自动路由" }}</td>
              <td class="px-5 py-4 text-muted-foreground">{{ new Date(task.created_at).toLocaleString() }}</td>
            </tr>
            <tr v-if="!items.length"><td colspan="5" class="px-5 py-16 text-center text-muted-foreground">{{ pending ? "正在加载…" : "没有匹配任务" }}</td></tr>
          </tbody>
        </table>
      </div>
    </Card>
  </div>
</template>

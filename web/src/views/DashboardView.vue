<script setup lang="ts">
import { useQuery } from "@tanstack/vue-query"
import { Activity, Boxes, CheckCircle2, Clock3, Cpu, FileStack, Webhook } from "lucide-vue-next"
import { computed } from "vue"

import { parserApi } from "@/api/client"
import Badge from "@/components/ui/Badge.vue"
import Card from "@/components/ui/Card.vue"

const tasks = useQuery({ queryKey: ["tasks"], queryFn: () => parserApi.tasks(100), refetchInterval: 10_000 })
const dashboard = useQuery({ queryKey: ["dashboard", "summary"], queryFn: parserApi.dashboard, refetchInterval: 15_000 })
const capabilities = useQuery({ queryKey: ["capabilities"], queryFn: parserApi.capabilities })

const taskItems = computed(() => tasks.data.value?.items ?? [])
const tasksPending = computed(() => tasks.isPending.value)
const capabilityData = computed(() => capabilities.data.value?.data)
const summary = computed(() => dashboard.data.value?.data)
const stats = computed(() => [
  { label: "总任务", value: summary.value?.tasks.total_tasks ?? 0, icon: FileStack, detail: "最近 24 小时" },
  { label: "执行中", value: summary.value?.tasks.running_tasks ?? 0, icon: Activity, detail: `${summary.value?.tasks.pending_tasks ?? 0} 个等待中` },
  { label: "已成功", value: summary.value?.tasks.succeeded_tasks ?? 0, icon: CheckCircle2, detail: `成功率 ${((summary.value?.tasks.success_rate ?? 0) * 100).toFixed(1)}%` },
  { label: "在线 Worker", value: (summary.value?.workers.online_workers ?? 0) + (summary.value?.workers.busy_workers ?? 0), icon: Cpu, detail: `${summary.value?.workers.used_concurrency ?? 0}/${summary.value?.workers.total_concurrency ?? 0} 并发使用` },
  { label: "启用 Backend", value: capabilityData.value?.backends.length ?? 0, icon: Boxes, detail: `${capabilityData.value?.runtimes.length ?? 0} 种在线 Runtime` },
  { label: "失败回调", value: summary.value?.callbacks.failed_deliveries ?? 0, icon: Webhook, detail: `${summary.value?.callbacks.pending_retries ?? 0} 个等待重试` },
])
</script>

<template>
  <div class="space-y-7">
    <header class="flex flex-col justify-between gap-4 md:flex-row md:items-end">
      <div>
        <p class="eyebrow">Operations overview</p>
        <h1 class="page-title">系统总览</h1>
        <p class="page-subtitle">解析任务、执行节点和服务能力的实时快照。</p>
      </div>
      <Badge tone="success"><span class="mr-1.5 size-1.5 rounded-full bg-emerald-500" />控制面正常</Badge>
    </header>

    <div class="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
      <Card v-for="item in stats" :key="item.label" class="p-5">
        <div class="flex items-start justify-between">
          <div>
            <p class="text-sm font-medium text-muted-foreground">{{ item.label }}</p>
            <p class="mt-3 font-display text-4xl font-bold tracking-tight">{{ item.value }}</p>
          </div>
          <div class="rounded-xl bg-primary/8 p-2.5 text-primary"><component :is="item.icon" class="size-5" /></div>
        </div>
        <p class="mt-4 text-xs text-muted-foreground">{{ item.detail }}</p>
      </Card>
    </div>

    <div class="grid gap-5 xl:grid-cols-[1.35fr_.65fr]">
      <Card class="overflow-hidden">
        <div class="flex items-center justify-between border-b border-border p-5">
          <div>
            <h2 class="section-title">最近任务</h2>
            <p class="text-sm text-muted-foreground">从最新提交开始</p>
          </div>
          <RouterLink to="/tasks" class="text-sm font-semibold text-primary hover:underline">查看全部</RouterLink>
        </div>
        <div v-if="tasksPending" class="p-8 text-sm text-muted-foreground">正在读取任务…</div>
        <div v-else-if="!taskItems.length" class="grid min-h-52 place-items-center p-8 text-center">
          <div><Clock3 class="mx-auto mb-3 size-7 text-muted-foreground" /><p class="font-semibold">还没有任务</p><p class="mt-1 text-sm text-muted-foreground">前往解析测试提交第一份内容。</p></div>
        </div>
        <div v-else class="divide-y divide-border">
          <div v-for="task in taskItems.slice(0, 6)" :key="task.task_id" class="grid grid-cols-[1fr_auto] gap-4 p-4 md:grid-cols-[1fr_120px_100px]">
            <div class="min-w-0"><p class="truncate font-mono text-sm font-semibold">{{ task.task_id }}</p><p class="mt-1 text-xs text-muted-foreground">{{ new Date(task.created_at).toLocaleString() }}</p></div>
            <p class="hidden self-center text-sm text-muted-foreground md:block">{{ task.pipeline_id ?? "自动路由" }}</p>
            <Badge class="self-center justify-self-end" :tone="task.status === 'succeeded' ? 'success' : task.status === 'failed' ? 'danger' : task.status === 'running' ? 'info' : 'neutral'">{{ task.status }}</Badge>
          </div>
        </div>
      </Card>

      <Card class="p-5">
        <div class="flex items-center gap-3">
          <div class="rounded-xl bg-violet-100 p-2.5 text-violet-700"><Boxes class="size-5" /></div>
          <div><h2 class="section-title">解析能力</h2><p class="text-sm text-muted-foreground">已发布与启用</p></div>
        </div>
        <dl class="mt-7 space-y-5">
          <div class="flex items-center justify-between border-b border-border pb-4"><dt class="text-sm text-muted-foreground">Pipeline</dt><dd class="font-display text-2xl font-bold">{{ capabilityData?.pipelines.length ?? 0 }}</dd></div>
          <div class="flex items-center justify-between border-b border-border pb-4"><dt class="text-sm text-muted-foreground">Backend</dt><dd class="font-display text-2xl font-bold">{{ capabilityData?.backends.length ?? 0 }}</dd></div>
          <div><dt class="mb-2 text-sm text-muted-foreground">媒体类型</dt><dd class="flex flex-wrap gap-2"><Badge v-for="category in capabilityData?.media_categories ?? []" :key="category">{{ category }}</Badge></dd></div>
          <div><dt class="mb-2 text-sm text-muted-foreground">在线硬件</dt><dd class="flex flex-wrap gap-2"><Badge v-for="runtime in capabilityData?.runtimes ?? []" :key="runtime.runtime" tone="info">{{ runtime.runtime }} · {{ runtime.available_devices }}</Badge><span v-if="!capabilityData?.runtimes.length" class="text-sm text-muted-foreground">暂无在线设备</span></dd></div>
          <div><dt class="mb-2 text-sm text-muted-foreground">启用 Backend</dt><dd class="max-h-28 space-y-1 overflow-auto font-mono text-xs text-muted-foreground"><p v-for="backend in capabilityData?.backends ?? []" :key="backend">{{ backend }}</p><span v-if="!capabilityData?.backends.length">暂无可用 Backend</span></dd></div>
        </dl>
      </Card>
    </div>
  </div>
</template>

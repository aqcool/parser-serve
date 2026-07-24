<script setup lang="ts">
import { useQuery, useQueryClient } from "@tanstack/vue-query"
import { Cpu, Power, RefreshCw, Save } from "lucide-vue-next"
import { computed, ref, watchEffect } from "vue"
import { useRoute } from "vue-router"

import { parserApi } from "@/api/client"
import Badge from "@/components/ui/Badge.vue"
import Button from "@/components/ui/Button.vue"
import Card from "@/components/ui/Card.vue"
import Input from "@/components/ui/Input.vue"
import ApiKeysPanel from "@/views/management/ApiKeysPanel.vue"
import BackendsPanel from "@/views/management/BackendsPanel.vue"
import CallbacksPanel from "@/views/management/CallbacksPanel.vue"
import PipelinesPanel from "@/views/management/PipelinesPanel.vue"
import SystemPanel from "@/views/management/SystemPanel.vue"

const route = useRoute()
const labels: Record<string, [string, string]> = {
  workers: ["Worker 管理", "查看节点、硬件、心跳和 Drain 状态。"],
  pipelines: ["Pipeline 管理", "校验、发布和回滚解析 DAG。"],
  backends: ["Backend 管理", "管理解析能力、运行时和调度权重。"],
  callbacks: ["回调记录", "查询投递状态、失败原因并人工重发。"],
  "api-keys": ["API Key", "创建、轮换、启停和删除接入密钥。"],
  settings: ["系统信息", "查看版本、Schema、上传限制和在线硬件 Runtime。"],
}
const content = computed(() => labels[String(route.params.section)] ?? ["系统管理", "管理 Parser Serve 控制面。"])
const isWorkers = computed(() => route.params.section === "workers")
const queryClient = useQueryClient()
const workers = useQuery({
  queryKey: ["workers", "management"],
  queryFn: parserApi.workers,
  enabled: isWorkers,
  refetchInterval: 15_000,
})
const workerItems = computed(() => workers.data.value?.items ?? [])
const workersPending = computed(() => workers.isPending.value)
const schedulingValues = ref<
  Record<string, { maximumConcurrency: string; schedulingWeight: string }>
>({})
const savingWorkerId = ref<string | null>(null)

watchEffect(() => {
  for (const worker of workerItems.value) {
    if (schedulingValues.value[worker.worker_id]) continue
    schedulingValues.value[worker.worker_id] = {
      maximumConcurrency: String(worker.maximum_concurrency),
      schedulingWeight: String(worker.scheduling_weight),
    }
  }
})

async function setDraining(workerId: string, draining: boolean) {
  await parserApi.updateWorker(workerId, { draining })
  await queryClient.invalidateQueries({ queryKey: ["workers"] })
}

async function saveScheduling(workerId: string) {
  const values = schedulingValues.value[workerId]
  if (!values) return
  savingWorkerId.value = workerId
  try {
    await parserApi.updateWorker(workerId, {
      maximum_concurrency: Number(values.maximumConcurrency),
      scheduling_weight: Number(values.schedulingWeight),
    })
    await queryClient.invalidateQueries({ queryKey: ["workers"] })
  } finally {
    savingWorkerId.value = null
  }
}
</script>

<template>
  <div class="space-y-7">
    <header><p class="eyebrow">Control plane</p><h1 class="page-title">{{ content[0] }}</h1><p class="page-subtitle">{{ content[1] }}</p></header>
    <Card v-if="isWorkers" class="overflow-hidden">
      <div class="flex items-center justify-between border-b border-border p-4">
        <p class="text-sm text-muted-foreground">{{ workerItems.length }} 个节点</p>
        <Button variant="outline" size="sm" @click="workers.refetch()"><RefreshCw class="size-3.5" />刷新</Button>
      </div>
      <div class="grid gap-4 p-4 md:grid-cols-2 xl:grid-cols-3">
        <article v-for="worker in workerItems" :key="worker.worker_id" class="rounded-xl border border-border p-4">
          <div class="flex items-start justify-between gap-3">
            <div class="flex min-w-0 gap-3"><div class="rounded-xl bg-primary/8 p-2.5 text-primary"><Cpu class="size-5" /></div><div class="min-w-0"><p class="truncate font-semibold">{{ worker.name }}</p><p class="truncate font-mono text-xs text-muted-foreground">{{ worker.worker_id }}</p></div></div>
            <Badge :tone="['online', 'busy'].includes(worker.status) ? 'success' : worker.status === 'draining' ? 'warning' : 'neutral'">{{ worker.status }}</Badge>
          </div>
          <dl class="mt-5 grid grid-cols-2 gap-3 text-xs">
            <div class="rounded-lg bg-muted/55 p-3"><dt class="text-muted-foreground">Runtime</dt><dd class="mt-1 font-semibold">{{ worker.devices.map((item) => item.runtime).join(", ") || "—" }}</dd></div>
            <div class="rounded-lg bg-muted/55 p-3"><dt class="text-muted-foreground">并发</dt><dd class="mt-1 font-semibold">{{ worker.resources?.running_tasks ?? 0 }} / {{ worker.maximum_concurrency }}</dd></div>
            <div class="col-span-2 rounded-lg bg-muted/55 p-3"><dt class="text-muted-foreground">Backend</dt><dd class="mt-1 truncate font-semibold">{{ worker.backends.map((item) => item.name).join(", ") || "—" }}</dd></div>
          </dl>
          <div v-if="worker.resources?.health_checks.length" class="mt-3 flex flex-wrap gap-2">
            <Badge v-for="check in worker.resources.health_checks" :key="check.name" :tone="check.healthy ? 'success' : 'danger'" :title="check.message ?? undefined">{{ check.name }} · {{ check.healthy ? "正常" : "异常" }}</Badge>
          </div>
          <div v-if="schedulingValues[worker.worker_id]" class="mt-4 grid grid-cols-2 gap-3">
            <label class="space-y-1.5 text-xs"><span class="font-semibold">最大并发</span><Input v-model="schedulingValues[worker.worker_id].maximumConcurrency" type="number" min="1" /></label>
            <label class="space-y-1.5 text-xs"><span class="font-semibold">调度权重</span><Input v-model="schedulingValues[worker.worker_id].schedulingWeight" type="number" min="1" max="1000" /></label>
          </div>
          <div class="mt-4 grid grid-cols-2 gap-2">
            <Button size="sm" variant="outline" :disabled="savingWorkerId === worker.worker_id" @click="saveScheduling(worker.worker_id)"><Save class="size-3.5" />保存调度</Button>
            <Button size="sm" :variant="worker.status === 'draining' ? 'default' : 'outline'" @click="setDraining(worker.worker_id, worker.status !== 'draining')"><Power class="size-3.5" />{{ worker.status === "draining" ? "恢复接单" : "进入 Drain" }}</Button>
          </div>
        </article>
        <p v-if="!workerItems.length" class="col-span-full py-16 text-center text-sm text-muted-foreground">{{ workersPending ? "正在加载…" : "尚无 Worker 注册" }}</p>
      </div>
    </Card>
    <PipelinesPanel v-else-if="route.params.section === 'pipelines'" />
    <BackendsPanel v-else-if="route.params.section === 'backends'" />
    <CallbacksPanel v-else-if="route.params.section === 'callbacks'" />
    <ApiKeysPanel v-else-if="route.params.section === 'api-keys'" />
    <SystemPanel v-else-if="route.params.section === 'settings'" />
    <Card v-else class="grid min-h-[320px] place-items-center border-dashed p-8 text-center text-sm text-muted-foreground">未知管理模块</Card>
  </div>
</template>

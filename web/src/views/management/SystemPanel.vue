<script setup lang="ts">
import { useQuery, useQueryClient } from "@tanstack/vue-query"
import { Database, FileJson2, Save, Server, ShieldCheck, SlidersHorizontal, Trash2 } from "lucide-vue-next"
import { computed, ref, watchEffect } from "vue"

import { ApiClientError, parserApi, type RetentionRun, type SettingKey } from "@/api/client"
import Badge from "@/components/ui/Badge.vue"
import Button from "@/components/ui/Button.vue"
import Card from "@/components/ui/Card.vue"
import Input from "@/components/ui/Input.vue"

const info = useQuery({ queryKey: ["system-info"], queryFn: parserApi.systemInfo })
const capabilities = useQuery({
  queryKey: ["capabilities"],
  queryFn: parserApi.capabilities,
})
const settings = useQuery({
  queryKey: ["system-settings"],
  queryFn: parserApi.systemSettings,
})
const queryClient = useQueryClient()
const system = computed(() => info.data.value?.data)
const capability = computed(() => capabilities.data.value?.data)
const maximumUploadMiB = ref("")
const maximumResultMiB = ref("")
const callbackAttempts = ref("")
const initialized = ref(false)
const saving = ref(false)
const message = ref("")
const error = ref("")
const retentionRunning = ref(false)
const retentionResult = ref<RetentionRun | null>(null)
const retentionError = ref("")

watchEffect(() => {
  if (initialized.value || !settings.data.value) return
  const values = Object.fromEntries(
    settings.data.value.data.settings.map((setting) => [
      setting.key,
      Number(setting.value),
    ]),
  )
  maximumUploadMiB.value = String(
    Math.round((values.maximum_upload_bytes ?? 0) / 1024 / 1024),
  )
  maximumResultMiB.value = String(
    Math.round((values.maximum_result_json_bytes ?? 0) / 1024 / 1024),
  )
  callbackAttempts.value = String(values.callback_maximum_attempts ?? 5)
  initialized.value = true
})

async function saveSettings() {
  saving.value = true
  message.value = ""
  error.value = ""
  const updates: Array<{ key: SettingKey; value: number }> = [
    {
      key: "maximum_upload_bytes",
      value: Number(maximumUploadMiB.value) * 1024 * 1024,
    },
    {
      key: "maximum_result_json_bytes",
      value: Number(maximumResultMiB.value) * 1024 * 1024,
    },
    {
      key: "callback_maximum_attempts",
      value: Number(callbackAttempts.value),
    },
  ]
  try {
    await parserApi.updateSystemSettings(updates)
    message.value = "动态设置已保存，并会在后续请求中立即生效。"
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["system-settings"] }),
      queryClient.invalidateQueries({ queryKey: ["capabilities"] }),
    ])
  } catch (caught) {
    error.value =
      caught instanceof ApiClientError ? caught.message : "系统设置保存失败"
  } finally {
    saving.value = false
  }
}

async function runRetention(dryRun: boolean) {
  if (
    !dryRun &&
    !window.confirm("确定删除当前已过期的上传文件、产物和可清理事件吗？")
  ) {
    return
  }
  retentionRunning.value = true
  retentionError.value = ""
  try {
    const response = await parserApi.runRetention(dryRun)
    retentionResult.value = response.data
  } catch (caught) {
    retentionError.value =
      caught instanceof ApiClientError ? caught.message : "保留策略执行失败"
  } finally {
    retentionRunning.value = false
  }
}
</script>

<template>
  <div class="space-y-5">
  <div class="grid gap-5 xl:grid-cols-2">
    <Card class="p-5">
      <div class="flex items-center gap-3"><div class="rounded-xl bg-primary/8 p-2.5 text-primary"><Server class="size-5" /></div><div><h2 class="section-title">版本信息</h2><p class="text-sm text-muted-foreground">来自受 API Key 保护的系统接口。</p></div></div>
      <dl class="mt-6 divide-y divide-border text-sm">
        <div class="flex justify-between py-3"><dt class="text-muted-foreground">服务</dt><dd class="font-semibold">{{ system?.name ?? "—" }}</dd></div>
        <div class="flex justify-between py-3"><dt class="text-muted-foreground">应用版本</dt><dd class="font-mono">{{ system?.version ?? "—" }}</dd></div>
        <div class="flex justify-between py-3"><dt class="text-muted-foreground">API Schema</dt><dd class="font-mono">{{ system?.api_version ?? "—" }}</dd></div>
        <div class="flex justify-between py-3"><dt class="text-muted-foreground">Result Schema</dt><dd class="font-mono">{{ system?.result_schema_version ?? "—" }}</dd></div>
        <div class="flex justify-between py-3"><dt class="text-muted-foreground">构建提交</dt><dd class="font-mono">{{ system?.build_commit ?? "未注入" }}</dd></div>
      </dl>
    </Card>
    <Card class="p-5">
      <div class="flex items-center gap-3"><div class="rounded-xl bg-violet-100 p-2.5 text-violet-700"><ShieldCheck class="size-5" /></div><div><h2 class="section-title">运行边界</h2><p class="text-sm text-muted-foreground">当前控制面公开限制和在线 Runtime。</p></div></div>
      <div class="mt-6 grid grid-cols-2 gap-3">
        <div class="rounded-xl bg-muted/55 p-4"><Database class="size-4 text-muted-foreground" /><p class="mt-3 text-xs text-muted-foreground">最大上传</p><p class="mt-1 font-display text-xl font-bold">{{ capability ? `${Math.round(capability.maximum_upload_bytes / 1024 / 1024)} MiB` : "—" }}</p></div>
        <div class="rounded-xl bg-muted/55 p-4"><FileJson2 class="size-4 text-muted-foreground" /><p class="mt-3 text-xs text-muted-foreground">媒体类型</p><p class="mt-1 font-display text-xl font-bold">{{ capability?.media_categories.length ?? 0 }}</p></div>
      </div>
      <div class="mt-5"><p class="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">在线 Runtime</p><div class="flex flex-wrap gap-2"><Badge v-for="runtime in capability?.runtimes ?? []" :key="runtime.runtime" tone="info">{{ runtime.runtime }} · {{ runtime.available_devices }} 设备</Badge><span v-if="!capability?.runtimes.length" class="text-sm text-muted-foreground">暂无在线设备</span></div></div>
      <p class="mt-6 rounded-xl border border-border bg-muted/35 p-3 text-xs leading-5 text-muted-foreground">页面只开放已经接入运行路径的动态参数。驱动、模型、数据库地址等部署级设置仍由镜像和环境变量管理。</p>
    </Card>
  </div>
  <Card class="p-5">
    <div class="flex items-center gap-3"><div class="rounded-xl bg-amber-100 p-2.5 text-amber-800"><SlidersHorizontal class="size-5" /></div><div><h2 class="section-title">动态设置</h2><p class="text-sm text-muted-foreground">数据库覆盖值在多控制面副本间共享，不需要重启服务。</p></div></div>
    <form class="mt-5 grid gap-4 md:grid-cols-3" @submit.prevent="saveSettings">
      <label class="space-y-2 text-sm"><span class="font-semibold">最大上传（MiB）</span><Input v-model="maximumUploadMiB" type="number" /><span class="block text-xs text-muted-foreground">同时限制原始文件和 Worker Artifact。</span></label>
      <label class="space-y-2 text-sm"><span class="font-semibold">最大结果 JSON（MiB）</span><Input v-model="maximumResultMiB" type="number" /><span class="block text-xs text-muted-foreground">HTTP 与 MCP 结果读取共享此限制。</span></label>
      <label class="space-y-2 text-sm"><span class="font-semibold">回调最大尝试次数</span><Input v-model="callbackAttempts" type="number" /><span class="block text-xs text-muted-foreground">范围 1–20，对新建投递生效。</span></label>
      <div class="md:col-span-3 flex items-center justify-between gap-4 border-t border-border pt-4"><div><p v-if="message" class="text-sm text-emerald-700">{{ message }}</p><p v-if="error" class="text-sm text-red-700">{{ error }}</p></div><Button type="submit" :disabled="saving || !initialized"><Save class="size-4" />保存设置</Button></div>
    </form>
  </Card>
  <Card class="p-5">
    <div class="flex flex-wrap items-start justify-between gap-4">
      <div class="flex items-center gap-3">
        <div class="rounded-xl bg-red-100 p-2.5 text-red-700"><Trash2 class="size-5" /></div>
        <div><h2 class="section-title">数据保留清理</h2><p class="text-sm text-muted-foreground">按部署级保留周期清理对象存储与数据库记录，活跃任务和待物化回调事件会自动保留。</p></div>
      </div>
      <div class="flex gap-2">
        <Button variant="outline" :disabled="retentionRunning" @click="runRetention(true)">试运行</Button>
        <Button variant="destructive" :disabled="retentionRunning" @click="runRetention(false)">执行清理</Button>
      </div>
    </div>
    <div v-if="retentionResult" class="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      <div class="rounded-xl bg-muted/55 p-4"><p class="text-xs text-muted-foreground">上传文件</p><p class="mt-1 text-xl font-bold">{{ retentionResult.uploaded_files_selected }}</p><p class="text-xs text-muted-foreground">活跃跳过 {{ retentionResult.uploaded_files_skipped_active }}</p></div>
      <div class="rounded-xl bg-muted/55 p-4"><p class="text-xs text-muted-foreground">Artifact</p><p class="mt-1 text-xl font-bold">{{ retentionResult.artifacts_selected }}</p><p class="text-xs text-muted-foreground">活跃跳过 {{ retentionResult.artifacts_skipped_active }}</p></div>
      <div class="rounded-xl bg-muted/55 p-4"><p class="text-xs text-muted-foreground">事件</p><p class="mt-1 text-xl font-bold">{{ retentionResult.events_selected }}</p><p class="text-xs text-muted-foreground">{{ retentionResult.dry_run ? "仅统计，未删除" : "已执行删除" }}</p></div>
      <div class="rounded-xl bg-muted/55 p-4"><p class="text-xs text-muted-foreground">存储删除失败</p><p class="mt-1 text-xl font-bold">{{ retentionResult.storage_delete_failures }}</p><p class="text-xs text-muted-foreground">失败项保留元数据以便重试</p></div>
    </div>
    <p v-if="retentionError" class="mt-4 text-sm text-red-700">{{ retentionError }}</p>
  </Card>
  </div>
</template>

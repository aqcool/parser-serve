<script setup lang="ts">
import { useQuery, useQueryClient } from "@tanstack/vue-query"
import { Copy, KeyRound, Plus, RefreshCw, RotateCcw, Trash2 } from "lucide-vue-next"
import { computed, ref } from "vue"

import { ApiClientError, parserApi } from "@/api/client"
import Badge from "@/components/ui/Badge.vue"
import Button from "@/components/ui/Button.vue"
import Card from "@/components/ui/Card.vue"
import Input from "@/components/ui/Input.vue"

const queryClient = useQueryClient()
const query = useQuery({
  queryKey: ["api-keys", "management"],
  queryFn: parserApi.apiKeys,
})
const items = computed(() => query.data.value?.items ?? [])
const name = ref("")
const kind = ref<"ordinary" | "worker">("ordinary")
const workerId = ref("")
const revealedKey = ref("")
const busy = ref<string | null>(null)
const error = ref("")

async function createKey() {
  busy.value = "create"
  error.value = ""
  revealedKey.value = ""
  try {
    const response = await parserApi.createApiKey({
      name: name.value,
      kind: kind.value,
      ...(kind.value === "worker" ? { worker_id: workerId.value } : {}),
    })
    revealedKey.value = response.data.api_key
    name.value = ""
    workerId.value = ""
    await queryClient.invalidateQueries({ queryKey: ["api-keys"] })
  } catch (caught) {
    error.value = caught instanceof ApiClientError ? caught.message : "API Key 创建失败"
  } finally {
    busy.value = null
  }
}

async function toggle(apiKeyId: string, enabled: boolean) {
  busy.value = apiKeyId
  error.value = ""
  try {
    await parserApi.updateApiKey(apiKeyId, { enabled })
    await queryClient.invalidateQueries({ queryKey: ["api-keys"] })
  } catch (caught) {
    error.value = caught instanceof ApiClientError ? caught.message : "API Key 更新失败"
  } finally {
    busy.value = null
  }
}

async function rotate(apiKeyId: string) {
  busy.value = apiKeyId
  error.value = ""
  try {
    const response = await parserApi.rotateApiKey(apiKeyId)
    revealedKey.value = response.data.api_key
    await queryClient.invalidateQueries({ queryKey: ["api-keys"] })
  } catch (caught) {
    error.value = caught instanceof ApiClientError ? caught.message : "API Key 轮换失败"
  } finally {
    busy.value = null
  }
}

async function remove(apiKeyId: string, keyName: string) {
  if (!window.confirm(`确定删除 API Key“${keyName}”？此操作不可撤销。`)) return
  busy.value = apiKeyId
  error.value = ""
  try {
    await parserApi.deleteApiKey(apiKeyId)
    await queryClient.invalidateQueries({ queryKey: ["api-keys"] })
  } catch (caught) {
    error.value = caught instanceof ApiClientError ? caught.message : "API Key 删除失败"
  } finally {
    busy.value = null
  }
}

async function copyKey() {
  await navigator.clipboard.writeText(revealedKey.value)
}
</script>

<template>
  <div class="space-y-5">
    <Card class="p-5">
      <div class="flex items-center gap-3"><div class="rounded-xl bg-primary/8 p-2.5 text-primary"><Plus class="size-5" /></div><div><h2 class="section-title">创建 API Key</h2><p class="text-sm text-muted-foreground">普通 Key 可访问业务和全部管理接口；Worker Key 绑定一个 Worker ID。</p></div></div>
      <form class="mt-5 grid gap-3 lg:grid-cols-[1fr_170px_1fr_auto]" @submit.prevent="createKey">
        <Input v-model="name" placeholder="Key 名称" />
        <select v-model="kind" class="h-10 rounded-lg border border-input bg-background px-3 text-sm outline-none focus:ring-2 focus:ring-ring"><option value="ordinary">普通 Key</option><option value="worker">Worker Key</option></select>
        <Input v-model="workerId" :disabled="kind !== 'worker'" placeholder="worker_xxxxxxxx" />
        <Button type="submit" :disabled="!name || (kind === 'worker' && !workerId) || busy !== null"><Plus class="size-4" />创建</Button>
      </form>
      <div v-if="revealedKey" class="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-4">
        <p class="text-xs font-semibold text-amber-900">只显示一次，请立即保存</p>
        <div class="mt-2 flex gap-2"><code class="min-w-0 flex-1 overflow-x-auto rounded-lg bg-white px-3 py-2 text-xs">{{ revealedKey }}</code><Button size="sm" variant="outline" @click="copyKey"><Copy class="size-3.5" />复制</Button></div>
      </div>
      <p v-if="error" class="mt-3 text-sm text-red-700">{{ error }}</p>
    </Card>
    <Card class="overflow-hidden">
      <div class="flex items-center justify-between border-b border-border p-4"><p class="text-sm font-semibold">{{ items.length }} 个 API Key</p><Button size="sm" variant="outline" @click="query.refetch()"><RefreshCw class="size-3.5" />刷新</Button></div>
      <div class="divide-y divide-border">
        <article v-for="key in items" :key="key.api_key_id" class="grid gap-3 p-4 lg:grid-cols-[1fr_130px_150px_auto] lg:items-center">
          <div class="flex min-w-0 gap-3"><div class="rounded-lg bg-muted p-2 text-muted-foreground"><KeyRound class="size-4" /></div><div class="min-w-0"><p class="truncate font-semibold">{{ key.name }}</p><p class="mt-1 font-mono text-xs text-muted-foreground">{{ key.prefix }}… · {{ key.api_key_id }}</p></div></div>
          <Badge class="w-fit" :tone="key.kind === 'worker' ? 'info' : 'neutral'">{{ key.kind }}</Badge>
          <div><Badge :tone="key.status === 'active' ? 'success' : key.status === 'expired' ? 'danger' : 'neutral'">{{ key.status }}</Badge><p class="mt-1 text-xs text-muted-foreground">{{ key.last_used_at ? `最近 ${new Date(key.last_used_at).toLocaleString()}` : "尚未使用" }}</p></div>
          <div class="flex justify-end gap-1">
            <Button size="sm" variant="ghost" :disabled="busy === key.api_key_id" @click="toggle(key.api_key_id, key.status !== 'active')">{{ key.status === "active" ? "停用" : "启用" }}</Button>
            <Button size="icon" variant="ghost" :disabled="busy === key.api_key_id" aria-label="轮换 API Key" @click="rotate(key.api_key_id)"><RotateCcw class="size-4" /></Button>
            <Button size="icon" variant="ghost" :disabled="busy === key.api_key_id" aria-label="删除 API Key" @click="remove(key.api_key_id, key.name)"><Trash2 class="size-4 text-red-600" /></Button>
          </div>
        </article>
        <div v-if="!items.length" class="grid min-h-64 place-items-center p-8 text-sm text-muted-foreground">{{ query.isPending.value ? "正在读取 API Key…" : "数据库中尚无可管理 API Key" }}</div>
      </div>
    </Card>
  </div>
</template>

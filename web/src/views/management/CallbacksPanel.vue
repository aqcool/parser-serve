<script setup lang="ts">
import { useQuery, useQueryClient } from "@tanstack/vue-query"
import { RefreshCw, RotateCcw, Send, Webhook } from "lucide-vue-next"
import { computed, ref } from "vue"

import {
  ApiClientError,
  parserApi,
  type CallbackAttempt,
} from "@/api/client"
import Badge from "@/components/ui/Badge.vue"
import Button from "@/components/ui/Button.vue"
import Card from "@/components/ui/Card.vue"
import Input from "@/components/ui/Input.vue"

const queryClient = useQueryClient()
const query = useQuery({
  queryKey: ["callbacks", "management"],
  queryFn: parserApi.callbacks,
})
const items = computed(() => query.data.value?.items ?? [])
const url = ref("")
const secret = ref("")
const busy = ref<string | null>(null)
const message = ref("")
const error = ref("")
const selectedDeliveryId = ref<string | null>(null)
const attempts = ref<CallbackAttempt[]>([])

async function testDelivery() {
  busy.value = "test"
  message.value = ""
  error.value = ""
  try {
    const response = await parserApi.testCallback(url.value, secret.value || undefined)
    message.value = response.data.delivered
      ? `投递成功：HTTP ${response.data.response_status_code ?? "—"}，${response.data.duration_ms} ms`
      : `投递失败：${response.data.error?.message ?? "未知错误"}`
  } catch (caught) {
    error.value =
      caught instanceof ApiClientError ? caught.message : "回调测试失败"
  } finally {
    busy.value = null
  }
}

async function retry(deliveryId: string) {
  busy.value = deliveryId
  error.value = ""
  try {
    await parserApi.retryCallback(deliveryId)
    await queryClient.invalidateQueries({ queryKey: ["callbacks"] })
  } catch (caught) {
    error.value =
      caught instanceof ApiClientError ? caught.message : "重新投递失败"
  } finally {
    busy.value = null
  }
}

async function showAttempts(deliveryId: string) {
  if (selectedDeliveryId.value === deliveryId) {
    selectedDeliveryId.value = null
    attempts.value = []
    return
  }
  busy.value = `history:${deliveryId}`
  error.value = ""
  try {
    const response = await parserApi.callbackAttempts(deliveryId)
    selectedDeliveryId.value = deliveryId
    attempts.value = response.items
  } catch (caught) {
    error.value =
      caught instanceof ApiClientError ? caught.message : "读取投递历史失败"
  } finally {
    busy.value = null
  }
}

function tone(
  status: string,
): "neutral" | "success" | "warning" | "danger" | "info" {
  if (status === "succeeded") return "success"
  if (status === "failed" || status === "cancelled") return "danger"
  if (status === "retry_wait") return "warning"
  return "info"
}
</script>

<template>
  <div class="space-y-5">
    <Card class="p-5">
      <div class="flex items-center gap-3"><div class="rounded-xl bg-primary/8 p-2.5 text-primary"><Send class="size-5" /></div><div><h2 class="section-title">测试回调</h2><p class="text-sm text-muted-foreground">发送签名测试事件，不创建业务任务。</p></div></div>
      <form class="mt-5 grid gap-3 lg:grid-cols-[1fr_1fr_auto]" @submit.prevent="testDelivery">
        <Input v-model="url" type="url" placeholder="https://example.com/callback" />
        <Input v-model="secret" type="password" autocomplete="new-password" placeholder="签名密钥（可选，至少 32 字符）" />
        <Button type="submit" :disabled="!url || busy !== null"><Send class="size-4" />发送测试</Button>
      </form>
      <p v-if="message" class="mt-3 text-sm text-emerald-700">{{ message }}</p>
      <p v-if="error" class="mt-3 text-sm text-red-700">{{ error }}</p>
    </Card>
    <Card class="overflow-hidden">
      <div class="flex items-center justify-between border-b border-border p-4"><p class="text-sm font-semibold">{{ items.length }} 条投递记录</p><Button size="sm" variant="outline" @click="query.refetch()"><RefreshCw class="size-3.5" />刷新</Button></div>
      <div class="divide-y divide-border">
        <template v-for="delivery in items" :key="delivery.delivery_id">
          <article class="grid gap-3 p-4 lg:grid-cols-[1fr_160px_130px_auto] lg:items-center">
            <div class="flex min-w-0 gap-3"><div class="rounded-lg bg-muted p-2 text-muted-foreground"><Webhook class="size-4" /></div><div class="min-w-0"><p class="truncate font-mono text-sm font-semibold">{{ delivery.delivery_id }}</p><p class="mt-1 truncate text-xs text-muted-foreground">{{ delivery.event.payload.type }} · {{ delivery.target_url }}</p></div></div>
            <p class="text-xs text-muted-foreground">本轮 {{ delivery.attempt }} / {{ delivery.maximum_attempts }} · 累计 {{ delivery.total_attempts }}</p>
            <Badge class="w-fit" :tone="tone(delivery.status)">{{ delivery.status }}<span v-if="delivery.response_status_code"> · {{ delivery.response_status_code }}</span></Badge>
            <div class="flex gap-2">
              <Button size="sm" variant="outline" :disabled="busy !== null" @click="showAttempts(delivery.delivery_id)">历史</Button>
              <Button v-if="['failed', 'cancelled'].includes(delivery.status)" size="sm" variant="outline" :disabled="busy === delivery.delivery_id" @click="retry(delivery.delivery_id)"><RotateCcw class="size-3.5" />重试</Button>
            </div>
          </article>
          <div v-if="selectedDeliveryId === delivery.delivery_id" class="bg-muted/30 px-4 pb-4">
            <div class="overflow-x-auto rounded-lg border border-border bg-background">
              <table class="w-full min-w-[760px] text-left text-xs">
                <thead class="border-b border-border text-muted-foreground"><tr><th class="p-3">序号</th><th class="p-3">本轮</th><th class="p-3">结果</th><th class="p-3">HTTP</th><th class="p-3">耗时</th><th class="p-3">响应 / 错误</th><th class="p-3">完成时间</th></tr></thead>
                <tbody>
                  <tr v-for="attempt in attempts" :key="attempt.attempt_id" class="border-b border-border last:border-0">
                    <td class="p-3 font-mono">#{{ attempt.sequence }}</td><td class="p-3">{{ attempt.attempt_number }}</td>
                    <td class="p-3"><Badge :tone="attempt.delivered ? 'success' : 'danger'">{{ attempt.delivered ? "成功" : "失败" }}</Badge></td>
                    <td class="p-3">{{ attempt.response_status_code ?? "—" }}</td><td class="p-3">{{ attempt.duration_ms }} ms</td>
                    <td class="max-w-xs truncate p-3 text-muted-foreground">{{ attempt.error?.message ?? attempt.response_summary ?? "—" }}</td>
                    <td class="p-3 text-muted-foreground">{{ new Date(attempt.completed_at).toLocaleString() }}</td>
                  </tr>
                  <tr v-if="!attempts.length"><td class="p-4 text-muted-foreground" colspan="7">尚无投递尝试</td></tr>
                </tbody>
              </table>
            </div>
          </div>
        </template>
        <div v-if="!items.length" class="grid min-h-64 place-items-center p-8 text-sm text-muted-foreground">{{ query.isPending.value ? "正在读取回调…" : "尚无回调投递记录" }}</div>
      </div>
    </Card>
  </div>
</template>

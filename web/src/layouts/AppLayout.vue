<script setup lang="ts">
import {
  Activity,
  Boxes,
  Cpu,
  FileSearch,
  Gauge,
  KeyRound,
  ListTodo,
  RadioTower,
  Settings,
  TestTube2,
  Webhook,
} from "lucide-vue-next"
import { RouterLink, RouterView, useRouter } from "vue-router"

import Button from "@/components/ui/Button.vue"
import { useConnectionStore } from "@/stores/connection"

const connection = useConnectionStore()
const router = useRouter()

const navigation = [
  { label: "总览", to: "/", icon: Gauge },
  { label: "解析测试", to: "/test", icon: TestTube2 },
  { label: "任务", to: "/tasks", icon: ListTodo },
  { label: "Worker", to: "/management/workers", icon: Cpu },
  { label: "Pipeline", to: "/management/pipelines", icon: RadioTower },
  { label: "Backend", to: "/management/backends", icon: Boxes },
  { label: "回调", to: "/management/callbacks", icon: Webhook },
  { label: "API Key", to: "/management/api-keys", icon: KeyRound },
  { label: "系统信息", to: "/management/settings", icon: Settings },
]

function disconnect() {
  connection.clear()
  void router.push({ name: "connect" })
}
</script>

<template>
  <div class="min-h-screen bg-background text-foreground">
    <aside class="fixed inset-y-0 left-0 z-20 hidden w-64 flex-col border-r border-sidebar-border bg-sidebar text-sidebar-foreground lg:flex">
      <div class="flex h-20 items-center gap-3 border-b border-sidebar-border px-6">
        <div class="grid size-10 place-items-center rounded-xl bg-sidebar-primary text-sidebar-primary-foreground">
          <FileSearch class="size-5" />
        </div>
        <div>
          <p class="font-display text-base font-bold tracking-tight">Parser Serve</p>
          <p class="text-xs text-sidebar-foreground/55">Control Console</p>
        </div>
      </div>
      <nav class="flex-1 space-y-1 p-3" aria-label="主导航">
        <RouterLink
          v-for="item in navigation"
          :key="item.to"
          :to="item.to"
          class="flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium text-sidebar-foreground/65 transition hover:bg-sidebar-accent hover:text-sidebar-accent-foreground"
          active-class="!bg-sidebar-accent !text-sidebar-accent-foreground"
        >
          <component :is="item.icon" class="size-4" />
          {{ item.label }}
        </RouterLink>
      </nav>
      <div class="m-3 rounded-xl border border-sidebar-border bg-sidebar-accent/45 p-3">
        <div class="mb-2 flex items-center gap-2 text-xs text-sidebar-foreground/60">
          <Activity class="size-3.5 text-emerald-400" />
          当前连接
        </div>
        <p class="truncate text-xs font-medium">{{ connection.apiUrl }}</p>
        <Button variant="ghost" size="sm" class="mt-2 w-full text-sidebar-foreground/70 hover:bg-sidebar-accent" @click="disconnect">
          切换连接
        </Button>
      </div>
    </aside>

    <main class="min-h-screen lg:pl-64">
      <header class="sticky top-0 z-10 flex h-16 items-center justify-between border-b border-border bg-background/90 px-5 backdrop-blur md:px-8">
        <div>
          <p class="text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">Multimodal operations</p>
        </div>
        <div class="flex items-center gap-2 rounded-full border border-border bg-card px-3 py-1.5 text-xs">
          <span class="size-2 rounded-full bg-emerald-500 shadow-[0_0_0_4px_rgba(16,185,129,.12)]" />
          API 已连接
        </div>
      </header>
      <div class="mx-auto max-w-[1500px] p-5 md:p-8">
        <RouterView />
      </div>
    </main>
  </div>
</template>

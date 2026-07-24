<script setup lang="ts">
import { ArrowRight, FileSearch, KeyRound, Server } from "lucide-vue-next"
import { ref } from "vue"
import { useRouter } from "vue-router"

import { parserApi } from "@/api/client"
import Button from "@/components/ui/Button.vue"
import Card from "@/components/ui/Card.vue"
import Input from "@/components/ui/Input.vue"
import { useConnectionStore } from "@/stores/connection"

const connection = useConnectionStore()
const router = useRouter()
const apiUrl = ref(connection.apiUrl)
const apiKey = ref(connection.apiKey)
const error = ref("")
const testing = ref(false)

async function connect() {
  error.value = ""
  testing.value = true
  connection.save(apiUrl.value, apiKey.value)
  try {
    await parserApi.capabilities()
    await router.push("/")
  } catch (reason) {
    connection.clear()
    error.value = reason instanceof Error ? reason.message : "连接失败"
  } finally {
    testing.value = false
  }
}
</script>

<template>
  <main class="relative grid min-h-screen place-items-center overflow-hidden bg-[#08120f] p-5 text-white">
    <div class="absolute inset-0 opacity-40 [background-image:radial-gradient(circle_at_20%_20%,#356859_0,transparent_33%),radial-gradient(circle_at_80%_75%,#223d35_0,transparent_30%)]" />
    <div class="absolute inset-0 opacity-[0.08] [background-image:linear-gradient(#fff_1px,transparent_1px),linear-gradient(90deg,#fff_1px,transparent_1px)] [background-size:48px_48px]" />
    <div class="relative grid w-full max-w-5xl overflow-hidden rounded-[28px] border border-white/10 bg-white/[0.055] shadow-2xl backdrop-blur-xl md:grid-cols-[1.1fr_.9fr]">
      <section class="flex min-h-[560px] flex-col justify-between p-8 md:p-12">
        <div class="flex items-center gap-3">
          <div class="grid size-11 place-items-center rounded-2xl bg-lime-300 text-[#0a1713]">
            <FileSearch class="size-6" />
          </div>
          <span class="font-display font-bold">Parser Serve</span>
        </div>
        <div class="max-w-lg">
          <p class="mb-4 text-xs font-bold uppercase tracking-[0.24em] text-lime-300">One protocol · every medium</p>
          <h1 class="font-display text-4xl font-bold leading-[1.08] tracking-[-0.04em] md:text-6xl">
            让每一种内容<br />都可被理解。
          </h1>
          <p class="mt-6 max-w-md text-base leading-7 text-white/55">
            统一解析文档、图片、网页、音频与视频。连接控制面后即可测试 Pipeline、管理异构 Worker，并观察每一次任务流转。
          </p>
        </div>
        <div class="flex gap-5 text-xs text-white/40">
          <span>CPU / GPU / 国产硬件</span>
          <span>HTTP / MCP / Callback</span>
        </div>
      </section>

      <Card class="m-3 flex flex-col justify-center border-white/10 bg-white p-7 text-slate-950 md:m-5 md:p-10">
        <div class="mb-8">
          <p class="text-sm font-semibold text-emerald-700">控制台连接</p>
          <h2 class="mt-2 font-display text-3xl font-bold tracking-tight">欢迎回来</h2>
          <p class="mt-2 text-sm text-slate-500">密钥只保存在当前浏览器会话中。</p>
        </div>
        <form class="space-y-5" @submit.prevent="connect">
          <label class="block">
            <span class="mb-2 flex items-center gap-2 text-sm font-semibold"><Server class="size-4" /> API 地址</span>
            <Input v-model="apiUrl" placeholder="http://127.0.0.1:8000" autocomplete="url" />
          </label>
          <label class="block">
            <span class="mb-2 flex items-center gap-2 text-sm font-semibold"><KeyRound class="size-4" /> API Key</span>
            <Input v-model="apiKey" type="password" placeholder="parser_••••••••" autocomplete="off" />
          </label>
          <p v-if="error" role="alert" class="rounded-lg bg-red-50 p-3 text-sm text-red-700">{{ error }}</p>
          <Button type="submit" class="h-11 w-full bg-[#173f34] hover:bg-[#225b4b]" :disabled="testing || !apiKey">
            {{ testing ? "正在验证…" : "连接控制面" }}
            <ArrowRight class="size-4" />
          </Button>
        </form>
      </Card>
    </div>
  </main>
</template>

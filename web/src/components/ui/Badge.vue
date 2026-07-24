<script setup lang="ts">
import { cn } from "@/lib/utils"

withDefaults(
  defineProps<{
    tone?: "neutral" | "success" | "warning" | "danger" | "info"
    class?: string
  }>(),
  { tone: "neutral" },
)
</script>

<template>
  <span
    :class="
      cn(
        'inline-flex items-center rounded-full px-2.5 py-1 text-xs font-semibold',
        {
          'bg-muted text-muted-foreground': tone === 'neutral',
          'bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300': tone === 'success',
          'bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300': tone === 'warning',
          'bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300': tone === 'danger',
          'bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-300': tone === 'info',
        },
        $props.class,
      )
    "
  >
    <slot />
  </span>
</template>

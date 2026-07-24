<script setup lang="ts">
import { computed } from "vue"
import { cn } from "@/lib/utils"

const props = withDefaults(
  defineProps<{
    variant?: "default" | "outline" | "ghost" | "destructive"
    size?: "default" | "sm" | "icon"
    type?: "button" | "submit" | "reset"
    disabled?: boolean
    class?: string
  }>(),
  { variant: "default", size: "default", type: "button" },
)

const classes = computed(() =>
  cn(
    "inline-flex items-center justify-center gap-2 rounded-lg text-sm font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50",
    {
      "bg-primary text-primary-foreground hover:bg-primary/90":
        props.variant === "default",
      "border border-border bg-background hover:bg-muted":
        props.variant === "outline",
      "hover:bg-muted hover:text-foreground": props.variant === "ghost",
      "bg-destructive text-white hover:bg-destructive/90":
        props.variant === "destructive",
      "h-10 px-4 py-2": props.size === "default",
      "h-8 rounded-md px-3 text-xs": props.size === "sm",
      "size-10": props.size === "icon",
    },
    props.class,
  ),
)
</script>

<template>
  <button :type="type" :disabled="disabled" :class="classes">
    <slot />
  </button>
</template>

<script setup lang="ts">
import { cn } from "@/lib/utils"

defineProps<{
  modelValue?: string
  type?: string
  placeholder?: string
  class?: string
  autocomplete?: string
  disabled?: boolean
  min?: string | number
  max?: string | number
  step?: string | number
}>()

defineEmits<{ "update:modelValue": [value: string] }>()
</script>

<template>
  <input
    :value="modelValue"
    :type="type ?? 'text'"
    :placeholder="placeholder"
    :autocomplete="autocomplete"
    :disabled="disabled"
    :min="min"
    :max="max"
    :step="step"
    :class="
      cn(
        'h-10 w-full rounded-lg border border-input bg-background px-3 text-sm outline-none placeholder:text-muted-foreground focus:ring-2 focus:ring-ring',
        $props.class,
      )
    "
    @input="$emit('update:modelValue', ($event.target as HTMLInputElement).value)"
  />
</template>

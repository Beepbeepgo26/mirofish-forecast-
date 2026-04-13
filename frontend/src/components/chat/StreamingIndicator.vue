<script setup lang="ts">
import type { StageInfo } from '@/composables/useForecastStream'

defineProps<{ stages: StageInfo[] }>()
</script>

<template>
  <div class="bg-[#111118] border border-[#2e2e3e] rounded-xl px-4 py-3 space-y-2">
    <div
      v-for="stage in stages"
      :key="stage.name"
      class="flex items-center gap-3 text-sm transition-all duration-300"
      :class="{
        'text-[#6b7280]': stage.status === 'pending',
        'text-[#e5e7eb]': stage.status === 'active',
        'text-[#9ca3af]': stage.status === 'completed',
      }"
    >
      <!-- Icon / spinner / check -->
      <span v-if="stage.status === 'completed'" class="text-[#22c55e] text-xs">✓</span>
      <span
        v-else-if="stage.status === 'active' && stage.name === 'fast_inference'"
        class="text-[#f59e0b] text-xs"
        >⚡</span
      >
      <span v-else-if="stage.status === 'active'" class="animate-spin text-xs">◌</span>
      <span v-else class="text-xs opacity-40">○</span>

      <!-- Stage label -->
      <span class="flex-1">
        {{ stage.message }}
      </span>

      <!-- Progress bar for simulation -->
      <div
        v-if="stage.name === 'simulation' && stage.status === 'active' && stage.progress != null"
        class="flex items-center gap-2"
      >
        <div class="w-24 h-1.5 bg-[#2e2e3e] rounded-full overflow-hidden">
          <div
            class="h-full bg-[#2962FF] rounded-full transition-all duration-300"
            :style="{ width: `${(stage.progress ?? 0) * 100}%` }"
          />
        </div>
        <span class="text-xs font-mono text-[#9ca3af]">
          {{ Math.round((stage.progress ?? 0) * 100) }}%
        </span>
      </div>
    </div>
  </div>
</template>

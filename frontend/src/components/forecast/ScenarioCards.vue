<script setup lang="ts">

defineProps<{
  scenarioProbs: Record<string, number>
}>()

const scenarioConfig: Record<string, { label: string; color: string; icon: string }> = {
  most_probable: { label: 'Most Probable', color: '#22c55e', icon: '🎯' },
  secondary: { label: 'Secondary', color: '#f59e0b', icon: '🔄' },
  failure_trap: { label: 'Failure / Trap', color: '#ef4444', icon: '⚠️' },
}
</script>

<template>
  <div class="space-y-2">
    <div
      v-for="(config, rank) in scenarioConfig"
      :key="rank"
      class="flex items-center gap-3 bg-[#0a0a0f] rounded-lg px-4 py-3"
      :style="{ borderLeft: `3px solid ${config.color}` }"
    >
      <span class="text-lg">{{ config.icon }}</span>
      <div class="flex-1">
        <div class="text-sm font-medium text-[#e5e7eb]">{{ config.label }}</div>
      </div>
      <div
        class="font-mono text-sm font-semibold"
        :style="{ color: config.color }"
      >
        {{ ((scenarioProbs[rank] ?? 0) * 100).toFixed(0) }}%
      </div>
    </div>
  </div>
</template>

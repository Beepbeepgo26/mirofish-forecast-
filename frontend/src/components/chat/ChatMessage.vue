<script setup lang="ts">
import type { ChatEntry } from '@/stores/forecastStore'
import ForecastCard from '@/components/forecast/ForecastCard.vue'

defineProps<{ entry: ChatEntry }>()

function formatTime(date: Date): string {
  return date.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' })
}
</script>

<template>
  <!-- User query -->
  <div v-if="entry.type === 'query'" class="flex justify-end">
    <div class="max-w-[80%]">
      <div class="bg-[#2962FF] text-white rounded-2xl rounded-br-md px-4 py-2.5 text-sm">
        {{ entry.query }}
      </div>
      <div class="text-[10px] text-[#6b7280] mt-1 text-right font-mono">
        {{ formatTime(entry.timestamp) }}
        · {{ entry.simPreset }}
      </div>
    </div>
  </div>

  <!-- Forecast result -->
  <div v-else-if="entry.type === 'result' && entry.result" class="flex justify-start">
    <div class="max-w-full w-full">
      <ForecastCard :forecast="entry.result" />
      <div class="text-[10px] text-[#6b7280] mt-1 font-mono">
        {{ formatTime(entry.timestamp) }}
        · {{ entry.result.pipeline_duration_seconds.toFixed(0) }}s
        · {{ entry.result.successful_simulations }}/{{ entry.result.total_simulations }} sims
      </div>
    </div>
  </div>

  <!-- Error -->
  <div v-else-if="entry.type === 'error'" class="flex justify-start">
    <div class="bg-[#1a1a24] border border-[#ef4444]/30 rounded-xl px-4 py-3 text-sm text-[#ef4444]">
      {{ entry.errorMessage }}
    </div>
  </div>
</template>

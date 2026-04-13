<script setup lang="ts">
import { ref, computed } from 'vue'
import { useForecastStore } from '@/stores/forecastStore'

const store = useForecastStore()
const activeAgent = ref<'institutional' | 'retail' | 'market_maker'>(
  'institutional',
)

const latestForecast = computed(() => {
  const results = store.history.filter((e) => e.type === 'result' && e.result)
  if (results.length === 0) return null
  return results[results.length - 1].result!
})

const agents: {
  key: 'institutional' | 'retail' | 'market_maker'
  label: string
  icon: string
}[] = [
  { key: 'institutional', label: 'Institutional', icon: '🏛️' },
  { key: 'retail', label: 'Retail', icon: '👤' },
  { key: 'market_maker', label: 'Market Maker', icon: '⚖️' },
]

function getReasoningText(agentKey: string): string {
  if (!latestForecast.value) return 'Run a forecast to see agent reasoning.'
  switch (agentKey) {
    case 'institutional':
      return latestForecast.value.institutional_reasoning || 'No data'
    case 'retail':
      return latestForecast.value.retail_reasoning || 'No data'
    case 'market_maker':
      return latestForecast.value.market_maker_reasoning || 'No data'
    default:
      return 'No data'
  }
}

function getDirection(
  reasoning: string,
): 'bullish' | 'bearish' | 'neutral' {
  const lower = reasoning.toLowerCase()
  if (
    lower.startsWith('long') ||
    lower.startsWith('bullish') ||
    lower.includes('(long)')
  )
    return 'bullish'
  if (
    lower.startsWith('short') ||
    lower.startsWith('bearish') ||
    lower.includes('(short)')
  )
    return 'bearish'
  return 'neutral'
}

function getConfidence(reasoning: string): string | null {
  const match = reasoning.match(/\((\d+)%\)/)
  return match ? match[1] + '%' : null
}
</script>

<template>
  <div class="flex flex-col h-full bg-[#0a0a0f]">
    <!-- Agent tabs -->
    <div class="flex border-b border-[#2e2e3e] bg-[#111118] shrink-0">
      <button
        v-for="agent in agents"
        :key="agent.key"
        :class="[
          'flex-1 py-2 px-3 text-xs font-medium transition-colors',
          'flex items-center justify-center gap-1.5',
          activeAgent === agent.key
            ? 'text-[#2962FF] border-b-2 border-[#2962FF] bg-[#2962FF]/5'
            : 'text-[#6b7280] hover:text-[#9ca3af] hover:bg-[#1a1a24]',
        ]"
        @click="activeAgent = agent.key"
      >
        <span>{{ agent.icon }}</span>
        <span>{{ agent.label }}</span>
      </button>
    </div>

    <!-- Agent reasoning content -->
    <div class="flex-1 overflow-y-auto p-4">
      <template v-if="latestForecast">
        <!-- Direction badge -->
        <div class="flex items-center gap-2 mb-3">
          <span
            :class="[
              'text-xs font-medium px-2 py-0.5 rounded',
              getDirection(getReasoningText(activeAgent)) === 'bullish'
                ? 'bg-[#22c55e]/15 text-[#22c55e]'
                : getDirection(getReasoningText(activeAgent)) === 'bearish'
                  ? 'bg-[#ef4444]/15 text-[#ef4444]'
                  : 'bg-[#2e2e3e] text-[#9ca3af]',
            ]"
          >
            {{
              getDirection(getReasoningText(activeAgent)).toUpperCase()
            }}
          </span>
          <span
            v-if="getConfidence(getReasoningText(activeAgent))"
            class="text-xs font-mono text-[#9ca3af]"
          >
            {{ getConfidence(getReasoningText(activeAgent)) }} confidence
          </span>
        </div>

        <!-- Reasoning text -->
        <p class="text-sm text-[#e5e7eb] leading-relaxed whitespace-pre-line">
          {{ getReasoningText(activeAgent) }}
        </p>

        <!-- Metadata -->
        <div
          class="mt-4 pt-3 border-t border-[#2e2e3e] flex items-center gap-3 text-xs text-[#6b7280]"
        >
          <span>{{ latestForecast.instrument }}</span>
          <span>{{ latestForecast.forecast_horizon_minutes }}min horizon</span>
          <span
            >{{ latestForecast.successful_simulations }}/{{
              latestForecast.total_simulations
            }}
            sims</span
          >
          <span>{{ latestForecast.pipeline_duration_seconds.toFixed(1) }}s</span>
        </div>
      </template>

      <template v-else>
        <div
          class="flex flex-col items-center justify-center h-full text-[#6b7280] text-sm gap-2"
        >
          <span class="text-2xl">🏛️</span>
          <span>Run a forecast to see agent reasoning</span>
        </div>
      </template>
    </div>
  </div>
</template>

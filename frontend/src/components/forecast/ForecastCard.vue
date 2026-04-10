<script setup lang="ts">
import { ref } from 'vue'
import type { ForecastResult } from '@/types/forecast'
import ProbabilityChart from './ProbabilityChart.vue'
import ScenarioCards from './ScenarioCards.vue'
import AgentTraces from './AgentTraces.vue'

defineProps<{ forecast: ForecastResult }>()
const activeTab = ref<'chart' | 'scenarios' | 'agents'>('chart')
</script>

<template>
  <div class="bg-[#111118] border border-[#2e2e3e] rounded-xl overflow-hidden">
    <!-- Forecast text -->
    <div class="px-5 pt-4 pb-3">
      <p class="text-sm text-[#e5e7eb] leading-relaxed">
        {{ forecast.forecast_text }}
      </p>
    </div>

    <!-- Key stats row -->
    <div class="flex items-center gap-4 px-5 py-2 border-t border-[#2e2e3e] bg-[#0a0a0f]/50">
      <div class="text-center">
        <div class="text-xs text-[#6b7280]">Current</div>
        <div class="font-mono text-sm font-semibold text-[#e5e7eb]">
          {{ forecast.current_price.toFixed(2) }}
        </div>
      </div>
      <div class="text-center">
        <div class="text-xs text-[#6b7280]">Median</div>
        <div
          class="font-mono text-sm font-semibold"
          :class="forecast.distribution.median > forecast.current_price ? 'text-[#22c55e]' : forecast.distribution.median < forecast.current_price ? 'text-[#ef4444]' : 'text-[#e5e7eb]'"
        >
          {{ forecast.distribution.median.toFixed(2) }}
        </div>
      </div>
      <div class="text-center">
        <div class="text-xs text-[#6b7280]">Range (50%)</div>
        <div class="font-mono text-xs text-[#9ca3af]">
          {{ forecast.distribution.percentile_25.toFixed(0) }}–{{ forecast.distribution.percentile_75.toFixed(0) }}
        </div>
      </div>
      <div class="flex-1" />
      <div class="flex items-center gap-2">
        <span class="text-xs px-2 py-0.5 rounded font-mono"
          :class="forecast.distribution.prob_up > 0.5 ? 'bg-[#22c55e]/15 text-[#22c55e]' : forecast.distribution.prob_down > 0.5 ? 'bg-[#ef4444]/15 text-[#ef4444]' : 'bg-[#2e2e3e] text-[#9ca3af]'"
        >
          ↑{{ (forecast.distribution.prob_up * 100).toFixed(0) }}%
        </span>
        <span class="text-xs px-2 py-0.5 rounded font-mono bg-[#2e2e3e] text-[#9ca3af]">
          →{{ (forecast.distribution.prob_flat * 100).toFixed(0) }}%
        </span>
        <span class="text-xs px-2 py-0.5 rounded font-mono"
          :class="forecast.distribution.prob_down > 0.5 ? 'bg-[#ef4444]/15 text-[#ef4444]' : 'bg-[#2e2e3e] text-[#9ca3af]'"
        >
          ↓{{ (forecast.distribution.prob_down * 100).toFixed(0) }}%
        </span>
      </div>
    </div>

    <!-- Tab buttons -->
    <div class="flex border-t border-[#2e2e3e]">
      <button
        v-for="tab in (['chart', 'scenarios', 'agents'] as const)"
        :key="tab"
        :class="[
          'flex-1 py-2 text-xs font-medium transition-colors',
          activeTab === tab
            ? 'text-[#2962FF] border-b-2 border-[#2962FF]'
            : 'text-[#6b7280] hover:text-[#9ca3af]',
        ]"
        @click="activeTab = tab"
      >
        {{ tab === 'chart' ? 'Distribution' : tab === 'scenarios' ? 'Scenarios' : 'Agents' }}
      </button>
    </div>

    <!-- Tab content -->
    <div class="p-4">
      <ProbabilityChart
        v-if="activeTab === 'chart'"
        :distribution="forecast.distribution"
        :current-price="forecast.current_price"
      />
      <ScenarioCards
        v-if="activeTab === 'scenarios'"
        :scenario-probs="forecast.distribution.scenario_probs"
      />
      <AgentTraces
        v-if="activeTab === 'agents'"
        :institutional="forecast.institutional_reasoning"
        :retail="forecast.retail_reasoning"
        :market-maker="forecast.market_maker_reasoning"
      />
    </div>
  </div>
</template>

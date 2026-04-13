<script setup lang="ts">
import { computed } from 'vue'
import { Splitpanes, Pane } from 'splitpanes'
import 'splitpanes/dist/splitpanes.css'
import PriceChart from '@/components/chart/PriceChart.vue'
import ChatContainer from '@/components/chat/ChatContainer.vue'
import AgentPanel from '@/components/agents/AgentPanel.vue'
import StatusBar from './StatusBar.vue'
import { usePriceData } from '@/components/chart/usePriceData'
import { useForecastStore } from '@/stores/forecastStore'
import type { ForecastOverlay } from '@/types/chart'

const store = useForecastStore()
const { bars } = usePriceData(
  computed(() => store.activeInstrument),
  computed(() => store.chartInterval),
)

// Build chart overlay from latest forecast
const overlay = computed<ForecastOverlay | null>(() => {
  const results = store.history.filter((e) => e.type === 'result' && e.result)
  if (results.length === 0) return null
  const f = results[results.length - 1].result!
  return {
    forecastId: f.forecast_id,
    startTime: Math.floor(new Date(f.created_at).getTime() / 1000),
    endTime:
      Math.floor(new Date(f.created_at).getTime() / 1000) +
      f.forecast_horizon_minutes * 60,
    currentPrice: f.current_price,
    median: f.distribution.median,
    p5: f.distribution.percentile_5,
    p25: f.distribution.percentile_25,
    p75: f.distribution.percentile_75,
    p95: f.distribution.percentile_95,
  }
})
</script>

<template>
  <div class="flex flex-col h-full">
    <!-- Desktop: splitpanes -->
    <div class="hidden md:flex flex-1 overflow-hidden">
      <Splitpanes class="h-full">
        <!-- Left: Price chart -->
        <Pane :size="55" :min-size="25">
          <PriceChart
            :bars="bars"
            :instrument="store.activeInstrument"
            :overlay="overlay"
          />
        </Pane>

        <!-- Right: Chat + Agents -->
        <Pane :size="45" :min-size="25">
          <Splitpanes horizontal class="h-full">
            <!-- Top: Chat -->
            <Pane :size="65" :min-size="30">
              <ChatContainer class="h-full" />
            </Pane>

            <!-- Bottom: Agent panel -->
            <Pane :size="35" :min-size="15">
              <AgentPanel />
            </Pane>
          </Splitpanes>
        </Pane>
      </Splitpanes>
    </div>

    <!-- Mobile: chat only -->
    <div class="md:hidden flex-1 overflow-hidden">
      <ChatContainer class="h-full" />
    </div>

    <!-- Status bar -->
    <StatusBar />
  </div>
</template>

<style>
/* Splitpanes theme overrides for dark trading terminal */
.splitpanes--vertical > .splitpanes__splitter {
  width: 4px;
  background: #2e2e3e;
  border: none;
  cursor: col-resize;
  transition: background 0.15s ease;
}
.splitpanes--vertical > .splitpanes__splitter:hover {
  background: #2962ff;
}
.splitpanes--horizontal > .splitpanes__splitter {
  height: 4px;
  background: #2e2e3e;
  border: none;
  cursor: row-resize;
  transition: background 0.15s ease;
}
.splitpanes--horizontal > .splitpanes__splitter:hover {
  background: #2962ff;
}
/* Remove default splitpanes borders/backgrounds */
.splitpanes__pane {
  background: #0a0a0f;
}
.splitpanes__splitter::before,
.splitpanes__splitter::after {
  display: none;
}
</style>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'

interface CalibrationStatus {
  summary: {
    total_forecasts: number
    scored_forecasts: number
    pending_forecasts: number
    calibration_ready: boolean
    direction_accuracy: number | null
    p50_coverage: number | null
    p90_coverage: number | null
    mean_absolute_error: number | null
    ece: number | null
    sample_size: number | null
  }
}

interface MLStatus {
  models_available: boolean
  last_train_status: string | null
}

const status = ref<CalibrationStatus | null>(null)
const mlStatus = ref<MLStatus | null>(null)
let interval: ReturnType<typeof setInterval> | null = null

async function fetchStatus(): Promise<void> {
  try {
    const [calRes, mlRes] = await Promise.all([
      fetch('/api/forecast/calibration'),
      fetch('/api/ml/status'),
    ])
    if (calRes.ok) {
      status.value = await calRes.json()
    }
    if (mlRes.ok) {
      mlStatus.value = await mlRes.json()
    }
  } catch {
    // Silent fail — status bar is non-critical
  }
}

onMounted(() => {
  fetchStatus()
  interval = setInterval(fetchStatus, 120000) // Every 2 minutes
})

onUnmounted(() => {
  if (interval) clearInterval(interval)
})
</script>

<template>
  <footer
    class="flex items-center justify-between px-4 py-1.5 border-t border-[#2e2e3e] bg-[#111118] text-[10px] font-mono text-[#6b7280] shrink-0"
  >
    <div class="flex items-center gap-4">
      <template v-if="status?.summary">
        <span>
          Calibration:
          <span
            :class="
              status.summary.calibration_ready
                ? 'text-[#22c55e]'
                : 'text-[#f59e0b]'
            "
          >
            {{ status.summary.calibration_ready ? 'Active' : 'Warming up' }}
          </span>
        </span>
        <span> Scored: {{ status.summary.scored_forecasts }} </span>
        <span v-if="status.summary.direction_accuracy !== null">
          Dir:
          {{ (status.summary.direction_accuracy * 100).toFixed(0) }}%
        </span>
        <span v-if="status.summary.p90_coverage !== null">
          P90 cov:
          {{ (status.summary.p90_coverage * 100).toFixed(0) }}%
        </span>
      </template>
      <template v-else>
        <span class="text-[#6b7280]">Calibration loading…</span>
      </template>

      <!-- Fast path model status -->
      <span v-if="mlStatus" class="border-l border-[#2e2e3e] pl-4">
        Fast Path:
        <span
          :class="
            mlStatus.models_available
              ? 'text-[#22c55e]'
              : 'text-[#6b7280]'
          "
        >
          {{ mlStatus.models_available ? 'Ready' : 'Not trained' }}
        </span>
      </span>
    </div>
    <div>MiroFish Forecast v0.3.0</div>
  </footer>
</template>

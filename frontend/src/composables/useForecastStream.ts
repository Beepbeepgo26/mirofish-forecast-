import { ref, shallowRef, onUnmounted } from 'vue'
import type { ForecastResult } from '@/types/forecast'
import type { SSEEvent } from '@/types/sse'

export type PipelineStatus = 'idle' | 'starting' | 'streaming' | 'complete' | 'error'

export interface StageInfo {
  name: string
  status: 'pending' | 'active' | 'completed'
  message: string
  progress?: number
  data?: Record<string, unknown>
  completedAt?: number
}

const STAGE_ORDER = [
  'parsing',
  'data_collection',
  'fast_inference',
  'scenario_building',
  'simulation',
  'synthesis',
]

const STAGE_LABELS: Record<string, string> = {
  parsing: 'Understanding your question',
  data_collection: 'Pulling market data',
  fast_inference: 'Running fast inference ⚡',
  scenario_building: 'Building scenarios',
  simulation: 'Running simulations',
  synthesis: 'Synthesizing forecast',
}

/**
 * Normalize a fast path result into ForecastResult shape.
 * This lets ForecastCard, ProbabilityChart, and ChatMessage
 * render fast path results without special-casing.
 */
function normalizeFastPathResult(raw: Record<string, unknown>): ForecastResult {
  const p5 = raw.predicted_p5 as number
  const p95 = raw.predicted_p95 as number
  const median = raw.predicted_median as number

  return {
    forecast_id: raw.forecast_id as string,
    instrument: raw.instrument as string,
    forecast_horizon_minutes: raw.forecast_horizon_minutes as number,
    current_price: raw.current_price as number,
    forecast_text: raw.forecast_text as string,
    distribution: {
      median,
      mean: median,
      std_dev: (p95 - p5) / 3.29,
      percentile_5: p5,
      percentile_25: (p5 + median) / 2,
      percentile_75: (median + p95) / 2,
      percentile_95: p95,
      skewness: 0,
      prob_up: raw.prob_up as number,
      prob_down: raw.prob_down as number,
      prob_flat: raw.prob_flat as number,
      scenario_probs: {},
    },
    total_simulations: 0,
    successful_simulations: 0,
    sim_preset: 'fast',
    institutional_reasoning: `${(raw.predicted_direction as string).toUpperCase()} (${((raw.direction_confidence as number) * 100).toFixed(0)}% confidence) — LightGBM fast path`,
    retail_reasoning: '',
    market_maker_reasoning: '',
    created_at: raw.created_at as string,
    pipeline_duration_seconds: raw.pipeline_duration_seconds as number,
    build_method: 'fast_path',
  }
}

export function useForecastStream() {
  const status = ref<PipelineStatus>('idle')
  const stages = ref<StageInfo[]>([])
  const result = shallowRef<ForecastResult | null>(null)
  const error = ref<string | null>(null)
  const forecastId = ref<string | null>(null)
  let eventSource: EventSource | null = null

  function _initStages() {
    stages.value = STAGE_ORDER.map(name => ({
      name,
      status: 'pending',
      message: STAGE_LABELS[name] || name,
    }))
  }

  function _updateStage(event: SSEEvent) {
    const idx = stages.value.findIndex(s => s.name === event.stage)
    if (idx === -1) return

    if (event.status === 'started') {
      stages.value[idx] = {
        ...stages.value[idx],
        status: 'active',
        message: event.message || STAGE_LABELS[event.stage] || '',
      }
    } else if (event.status === 'completed') {
      stages.value[idx] = {
        ...stages.value[idx],
        status: 'completed',
        data: event as unknown as Record<string, unknown>,
        completedAt: Date.now(),
      }
    } else if (event.status === 'progress') {
      stages.value[idx] = {
        ...stages.value[idx],
        status: 'active',
        message: event.message || '',
        progress: event.progress,
      }
    }
  }

  async function startForecast(
    query: string,
    simPreset: string = 'standard',
    simCount: number | null = null,
  ) {
    status.value = 'starting'
    result.value = null
    error.value = null
    forecastId.value = null
    _initStages()

    try {
      const body: Record<string, unknown> = { query, sim_preset: simPreset }
      if (simCount !== null) body.sim_count = simCount

      const response = await fetch('/api/forecast/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })

      if (!response.ok) {
        const err = await response.json()
        throw new Error(err.error || `HTTP ${response.status}`)
      }

      const { stream_url, forecast_id } = await response.json()
      forecastId.value = forecast_id
      status.value = 'streaming'

      eventSource = new EventSource(stream_url)

      eventSource.onmessage = (msg) => {
        try {
          const event: SSEEvent = JSON.parse(msg.data)
          _updateStage(event)

          if (event.stage === 'complete' && event.forecast) {
            const raw = event.forecast as Record<string, unknown>
            // Normalize fast path results into ForecastResult shape
            if (raw.build_method === 'fast_path') {
              result.value = normalizeFastPathResult(raw)
            } else {
              result.value = raw as unknown as ForecastResult
            }
            status.value = 'complete'
            eventSource?.close()
          } else if (event.stage === 'error') {
            error.value = event.message || event.error || 'Unknown error'
            status.value = 'error'
            eventSource?.close()
          }
        } catch (e) {
          console.error('SSE parse error:', e)
        }
      }

      eventSource.onerror = () => {
        if (status.value === 'streaming') {
          error.value = 'Connection to forecast stream lost'
          status.value = 'error'
        }
        eventSource?.close()
      }
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Failed to start forecast'
      status.value = 'error'
    }
  }

  async function cancel() {
    if (forecastId.value && (status.value === 'streaming' || status.value === 'starting')) {
      try {
        await fetch(`/api/forecast/cancel/${forecastId.value}`, { method: 'POST' })
      } catch (e) {
        console.error('Cancel request failed:', e)
      }
      eventSource?.close()
      status.value = 'idle'
      stages.value = []
      error.value = 'Forecast cancelled'
    }
  }

  function reset() {
    eventSource?.close()
    status.value = 'idle'
    stages.value = []
    result.value = null
    error.value = null
    forecastId.value = null
  }

  onUnmounted(() => {
    eventSource?.close()
  })

  return { status, stages, result, error, startForecast, cancel, reset }
}

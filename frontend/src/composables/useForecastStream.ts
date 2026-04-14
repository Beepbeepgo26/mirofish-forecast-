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
            result.value = event.forecast as unknown as ForecastResult
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

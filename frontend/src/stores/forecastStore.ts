import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { ForecastResult, SimPreset } from '@/types/forecast'

export interface ChatEntry {
  id: string
  type: 'query' | 'result' | 'error'
  query?: string
  simPreset?: SimPreset
  result?: ForecastResult
  errorMessage?: string
  timestamp: Date
}

export const useForecastStore = defineStore('forecast', () => {
  const history = ref<ChatEntry[]>([])
  const currentPreset = ref<SimPreset>('standard')
  const customSimCount = ref<number | null>(null)
  const showAdvanced = ref(false)

  // Phase 2: Active instrument for chart
  const activeInstrument = ref<string>('ES')
  const chartInterval = ref<string>('5m')

  function addQuery(query: string, preset: SimPreset): void {
    history.value.push({
      id: crypto.randomUUID(),
      type: 'query',
      query,
      simPreset: preset,
      timestamp: new Date(),
    })
  }

  function addResult(result: ForecastResult): void {
    history.value.push({
      id: crypto.randomUUID(),
      type: 'result',
      result,
      timestamp: new Date(),
    })
    // Update active instrument to match the forecast
    if (result.instrument) {
      activeInstrument.value = result.instrument
    }
  }

  function addError(message: string): void {
    history.value.push({
      id: crypto.randomUUID(),
      type: 'error',
      errorMessage: message,
      timestamp: new Date(),
    })
  }

  function clearHistory(): void {
    history.value = []
  }

  return {
    history,
    currentPreset,
    customSimCount,
    showAdvanced,
    activeInstrument,
    chartInterval,
    addQuery,
    addResult,
    addError,
    clearHistory,
  }
})

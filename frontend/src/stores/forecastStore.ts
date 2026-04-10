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

  function addQuery(query: string, preset: SimPreset) {
    history.value.push({
      id: crypto.randomUUID(),
      type: 'query',
      query,
      simPreset: preset,
      timestamp: new Date(),
    })
  }

  function addResult(result: ForecastResult) {
    history.value.push({
      id: crypto.randomUUID(),
      type: 'result',
      result,
      timestamp: new Date(),
    })
  }

  function addError(message: string) {
    history.value.push({
      id: crypto.randomUUID(),
      type: 'error',
      errorMessage: message,
      timestamp: new Date(),
    })
  }

  function clearHistory() {
    history.value = []
  }

  return {
    history,
    currentPreset,
    customSimCount,
    showAdvanced,
    addQuery,
    addResult,
    addError,
    clearHistory,
  }
})

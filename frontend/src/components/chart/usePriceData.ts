import { ref, watch, onMounted, onUnmounted, type Ref } from 'vue'
import type { OHLCVBar, OHLCVResponse } from '@/types/chart'

export function usePriceData(
  instrument: Ref<string> | string = 'ES',
  interval: Ref<string> | string = '5m',
) {
  const bars = ref<OHLCVBar[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)
  const lastPrice = ref<number | null>(null)
  let pollInterval: ReturnType<typeof setInterval> | null = null

  function getInstrument(): string {
    return typeof instrument === 'string' ? instrument : instrument.value
  }

  function getInterval(): string {
    return typeof interval === 'string' ? interval : interval.value
  }

  async function fetchBars(): Promise<void> {
    try {
      loading.value = true
      error.value = null
      const inst = getInstrument()
      const intv = getInterval()
      const res = await fetch(
        `/api/market/ohlcv?instrument=${inst}&interval=${intv}&count=200`,
      )
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data: OHLCVResponse = await res.json()
      bars.value = data.bars
      if (data.bars.length > 0) {
        lastPrice.value = data.bars[data.bars.length - 1].close
      }
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Failed to fetch price data'
    } finally {
      loading.value = false
    }
  }

  function startPolling(intervalMs = 30000): void {
    stopPolling()
    fetchBars()
    pollInterval = setInterval(fetchBars, intervalMs)
  }

  function stopPolling(): void {
    if (pollInterval) {
      clearInterval(pollInterval)
      pollInterval = null
    }
  }

  // Re-fetch when instrument or interval changes
  if (typeof instrument !== 'string') {
    watch(instrument, () => fetchBars())
  }
  if (typeof interval !== 'string') {
    watch(interval as Ref<string>, () => fetchBars())
  }

  onMounted(() => startPolling())
  onUnmounted(() => stopPolling())

  return { bars, loading, error, lastPrice, fetchBars }
}

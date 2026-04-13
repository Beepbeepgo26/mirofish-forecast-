<script setup lang="ts">
import { ref, watch, onMounted, onUnmounted, nextTick } from 'vue'
import {
  createChart,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
  ColorType,
} from 'lightweight-charts'
import type { OHLCVBar, ForecastOverlay } from '@/types/chart'
import { COLORS } from '@/config/theme'

const props = defineProps<{
  bars: OHLCVBar[]
  instrument: string
  overlay?: ForecastOverlay | null
}>()

const chartContainer = ref<HTMLElement | null>(null)
let chart: IChartApi | null = null
let candleSeries: ISeriesApi<'Candlestick'> | null = null
let volumeSeries: ISeriesApi<'Histogram'> | null = null

function initChart(): void {
  if (!chartContainer.value) return

  chart = createChart(chartContainer.value, {
    layout: {
      background: { type: ColorType.Solid, color: COLORS.base },
      textColor: COLORS.textSecondary,
      fontFamily: "'Inter', sans-serif",
      fontSize: 11,
    },
    grid: {
      vertLines: { color: COLORS.border },
      horzLines: { color: COLORS.border },
    },
    crosshair: {
      vertLine: { color: COLORS.accent, labelBackgroundColor: COLORS.accent },
      horzLine: { color: COLORS.accent, labelBackgroundColor: COLORS.accent },
    },
    rightPriceScale: {
      borderColor: COLORS.border,
      scaleMargins: { top: 0.1, bottom: 0.25 },
    },
    timeScale: {
      borderColor: COLORS.border,
      timeVisible: true,
      secondsVisible: false,
    },
    handleScroll: { vertTouchDrag: false },
  })

  candleSeries = chart.addCandlestickSeries({
    upColor: COLORS.bullish,
    downColor: COLORS.bearish,
    borderUpColor: COLORS.bullish,
    borderDownColor: COLORS.bearish,
    wickUpColor: COLORS.bullish,
    wickDownColor: COLORS.bearish,
  })

  volumeSeries = chart.addHistogramSeries({
    priceFormat: { type: 'volume' },
    priceScaleId: 'volume',
  })

  chart.priceScale('volume').applyOptions({
    scaleMargins: { top: 0.8, bottom: 0 },
  })

  updateData()
}

function updateData(): void {
  if (!candleSeries || !volumeSeries) return

  const candleData = props.bars.map((b) => ({
    time: b.time as UTCTimestamp,
    open: b.open,
    high: b.high,
    low: b.low,
    close: b.close,
  }))

  const volData = props.bars.map((b) => ({
    time: b.time as UTCTimestamp,
    value: b.volume,
    color:
      b.close >= b.open ? 'rgba(34, 197, 94, 0.3)' : 'rgba(239, 68, 68, 0.3)',
  }))

  candleSeries.setData(candleData)
  volumeSeries.setData(volData)
}

function updateOverlay(): void {
  if (!candleSeries || !props.overlay) return

  const o = props.overlay

  // P5–P95 band
  candleSeries.createPriceLine({
    price: o.p95,
    color: 'rgba(41, 98, 255, 0.3)',
    lineWidth: 1,
    lineStyle: 2,
    axisLabelVisible: true,
    title: 'P95',
  })
  candleSeries.createPriceLine({
    price: o.p5,
    color: 'rgba(41, 98, 255, 0.3)',
    lineWidth: 1,
    lineStyle: 2,
    axisLabelVisible: true,
    title: 'P5',
  })

  // P25–P75 band
  candleSeries.createPriceLine({
    price: o.p75,
    color: 'rgba(41, 98, 255, 0.5)',
    lineWidth: 1,
    lineStyle: 2,
    axisLabelVisible: false,
    title: '',
  })
  candleSeries.createPriceLine({
    price: o.p25,
    color: 'rgba(41, 98, 255, 0.5)',
    lineWidth: 1,
    lineStyle: 2,
    axisLabelVisible: false,
    title: '',
  })

  // Median line (solid)
  candleSeries.createPriceLine({
    price: o.median,
    color: COLORS.accent,
    lineWidth: 2,
    lineStyle: 0,
    axisLabelVisible: true,
    title: 'Forecast',
  })

  // Current price entry marker (dotted)
  candleSeries.createPriceLine({
    price: o.currentPrice,
    color: COLORS.warning,
    lineWidth: 1,
    lineStyle: 1,
    axisLabelVisible: true,
    title: 'Entry',
  })
}

function handleResize(): void {
  if (chart && chartContainer.value) {
    chart.applyOptions({
      width: chartContainer.value.clientWidth,
      height: chartContainer.value.clientHeight,
    })
  }
}

watch(
  () => props.bars,
  () => {
    updateData()
    chart?.timeScale().fitContent()
  },
  { deep: true },
)

watch(
  () => props.overlay,
  () => {
    nextTick(() => updateOverlay())
  },
)

onMounted(() => {
  initChart()
  window.addEventListener('resize', handleResize)

  // Use ResizeObserver for reliable pane resize handling
  if (chartContainer.value) {
    const ro = new ResizeObserver(() => handleResize())
    ro.observe(chartContainer.value)
  }
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
  chart?.remove()
  chart = null
})
</script>

<template>
  <div class="relative w-full h-full bg-[#0a0a0f]">
    <div ref="chartContainer" class="w-full h-full" />
    <!-- Instrument badge -->
    <div class="absolute top-3 left-3 flex items-center gap-2 pointer-events-none">
      <span
        class="text-sm font-semibold text-[#e5e7eb] bg-[#111118]/80 px-2 py-1 rounded"
      >
        {{ instrument }}
      </span>
      <span
        class="text-xs font-mono text-[#6b7280] bg-[#111118]/80 px-2 py-0.5 rounded"
      >
        5min
      </span>
    </div>
    <!-- Loading state -->
    <div
      v-if="bars.length === 0"
      class="absolute inset-0 flex items-center justify-center text-[#6b7280] text-sm"
    >
      Loading chart…
    </div>
  </div>
</template>

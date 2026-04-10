<script setup lang="ts">
import { computed } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, MarkLineComponent, MarkAreaComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { ProbabilityDistribution } from '@/types/forecast'

use([LineChart, GridComponent, TooltipComponent, MarkLineComponent, MarkAreaComponent, CanvasRenderer])

const props = defineProps<{
  distribution: ProbabilityDistribution
  currentPrice: number
}>()

function normalPDF(x: number, mean: number, stdDev: number): number {
  if (stdDev === 0) return x === mean ? 1 : 0
  return (1 / (stdDev * Math.sqrt(2 * Math.PI))) * Math.exp(-0.5 * ((x - mean) / stdDev) ** 2)
}

const chartOption = computed(() => {
  const { mean, std_dev, percentile_5, percentile_95 } = props.distribution
  const sd = Math.max(std_dev, 1)
  const lo = Math.min(percentile_5, mean - 3 * sd)
  const hi = Math.max(percentile_95, mean + 3 * sd)
  const step = (hi - lo) / 120

  const xData: number[] = []
  const yData: number[] = []
  for (let x = lo; x <= hi; x += step) {
    xData.push(Math.round(x * 100) / 100)
    yData.push(normalPDF(x, mean, sd))
  }

  return {
    backgroundColor: 'transparent',
    grid: { left: 50, right: 20, top: 20, bottom: 35 },
    tooltip: {
      trigger: 'axis' as const,
      backgroundColor: '#111118',
      borderColor: '#2e2e3e',
      textStyle: { color: '#e5e7eb', fontSize: 11, fontFamily: 'JetBrains Mono' },
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      formatter: (params: any) => {
        const p = params[0]
        return `Price: ${Number(p.axisValue).toFixed(2)}`
      },
    },
    xAxis: {
      type: 'category' as const,
      data: xData.map(v => v.toFixed(1)),
      axisLabel: { color: '#6b7280', fontSize: 10, fontFamily: 'JetBrains Mono', interval: 'auto' },
      axisLine: { lineStyle: { color: '#2e2e3e' } },
      axisTick: { show: false },
    },
    yAxis: {
      type: 'value' as const,
      show: false,
    },
    series: [
      {
        type: 'line' as const,
        data: yData,
        smooth: true,
        showSymbol: false,
        lineStyle: { color: '#2962FF', width: 2 },
        areaStyle: {
          color: {
            type: 'linear' as const,
            x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: 'rgba(41,98,255,0.3)' },
              { offset: 1, color: 'rgba(41,98,255,0.02)' },
            ],
          },
        },
        markLine: {
          silent: true,
          symbol: 'none',
          data: [
            {
              xAxis: xData.findIndex(v => v >= props.currentPrice).toString(),
              lineStyle: { color: '#f59e0b', type: 'dashed' as const, width: 1 },
              label: { show: true, formatter: 'Current', color: '#f59e0b', fontSize: 10 },
            },
            {
              xAxis: xData.findIndex(v => v >= props.distribution.median).toString(),
              lineStyle: { color: '#22c55e', type: 'solid' as const, width: 1 },
              label: { show: true, formatter: 'Median', color: '#22c55e', fontSize: 10 },
            },
          ],
        },
      },
    ],
  }
})
</script>

<template>
  <VChart :option="chartOption" style="height: 180px; width: 100%;" autoresize />
</template>

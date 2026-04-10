<script setup lang="ts">
import type { MarketContextSummary } from '@/types/market'

defineProps<{ context: MarketContextSummary }>()

function fmt(val: number | null, decimals = 2): string {
  if (val == null) return '—'
  return val.toFixed(decimals)
}
</script>

<template>
  <div class="flex items-center gap-4 text-xs font-mono text-[#9ca3af]">
    <span>ES <span class="text-[#e5e7eb]">{{ fmt(context.es_price) }}</span></span>
    <span>VIX <span class="text-[#e5e7eb]">{{ fmt(context.vix_spot, 1) }}</span></span>
    <span>F&amp;G <span class="text-[#e5e7eb]">{{ fmt(context.fear_greed, 0) }}</span></span>
    <span>10Y <span class="text-[#e5e7eb]">{{ fmt(context.ten_year) }}%</span></span>
    <span>DXY <span class="text-[#e5e7eb]">{{ fmt(context.dxy, 1) }}</span></span>
  </div>
</template>

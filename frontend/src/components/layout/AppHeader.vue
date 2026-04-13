<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import SessionStatus from './SessionStatus.vue'

interface MarketTick {
  symbol: string
  price: number | null
  change?: number
}

const ticks = ref<MarketTick[]>([
  { symbol: 'ES', price: null },
  { symbol: 'NQ', price: null },
  { symbol: 'VIX', price: null },
  { symbol: 'DXY', price: null },
  { symbol: 'GC', price: null },
  { symbol: 'CL', price: null },
])

let interval: ReturnType<typeof setInterval> | null = null

async function fetchTicks(): Promise<void> {
  try {
    const res = await fetch('/api/market/snapshot')
    if (!res.ok) return
    const data = await res.json()
    const priceMap: Record<string, number | null> = {
      ES: data.cross_asset?.es_price ?? null,
      NQ: data.cross_asset?.nq_price ?? null,
      VIX: data.vix?.spot ?? null,
      DXY: data.cross_asset?.dxy_price ?? null,
      GC: data.cross_asset?.gld_price ?? null,
      CL: data.cross_asset?.crude_price ?? null,
    }
    ticks.value = ticks.value.map((t) => ({
      ...t,
      price: priceMap[t.symbol] ?? t.price,
    }))
  } catch {
    // Silent fail
  }
}

onMounted(() => {
  fetchTicks()
  interval = setInterval(fetchTicks, 30000)
})

onUnmounted(() => {
  if (interval) clearInterval(interval)
})

function fmt(val: number | null, decimals = 2): string {
  if (val == null) return '—'
  return val.toFixed(decimals)
}
</script>

<template>
  <header
    class="flex items-center justify-between px-4 py-2 border-b border-[#2e2e3e] bg-[#111118] shrink-0"
  >
    <!-- Brand -->
    <div class="flex items-center gap-2 shrink-0">
      <div class="text-base font-semibold tracking-tight text-[#e5e7eb]">
        MiroFish <span class="text-[#2962FF]">Forecast</span>
      </div>
    </div>

    <!-- Market ticker -->
    <div class="hidden sm:flex items-center gap-4 text-xs font-mono">
      <div
        v-for="tick in ticks"
        :key="tick.symbol"
        class="flex items-center gap-1.5 text-[#9ca3af]"
      >
        <span class="text-[10px] text-[#6b7280]">{{ tick.symbol }}</span>
        <span class="text-[#e5e7eb]">{{
          fmt(
            tick.price,
            tick.symbol === 'VIX' || tick.symbol === 'DXY' ? 1 : 2,
          )
        }}</span>
      </div>
    </div>

    <!-- Session status -->
    <div class="flex items-center gap-3 shrink-0">
      <SessionStatus />
      <span class="text-xs font-mono text-[#6b7280]">v0.3.0</span>
    </div>
  </header>
</template>

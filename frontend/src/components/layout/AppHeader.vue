<script setup lang="ts">
import SessionStatus from './SessionStatus.vue'
</script>

<template>
  <header class="flex items-center justify-between px-6 py-3 border-b border-[#2e2e3e] bg-[#111118]">
    <div class="flex items-center gap-3">
      <div class="text-lg font-semibold tracking-tight text-[#e5e7eb]">
        MiroFish <span class="text-[#2962FF]">Forecast</span>
      </div>
      <div class="text-xs text-[#6b7280] font-mono">Futures</div>
    </div>
    <div class="flex items-center gap-4">
      <SessionStatus />
      <span class="text-xs font-mono text-[#6b7280]">v0.2.0</span>
    </div>
  </header>
</template>

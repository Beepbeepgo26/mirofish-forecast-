<script setup lang="ts">
import { ref } from 'vue'

defineProps<{
  institutional: string
  retail: string
  marketMaker: string
}>()

const expanded = ref<string | null>(null)

function toggle(agent: string) {
  expanded.value = expanded.value === agent ? null : agent
}

const agents = [
  { key: 'institutional', label: 'Institutional', icon: '🏛️' },
  { key: 'retail', label: 'Retail', icon: '🧑‍💻' },
  { key: 'marketMaker', label: 'Market Maker', icon: '🏦' },
] as const
</script>

<template>
  <div class="space-y-2">
    <div
      v-for="agent in agents"
      :key="agent.key"
      class="bg-[#0a0a0f] rounded-lg overflow-hidden"
    >
      <button
        class="w-full flex items-center gap-3 px-4 py-2.5 text-sm text-[#e5e7eb] hover:bg-[#1a1a24] transition-colors"
        @click="toggle(agent.key)"
      >
        <span>{{ agent.icon }}</span>
        <span class="font-medium">{{ agent.label }}</span>
        <span class="flex-1" />
        <span class="text-xs text-[#6b7280]">
          {{ expanded === agent.key ? '▾' : '▸' }}
        </span>
      </button>
      <div
        v-if="expanded === agent.key"
        class="px-4 pb-3 text-xs text-[#9ca3af] leading-relaxed"
      >
        {{ agent.key === 'institutional' ? institutional : agent.key === 'retail' ? retail : marketMaker }}
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useForecastStore } from '@/stores/forecastStore'
import { SIM_PRESETS, type SimPreset } from '@/types/forecast'

const props = defineProps<{ disabled: boolean; isStreaming: boolean }>()
const emit = defineEmits<{ submit: [query: string]; cancel: [] }>()
const store = useForecastStore()
const query = ref('')

function handleSubmit() {
  const trimmed = query.value.trim()
  if (!trimmed || props.disabled) return
  emit('submit', trimmed)
  query.value = ''
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    handleSubmit()
  }
}

const presets: SimPreset[] = ['simple', 'quick', 'standard', 'deep']
</script>

<template>
  <div class="border-t border-[#2e2e3e] bg-[#111118] px-4 py-3">
    <!-- Simulation presets -->
    <div class="flex items-center gap-2 mb-2">
      <span class="text-xs text-[#6b7280]">Sims:</span>
      <button
        v-for="p in presets"
        :key="p"
        :class="[
          'px-2.5 py-1 rounded text-xs font-medium transition-colors',
          store.currentPreset === p
            ? 'bg-[#2962FF] text-white'
            : 'bg-[#1a1a24] text-[#9ca3af] hover:bg-[#2e2e3e]',
        ]"
        @click="store.currentPreset = p; store.customSimCount = null"
      >
        {{ SIM_PRESETS[p].label }}
        <span class="text-[10px] opacity-70 ml-1">{{ SIM_PRESETS[p].time }}</span>
      </button>

      <button
        class="text-xs text-[#6b7280] hover:text-[#9ca3af] ml-1"
        @click="store.showAdvanced = !store.showAdvanced"
      >
        {{ store.showAdvanced ? 'Simple' : 'Advanced' }}
      </button>
    </div>

    <!-- Advanced slider -->
    <div v-if="store.showAdvanced" class="flex items-center gap-3 mb-2">
      <input
        type="range"
        :min="100"
        :max="500"
        :step="50"
        :value="store.customSimCount ?? SIM_PRESETS[store.currentPreset].sims"
        class="flex-1 accent-[#2962FF] h-1"
        @input="(e) => { store.customSimCount = Number((e.target as HTMLInputElement).value) }"
      />
      <span class="text-xs font-mono text-[#9ca3af] w-12 text-right">
        {{ store.customSimCount ?? SIM_PRESETS[store.currentPreset].sims }}
      </span>
    </div>

    <!-- Input row -->
    <div class="flex items-end gap-2">
      <textarea
        v-model="query"
        :disabled="disabled"
        rows="1"
        placeholder="Ask about ES, NQ, CL, or GC futures..."
        class="flex-1 bg-[#1a1a24] border border-[#2e2e3e] rounded-lg px-4 py-2.5 text-sm text-[#e5e7eb] placeholder-[#6b7280] resize-none focus:outline-none focus:border-[#2962FF] transition-colors disabled:opacity-50"
        @keydown="handleKeydown"
      />
      <button
        v-if="!props.isStreaming"
        :disabled="disabled || !query.trim()"
        class="px-4 py-2.5 bg-[#2962FF] text-white text-sm font-medium rounded-lg hover:bg-[#1d4ed8] disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        @click="handleSubmit"
      >
        Send
      </button>
      <button
        v-else
        class="px-4 py-2.5 bg-[#ef4444] text-white text-sm font-medium rounded-lg hover:bg-[#dc2626] transition-colors flex items-center gap-1.5"
        @click="emit('cancel')"
      >
        <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5">
          <rect x="6" y="6" width="12" height="12" rx="1" />
        </svg>
        Stop
      </button>
    </div>
  </div>
</template>

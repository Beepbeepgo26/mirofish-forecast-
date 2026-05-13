<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'
import type { BrooksAnalog } from '@/types/forecast'

const props = defineProps<{
  analog: BrooksAnalog
  signedUrl: string
}>()

const emit = defineEmits<{
  close: []
}>()

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') {
    emit('close')
  }
}

function handleBackdropClick(e: MouseEvent) {
  if ((e.target as HTMLElement).classList.contains('lightbox-backdrop')) {
    emit('close')
  }
}

onMounted(() => {
  document.addEventListener('keydown', handleKeydown)
})

onUnmounted(() => {
  document.removeEventListener('keydown', handleKeydown)
})
</script>

<template>
  <Teleport to="body">
    <div
      class="lightbox-backdrop fixed inset-0 z-50 flex items-center justify-center
             bg-black/80 backdrop-blur-sm"
      @click="handleBackdropClick"
    >
      <div
        class="relative bg-[#111118] border border-[#2e2e3e] rounded-xl
               max-w-4xl max-h-[90vh] w-[95vw] overflow-hidden flex flex-col"
      >
        <!-- Header -->
        <div class="flex items-center justify-between px-5 py-3 border-b border-[#2e2e3e]">
          <div class="flex items-center gap-3">
            <span class="text-sm font-medium text-[#e5e7eb]">
              {{ analog.pattern_type.replaceAll('_', ' ') }}
            </span>
            <span class="text-xs text-[#6b7280]">
              Page {{ analog.page_number }}
            </span>
          </div>
          <button
            class="text-[#6b7280] hover:text-[#e5e7eb] transition-colors text-lg leading-none"
            @click="$emit('close')"
          >
            ✕
          </button>
        </div>

        <!-- Chart image -->
        <div class="flex-1 overflow-auto p-4 flex items-center justify-center bg-[#0a0a0f]">
          <img
            :src="signedUrl"
            :alt="`Brooks chart page ${analog.page_number}`"
            class="max-w-full max-h-[50vh] object-contain rounded"
          />
        </div>

        <!-- Metadata -->
        <div class="px-5 py-4 border-t border-[#2e2e3e] space-y-3">
          <!-- Badge row -->
          <div class="flex items-center gap-2 flex-wrap">
            <span
              :class="[
                'text-xs font-medium px-2 py-0.5 rounded',
                analog.direction === 'long'
                  ? 'bg-[#22c55e]/15 text-[#22c55e]'
                  : analog.direction === 'short'
                    ? 'bg-[#ef4444]/15 text-[#ef4444]'
                    : 'bg-[#2e2e3e] text-[#9ca3af]',
              ]"
            >
              {{ analog.direction.toUpperCase() }}
            </span>
            <span
              :class="[
                'text-xs px-2 py-0.5 rounded',
                analog.outcome === 'success'
                  ? 'bg-[#22c55e]/10 text-[#22c55e]'
                  : analog.outcome === 'failure'
                    ? 'bg-[#ef4444]/10 text-[#ef4444]'
                    : analog.outcome === 'trap'
                      ? 'bg-[#f59e0b]/10 text-[#f59e0b]'
                      : 'bg-[#2e2e3e] text-[#6b7280]',
              ]"
            >
              {{ analog.outcome }}
            </span>
            <span class="text-xs px-2 py-0.5 rounded bg-[#2e2e3e] text-[#9ca3af]">
              {{ analog.day_type }}
            </span>
            <span class="text-xs px-2 py-0.5 rounded bg-[#2e2e3e] text-[#9ca3af]">
              {{ analog.always_in_direction }}
            </span>
            <span class="text-xs font-mono text-[#9ca3af] ml-auto">
              Similarity: {{ (analog.similarity_score * 100).toFixed(1) }}%
            </span>
          </div>

          <!-- Brooks concepts -->
          <div v-if="analog.brooks_concepts.length" class="flex items-center gap-1.5 flex-wrap">
            <span class="text-xs text-[#6b7280]">Concepts:</span>
            <span
              v-for="concept in analog.brooks_concepts"
              :key="concept"
              class="text-[10px] px-1.5 py-0.5 rounded bg-[#2962FF]/10 text-[#2962FF]"
            >
              {{ concept }}
            </span>
          </div>

          <!-- Analysis summary -->
          <p class="text-xs text-[#9ca3af] leading-relaxed">
            {{ analog.analysis_summary }}
          </p>
        </div>
      </div>
    </div>
  </Teleport>
</template>

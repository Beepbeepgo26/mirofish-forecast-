<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import ChatInput from './ChatInput.vue'
import ChatMessage from './ChatMessage.vue'
import StreamingIndicator from './StreamingIndicator.vue'
import { useForecastStream } from '@/composables/useForecastStream'
import { useAutoScroll } from '@/composables/useAutoScroll'
import { useForecastStore } from '@/stores/forecastStore'

const store = useForecastStore()
const { status, stages, result, error, startForecast, cancel } = useForecastStream()
const scrollContainer = ref<HTMLElement | null>(null)
const scrollTrigger = computed(() => [store.history.length, stages.value])
const { onScroll, scrollToBottom } = useAutoScroll(scrollContainer, scrollTrigger)

async function handleSubmit(query: string) {
  store.addQuery(query, store.currentPreset)
  await startForecast(query, store.currentPreset, store.customSimCount)
}

watch(result, (val) => {
  if (val) {
    store.addResult(val)
    scrollToBottom()
  }
})

watch(error, (val) => {
  if (val) {
    store.addError(val)
    scrollToBottom()
  }
})
</script>

<template>
  <div class="flex flex-col h-full">
    <!-- Message area -->
    <div
      ref="scrollContainer"
      class="flex-1 overflow-y-auto px-4 py-6 space-y-4"
      @scroll="onScroll"
    >
      <!-- Empty state -->
      <div
        v-if="store.history.length === 0 && status === 'idle'"
        class="flex flex-col items-center justify-center h-full text-center"
      >
        <div class="text-2xl font-semibold text-[#e5e7eb] mb-2">
          MiroFish <span class="text-[#2962FF]">Forecast</span>
        </div>
        <p class="text-[#6b7280] text-sm max-w-md">
          Ask a question about ES, NQ, CL, or GC futures. Try "Where will ES be in 2 hours?" or "NQ forecast for Monday"
        </p>
      </div>

      <!-- Chat history -->
      <ChatMessage
        v-for="entry in store.history"
        :key="entry.id"
        :entry="entry"
      />

      <!-- Active streaming indicator -->
      <StreamingIndicator
        v-if="status === 'streaming'"
        :stages="stages"
      />
    </div>

    <!-- Input area -->
    <ChatInput
      :disabled="status === 'streaming' || status === 'starting'"
      :is-streaming="status === 'streaming'"
      @submit="handleSubmit"
      @cancel="cancel"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import type { BrooksAnalog } from '@/types/forecast'
import { useBrooksChart } from '@/composables/useBrooksChart'

const props = defineProps<{
  analog: BrooksAnalog
}>()

const emit = defineEmits<{
  click: [analog: BrooksAnalog, signedUrl: string]
}>()

const { getSignedUrl } = useBrooksChart()
const thumbnailUrl = ref<string | null>(null)

onMounted(async () => {
  thumbnailUrl.value = await getSignedUrl(props.analog.page_number)
})

function handleClick() {
  if (thumbnailUrl.value) {
    emit('click', props.analog, thumbnailUrl.value)
  }
}
</script>

<template>
  <button
    class="flex flex-col w-[180px] shrink-0 bg-[#111118] border border-[#2e2e3e]
           rounded-lg overflow-hidden hover:border-[#2962FF] transition-colors
           cursor-pointer text-left"
    @click="handleClick"
  >
    <!-- Thumbnail -->
    <div class="w-full h-[100px] bg-[#0a0a0f] flex items-center justify-center overflow-hidden">
      <img
        v-if="thumbnailUrl"
        :src="thumbnailUrl"
        :alt="`Brooks chart page ${analog.page_number}`"
        class="w-full h-full object-cover"
        loading="lazy"
      />
      <span v-else class="text-xs text-[#6b7280]">Loading...</span>
    </div>

    <!-- Card content -->
    <div class="p-2 space-y-1.5">
      <!-- Pattern type -->
      <div class="text-xs font-medium text-[#e5e7eb] truncate">
        {{ analog.pattern_type.replaceAll('_', ' ') }}
      </div>

      <!-- Badges row -->
      <div class="flex items-center gap-1 flex-wrap">
        <!-- Direction -->
        <span
          :class="[
            'text-[10px] font-medium px-1.5 py-0.5 rounded',
            analog.direction === 'long'
              ? 'bg-[#22c55e]/15 text-[#22c55e]'
              : analog.direction === 'short'
                ? 'bg-[#ef4444]/15 text-[#ef4444]'
                : 'bg-[#2e2e3e] text-[#9ca3af]',
          ]"
        >
          {{ analog.direction.toUpperCase() }}
        </span>

        <!-- Outcome -->
        <span
          :class="[
            'text-[10px] px-1.5 py-0.5 rounded',
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

        <!-- Similarity -->
        <span class="text-[10px] font-mono text-[#9ca3af] ml-auto">
          {{ (analog.similarity_score * 100).toFixed(0) }}%
        </span>
      </div>
    </div>
  </button>
</template>

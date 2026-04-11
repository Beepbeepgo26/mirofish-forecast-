<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'

interface SessionInfo {
  session_type: string
  is_rth_open: boolean
  is_tradeable: boolean
  current_time_et: string
  day_of_week: string
  session_label: string
  minutes_to_rth_close: number | null
  next_rth_open: string | null
}

const session = ref<SessionInfo | null>(null)
let interval: ReturnType<typeof setInterval> | null = null

async function fetchSession() {
  try {
    const res = await fetch('/api/forecast/session-info')
    if (res.ok) {
      session.value = await res.json()
    }
  } catch (e) {
    console.error('Failed to fetch session info:', e)
  }
}

onMounted(() => {
  fetchSession()
  interval = setInterval(fetchSession, 60000)
})

onUnmounted(() => {
  if (interval) clearInterval(interval)
})

function statusColor(info: SessionInfo): string {
  if (info.is_rth_open) return '#22c55e'
  if (info.is_tradeable) return '#f59e0b'
  return '#ef4444'
}

function statusDot(info: SessionInfo): string {
  if (info.is_rth_open) return '●'
  if (info.is_tradeable) return '◐'
  return '○'
}
</script>

<template>
  <div v-if="session" class="flex items-center gap-2 text-xs">
    <span
      class="font-mono text-sm"
      :style="{ color: statusColor(session) }"
    >
      {{ statusDot(session) }}
    </span>
    <span class="text-[#9ca3af]">
      {{ session.session_label }}
    </span>
    <span class="text-[#6b7280] font-mono">
      {{ session.current_time_et }}
    </span>
    <span
      v-if="session.is_rth_open && session.minutes_to_rth_close"
      class="text-[#6b7280]"
    >
      ({{ session.minutes_to_rth_close }}m to close)
    </span>
    <span
      v-else-if="!session.is_rth_open && session.next_rth_open"
      class="text-[#6b7280]"
    >
      Next: {{ session.next_rth_open }}
    </span>
  </div>
</template>

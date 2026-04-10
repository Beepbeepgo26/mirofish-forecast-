<script setup lang="ts">
import AppHeader from '@/components/layout/AppHeader.vue'
import ChatContainer from '@/components/chat/ChatContainer.vue'
</script>

<template>
  <div class="flex flex-col h-screen bg-[#0a0a0f]">
    <AppHeader />
    <ChatContainer class="flex-1 overflow-hidden" />
  </div>
</template>

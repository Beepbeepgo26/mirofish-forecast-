<script setup lang="ts">
import AppHeader from '@/components/layout/AppHeader.vue'
import DashboardLayout from '@/components/layout/DashboardLayout.vue'
</script>

<template>
  <div class="flex flex-col h-screen bg-[#0a0a0f]">
    <AppHeader />
    <DashboardLayout class="flex-1 overflow-hidden" />
  </div>
</template>

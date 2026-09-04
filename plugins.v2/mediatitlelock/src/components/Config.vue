<script setup>
import Page from './Page.vue'

defineProps({
  api: Object,
  pluginId: String,
})

const emit = defineEmits(['close'])
</script>

<template>
  <Page :api="api" :plugin-id="pluginId" @close="emit('close')" />
</template>

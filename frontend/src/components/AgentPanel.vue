<script setup>
import AgentPanelFeature from '../features/agent/components/AgentPanelFeature.vue';

defineProps({
  alertId: String
});

defineEmits(['close']);
</script>

<template>
  <AgentPanelFeature v-bind="$props" @close="$emit('close')" />
</template>

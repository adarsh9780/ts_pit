<script setup>
import AlertDetailView from '../features/alerts/views/AlertDetailView.vue';

defineProps({
  alertId: {
    type: [String, Number],
    required: true
  }
});

defineEmits(['toggle-agent']);
</script>

<template>
  <AlertDetailView v-bind="$props" @toggle-agent="$emit('toggle-agent')" />
</template>

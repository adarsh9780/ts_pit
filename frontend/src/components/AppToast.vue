<script setup>
import { useToast } from '../composables/useToast.js';

const { toasts, dismiss } = useToast();
</script>

<template>
  <div class="toast-host" aria-live="polite" aria-atomic="true">
    <transition-group name="toast-fade" tag="div" class="toast-stack">
      <div
        v-for="toast in toasts"
        :key="toast.id"
        class="toast-item"
        :class="`lvl-${toast.level}`"
      >
        <span class="toast-text">{{ toast.message }}</span>
        <button class="toast-close" @click="dismiss(toast.id)" title="Dismiss">×</button>
      </div>
    </transition-group>
  </div>
</template>

<style scoped>
.toast-host {
  position: fixed;
  left: 16px;
  bottom: 16px;
  z-index: 9999;
  pointer-events: none;
}

.toast-stack {
  display: flex;
  flex-direction: column;
  gap: 8px;
  align-items: flex-start;
}

.toast-item {
  pointer-events: auto;
  min-width: 200px;
  max-width: 360px;
  border-radius: 10px;
  border: 1px solid #d5dde9;
  background: #ffffff;
  color: #0f172a;
  box-shadow: 0 10px 24px rgba(15, 23, 42, 0.12);
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
}

.toast-item.lvl-success {
  border-color: #b7e4c7;
  background: #f0fdf4;
}

.toast-item.lvl-error {
  border-color: #fecaca;
  background: #fef2f2;
}

.toast-text {
  font-size: 12px;
  line-height: 1.35;
  flex: 1;
}

.toast-close {
  border: none;
  background: transparent;
  color: #64748b;
  font-size: 14px;
  line-height: 1;
  cursor: pointer;
}

.toast-fade-enter-active,
.toast-fade-leave-active {
  transition: all 0.18s ease;
}

.toast-fade-enter-from,
.toast-fade-leave-to {
  opacity: 0;
  transform: translateY(6px) scale(0.98);
}
</style>

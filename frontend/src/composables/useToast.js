import { computed, ref } from 'vue';

const toasts = ref([]);
let toastSeq = 0;

export function useToast() {
  const notify = (message, options = {}) => {
    const text = String(message || '').trim();
    if (!text) return null;

    const id = `toast-${Date.now()}-${toastSeq++}`;
    const duration = Number.isFinite(options.duration) ? Math.max(1200, options.duration) : 2200;
    const level = String(options.level || 'info');

    const toast = { id, message: text, level };
    toasts.value.push(toast);

    window.setTimeout(() => {
      const idx = toasts.value.findIndex((item) => item.id === id);
      if (idx >= 0) toasts.value.splice(idx, 1);
    }, duration);

    return id;
  };

  const dismiss = (id) => {
    const idx = toasts.value.findIndex((item) => item.id === id);
    if (idx >= 0) toasts.value.splice(idx, 1);
  };

  return {
    toasts: computed(() => toasts.value),
    notify,
    dismiss,
  };
}

<script setup>
defineProps({
    isOpen: Boolean,
    title: {
        type: String,
        default: 'Confirm Action'
    },
    message: {
        type: String,
        default: 'Are you sure you want to proceed?'
    },
    confirmText: {
        type: String,
        default: 'Confirm'
    },
    cancelText: {
        type: String,
        default: 'Cancel'
    },
    showButtons: {
        type: Boolean,
        default: true
    }
});

const emit = defineEmits(['confirm', 'cancel']);
</script>

<template>
    <Transition name="fade">
        <div v-if="isOpen" class="modal-overlay">
            <div class="modal-container">
                <div class="modal-header">
                    <h3>{{ title }}</h3>
                </div>
                <div class="modal-body">
                    <p>{{ message }}</p>
                </div>
                <div class="modal-footer" v-if="showButtons">
                    <button class="btn btn-cancel" @click="$emit('cancel')">{{ cancelText }}</button>
                    <button class="btn btn-confirm" @click="$emit('confirm')">{{ confirmText }}</button>
                </div>
            </div>
        </div>
    </Transition>
</template>

<style scoped>
.modal-overlay {
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background-color: rgba(0, 0, 0, 0.5);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 1000;
    backdrop-filter: blur(2px);
}

.modal-container {
    background: white;
    border-radius: 8px;
    box-shadow: 0 10px 25px rgba(0, 0, 0, 0.1);
    width: 90%;
    max-width: 400px;
    overflow: hidden;
    animation: slide-up 0.2s ease-out;
}

.modal-header {
    padding: 16px 20px;
    border-bottom: 1px solid #e2e8f0;
}

.modal-header h3 {
    margin: 0;
    font-size: 1.1rem;
    color: #1e293b;
    font-weight: 600;
}

.modal-body {
    padding: 20px;
    color: #475569;
    font-size: 0.95rem;
    line-height: 1.5;
}

.modal-footer {
    padding: 16px 20px;
    background-color: #f8fafc;
    border-top: 1px solid #e2e8f0;
    display: flex;
    justify-content: flex-end;
    gap: 12px;
}

.btn {
    padding: 8px 16px;
    border-radius: 6px;
    font-size: 0.875rem;
    font-weight: 500;
    cursor: pointer;
    transition: all 0.2s;
    border: 1px solid transparent;
}

.btn-cancel {
    background-color: white;
    border-color: #cbd5e1;
    color: #64748b;
}

.btn-cancel:hover {
    border-color: #94a3b8;
    color: #475569;
}

.btn-confirm {
    background-color: #6366f1;
    color: white;
}

.btn-confirm:hover {
    background-color: #4f46e5;
}

/* Transitions */
.fade-enter-active,
.fade-leave-active {
    transition: opacity 0.2s;
}

.fade-enter-from,
.fade-leave-to {
    opacity: 0;
}

@keyframes slide-up {
    from {
        transform: translateY(10px);
        opacity: 0;
    }
    to {
        transform: translateY(0);
        opacity: 1;
    }
}
</style>

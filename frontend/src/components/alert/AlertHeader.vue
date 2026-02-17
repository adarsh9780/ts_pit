<script setup>

const props = defineProps({
  alertData: { type: Object, required: true },
  alertId: { type: [String, Number], required: true },
  newsCount: { type: Number, default: 0 },
  validStatuses: { type: Array, default: () => ['NEEDS_REVIEW', 'ESCALATE_L2', 'DISMISS'] }
});

const emit = defineEmits(['update-status', 'toggle-agent']);

const getStatusClass = (status) => {
    const classes = {
        'NEEDS_REVIEW': 'status-needs-review',
        'ESCALATE_L2': 'status-escalate-l2',
        'DISMISS': 'status-dismiss',
        'Pending': 'status-needs-review',
        'Approved': 'status-escalate-l2',
        'Rejected': 'status-dismiss'
    };
    return classes[status] || '';
};

const updateStatus = (status) => {
    emit('update-status', status);
};
</script>

<template>
    <header class="header">
        <div class="header-container">
            <!-- Row 1: Identity & Actions -->
            <div class="header-top">
                <div class="identity-section">
                    <h1>{{ alertData.ticker }}</h1>
                    <span class="subtitle">{{ alertData.instrument_name }}</span>
                </div>
                <div class="actions-section">
                    <button class="action-btn ask-ai-btn" @click="$emit('toggle-agent')" title="Open AI Assistant">
                        Ask AI
                    </button>
                    <button
                        v-if="validStatuses.includes('ESCALATE_L2')"
                        class="action-btn escalate-btn"
                        @click="updateStatus('ESCALATE_L2')"
                        :disabled="alertData.status === 'ESCALATE_L2'"
                    >
                        Escalate L2
                    </button>
                    <button
                        v-if="validStatuses.includes('DISMISS')"
                        class="action-btn dismiss-btn"
                        @click="updateStatus('DISMISS')"
                        :disabled="alertData.status === 'DISMISS'"
                    >
                        Dismiss
                    </button>
                    <button
                        v-if="validStatuses.includes('NEEDS_REVIEW')"
                        class="action-btn review-btn"
                        @click="updateStatus('NEEDS_REVIEW')"
                        :disabled="alertData.status === 'NEEDS_REVIEW'"
                    >
                        Needs Review
                    </button>
                </div>
            </div>

            <!-- Row 2: Context Badges -->
            <div class="header-context">
                <div class="badge-group">
                    <span class="label">ID</span>
                    <span class="value">{{ alertId }}</span>
                </div>
                <div class="badge-group">
                    <span class="label">ISIN</span>
                    <span class="value">{{ alertData.isin }}</span>
                </div>
                <div class="badge-separator"></div>
                <div class="badge-group">
                    <span class="tag type" :class="alertData.trade_type?.toLowerCase()">{{ alertData.trade_type }}</span>
                </div>
                <div class="badge-group">
                    <span class="status-badge" :class="getStatusClass(alertData.status)">{{ alertData.status }}</span>
                </div>
            </div>

            <!-- Row 3: Metrics Grid -->
            <div class="header-metrics">
                <!-- Timeframe Column -->
                <div class="metric-column">
                    <div class="metric-label">TIMEFRAME</div>
                    <div class="metric-grid">
                        <div class="metric-cell">
                            <span class="sub-label">Alert Date</span>
                            <span class="metric-value">{{ alertData.alert_date }}</span>
                        </div>
                        <div class="metric-cell">
                            <span class="sub-label">Range</span>
                            <span class="metric-value">{{ alertData.start_date }} <span class="arrow">→</span> {{ alertData.end_date }}</span>
                        </div>
                    </div>
                </div>

                <!-- Volume Column -->
                <div class="metric-column">
                    <div class="metric-label">VOLUME</div>
                    <div class="metric-grid">
                        <div class="metric-cell">
                            <span class="sub-label">Buy</span>
                            <span class="metric-value">{{ alertData.buy_quantity?.toLocaleString() || '-' }}</span>
                        </div>
                        <div class="metric-cell">
                            <span class="sub-label">Sell</span>
                            <span class="metric-value">{{ alertData.sell_quantity?.toLocaleString() || '-' }}</span>
                        </div>
                    </div>
                </div>

                <!-- Content Column -->
                <div class="metric-column">
                    <div class="metric-label">CONTENT</div>
                    <div class="metric-grid">
                        <div class="metric-cell">
                            <span class="sub-label">Articles</span>
                            <span class="metric-value">{{ newsCount }}</span>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </header>
</template>

<style scoped>
/* Main Container */
.header { 
    background: var(--color-surface); 
    border-bottom: 1px solid var(--color-border); 
    padding: 1rem 1.5rem; 
    box-shadow: var(--shadow-sm); 
    flex-shrink: 0; 
}
.header-container { display: flex; flex-direction: column; gap: 1rem; }

/* 1. Identity & Actions */
.header-top { display: flex; justify-content: space-between; align-items: center; }
.identity-section { display: flex; align-items: baseline; gap: 1rem; }
.identity-section h1 { margin: 0; font-size: 1.75rem; color: var(--color-text-main); font-weight: 700; line-height: 1; }
.identity-section .subtitle { font-size: 1rem; color: var(--color-text-muted); font-weight: 400; }

.actions-section { display: flex; gap: 0.75rem; }
.action-btn { 
    padding: 0.5rem 1rem; 
    border: 1px solid var(--color-border); 
    border-radius: 0.5rem; 
    font-size: 0.875rem; 
    font-weight: 600; 
    cursor: pointer; 
    transition: all 0.2s; 
    background: var(--color-surface);
    color: var(--color-text-main);
    display: flex; 
    align-items: center; 
    gap: 6px; 
}
.action-btn:disabled { opacity: 0.5; cursor: not-allowed; filter: grayscale(0.2); }

.ask-ai-btn { background: var(--color-accent); color: #ffffff; border-color: transparent; margin-right: 0.5rem; }
.ask-ai-btn:hover { background: var(--color-accent-hover); box-shadow: var(--shadow-sm); }

.dismiss-btn,
.escalate-btn,
.review-btn { background: var(--color-surface); color: var(--color-text-main); }
.dismiss-btn:hover:not(:disabled),
.escalate-btn:hover:not(:disabled),
.review-btn:hover:not(:disabled) { background: var(--color-surface-hover); box-shadow: var(--shadow-sm); }

/* 2. Context Row */
.header-context { display: flex; flex-wrap: wrap; gap: 1rem; align-items: center; font-size: 0.8rem; }
.badge-group { display: flex; align-items: center; gap: 6px; }
.badge-group .label { color: var(--color-text-subtle); font-weight: 500; text-transform: uppercase; font-size: 0.7rem; letter-spacing: 0.5px; }
.badge-group .value { font-family: var(--font-family-ui); color: var(--color-primary-light); background: var(--color-surface-hover); padding: 2px 6px; border-radius: 4px; }
.badge-separator { width: 1px; height: 16px; background: var(--color-border); margin: 0 0.25rem; }

.tag.type { text-transform: uppercase; padding: 0.25rem 0.75rem; border-radius: 9999px; font-weight: 600; font-size: 0.75rem; letter-spacing: 0.5px; }
.tag.type.buy { background-color: var(--color-success-bg); color: var(--color-success-text); }
.tag.type.sell { background-color: var(--color-danger-bg); color: var(--color-danger-text); }

.status-badge { padding: 0.25rem 0.75rem; border-radius: 6px; font-weight: 600; text-transform: uppercase; font-size: 0.75rem; }
.status-needs-review { background-color: var(--color-warning-bg); color: var(--color-warning-text); border: 1px solid color-mix(in srgb, var(--color-warning) 30%, white); }
.status-escalate-l2 { background-color: var(--color-danger-bg); color: var(--color-danger-text); border: 1px solid color-mix(in srgb, var(--color-danger) 24%, white); }
.status-dismiss { background-color: var(--color-success-bg); color: var(--color-success-text); border: 1px solid color-mix(in srgb, var(--color-success) 28%, white); }

/* 3. Metrics Grid */
.header-metrics { 
    display: flex; 
    flex-wrap: wrap; /* Allow wrapping */
    gap: 2rem; 
    row-gap: 1.5rem; /* Gap when wrapped */
    padding-top: 1rem; 
    border-top: 1px solid var(--color-divider); 
}
.metric-column { 
    display: flex; 
    flex-direction: column; 
    gap: 0.5rem; 
    min-width: 120px; /* Prevent crushing */
}
.metric-label { font-size: 0.7rem; font-weight: 700; color: var(--color-text-subtle); letter-spacing: 0.5px; text-transform: uppercase; }
.metric-grid { display: flex; gap: 1.5rem; flex-wrap: wrap; } /* Sub-items can wrap if needed */
.metric-cell { display: flex; flex-direction: column; gap: 2px; }
.sub-label { font-size: 0.7rem; color: var(--color-text-muted); }
.metric-value { font-size: 0.9rem; color: var(--color-text-main); font-weight: 600; white-space: nowrap; }
.arrow { color: var(--color-text-subtle); font-size: 0.8rem; margin: 0 4px; }
</style>

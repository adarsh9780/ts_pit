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
                        <span class="icon">🤖</span> Ask AI
                    </button>
                    <button
                        v-if="validStatuses.includes('ESCALATE_L2')"
                        class="action-btn escalate-btn"
                        @click="updateStatus('ESCALATE_L2')"
                        :disabled="alertData.status === 'ESCALATE_L2'"
                    >
                        <span class="icon">!</span> Escalate L2
                    </button>
                    <button
                        v-if="validStatuses.includes('DISMISS')"
                        class="action-btn dismiss-btn"
                        @click="updateStatus('DISMISS')"
                        :disabled="alertData.status === 'DISMISS'"
                    >
                        <span class="icon">✓</span> Dismiss
                    </button>
                    <button
                        v-if="validStatuses.includes('NEEDS_REVIEW')"
                        class="action-btn review-btn"
                        @click="updateStatus('NEEDS_REVIEW')"
                        :disabled="alertData.status === 'NEEDS_REVIEW'"
                    >
                        <span class="icon">↺</span> Needs Review
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
                <div class="badge-separator" v-if="alertData.narrative_theme"></div>
                <!-- Theme Badge -->
                <div class="badge-group full-width" v-if="alertData.narrative_theme">
                   <div class="theme-badge" title="AI Generated Theme">
                       <span class="theme-icon">✨</span> {{ alertData.narrative_theme }}
                   </div>
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
    background: white; 
    border-bottom: 1px solid #e2e8f0; 
    padding: 1rem 1.5rem; 
    box-shadow: 0 1px 2px rgba(0,0,0,0.05); 
    flex-shrink: 0; 
}
.header-container { display: flex; flex-direction: column; gap: 1rem; }

/* 1. Identity & Actions */
.header-top { display: flex; justify-content: space-between; align-items: center; }
.identity-section { display: flex; align-items: baseline; gap: 1rem; }
.identity-section h1 { margin: 0; font-size: 1.75rem; color: #0f172a; font-weight: 700; line-height: 1; }
.identity-section .subtitle { font-size: 1rem; color: #64748b; font-weight: 400; }

.actions-section { display: flex; gap: 0.75rem; }
.action-btn { 
    padding: 0.5rem 1rem; 
    border: none; 
    border-radius: 0.5rem; 
    font-size: 0.875rem; 
    font-weight: 600; 
    cursor: pointer; 
    transition: all 0.2s; 
    display: flex; 
    align-items: center; 
    gap: 6px; 
}
.action-btn:disabled { opacity: 0.5; cursor: not-allowed; filter: grayscale(0.2); }

.ask-ai-btn { background: #3b82f6; color: white; margin-right: 0.5rem; }
.ask-ai-btn:hover { background: #2563eb; box-shadow: 0 2px 4px rgba(59, 130, 246, 0.3); }

.dismiss-btn { background: #dcfce7; color: #166534; }
.dismiss-btn:hover:not(:disabled) { background: #bbf7d0; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
.escalate-btn { background: #fee2e2; color: #991b1b; }
.escalate-btn:hover:not(:disabled) { background: #fecaca; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
.review-btn { background: #fff7ed; color: #c2410c; }
.review-btn:hover:not(:disabled) { background: #ffedd5; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }

/* 2. Context Row */
.header-context { display: flex; flex-wrap: wrap; gap: 1rem; align-items: center; font-size: 0.8rem; }
.badge-group { display: flex; align-items: center; gap: 6px; }
.badge-group .label { color: #94a3b8; font-weight: 500; text-transform: uppercase; font-size: 0.7rem; letter-spacing: 0.5px; }
.badge-group .value { font-family: 'Monaco', 'Consolas', monospace; color: #334155; background: #f1f5f9; padding: 2px 6px; border-radius: 4px; }
.badge-separator { width: 1px; height: 16px; background: #e2e8f0; margin: 0 0.25rem; }

.tag.type { text-transform: uppercase; padding: 0.25rem 0.75rem; border-radius: 9999px; font-weight: 600; font-size: 0.75rem; letter-spacing: 0.5px; }
.tag.type.buy { background-color: #dcfce7; color: #166534; }
.tag.type.sell { background-color: #fee2e2; color: #991b1b; }

.status-badge { padding: 0.25rem 0.75rem; border-radius: 6px; font-weight: 600; text-transform: uppercase; font-size: 0.75rem; }
.status-needs-review { background-color: #fff7ed; color: #c2410c; border: 1px solid #ffedd5; }
.status-escalate-l2 { background-color: #fef2f2; color: #b91c1c; border: 1px solid #fee2e2; }
.status-dismiss { background-color: #f0fdf4; color: #15803d; border: 1px solid #dcfce7; }

.theme-badge {
    background-color: #f3e8ff; color: #7e22ce; border: 1px solid #d8b4fe;
    display: inline-flex; align-items: center; gap: 6px; padding: 0.25rem 0.75rem; border-radius: 9999px; font-weight: 500; font-size: 0.8rem;
}

/* 3. Metrics Grid */
.header-metrics { 
    display: flex; 
    flex-wrap: wrap; /* Allow wrapping */
    gap: 2rem; 
    row-gap: 1.5rem; /* Gap when wrapped */
    padding-top: 1rem; 
    border-top: 1px solid #f1f5f9; 
}
.metric-column { 
    display: flex; 
    flex-direction: column; 
    gap: 0.5rem; 
    min-width: 120px; /* Prevent crushing */
}
.metric-label { font-size: 0.7rem; font-weight: 700; color: #94a3b8; letter-spacing: 0.5px; text-transform: uppercase; }
.metric-grid { display: flex; gap: 1.5rem; flex-wrap: wrap; } /* Sub-items can wrap if needed */
.metric-cell { display: flex; flex-direction: column; gap: 2px; }
.sub-label { font-size: 0.7rem; color: #64748b; }
.metric-value { font-size: 0.9rem; color: #0f172a; font-weight: 600; white-space: nowrap; }
.arrow { color: #cbd5e1; font-size: 0.8rem; margin: 0 4px; }
</style>

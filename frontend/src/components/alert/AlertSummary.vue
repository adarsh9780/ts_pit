<script setup>
import { ref, computed } from 'vue';

const props = defineProps({
    alertData: { type: Object, required: true },
    isGeneratingSummary: { type: Boolean, default: false }
});

const emit = defineEmits(['refresh', 'analyze']);

const summaryTab = ref('narrative'); // 'narrative' or 'recommendation'

const parseEvents = (data) => {
    if (!data) return [];
    if (Array.isArray(data)) {
        // Clean bullet characters from array items
        return data.map(item => typeof item === 'string' ? item.replace(/^[-*•]\s*/, '') : item);
    }
    try {
        const parsed = JSON.parse(data);
        return Array.isArray(parsed) ? parsed.map(item => typeof item === 'string' ? item.replace(/^[-*•]\s*/, '') : item) : [];
    } catch (e) {
        return [];
    }
};

const parseReasoning = (text) => {
    if (!text) return { intro: [], sections: [] };

    const lines = text
        .split('\n')
        .map(line => line.trim())
        .filter(line => line.length > 0);

    const intro = [];
    const sections = [];
    let currentSection = null;

    for (const rawLine of lines) {
        const isBullet = /^[-*•]\s+/.test(rawLine);
        const clean = rawLine.replace(/^[-*•]\s*/, '');
        // Treat subsection headers consistently even if older data stored them with bullet prefix.
        const isHeader = clean.endsWith(':');

        if (isHeader) {
            currentSection = { title: clean.slice(0, -1), items: [] };
            sections.push(currentSection);
            continue;
        }

        if (currentSection) {
            currentSection.items.push(clean);
        } else {
            intro.push(clean);
        }
    }

    return { intro, sections };
};

const recommendationClass = computed(() => {
    if (!props.alertData || !props.alertData.recommendation) return '';
    const rec = props.alertData.recommendation.toUpperCase();
    if (rec.includes('DISMISS') || rec.includes('REJECT')) return 'reject'; // Green
    if (rec.includes('ESCALATE_L2') || rec.includes('APPROVE') || rec.includes('UNEXPLAINED')) return 'approve_l2'; // Red
    if (rec.includes('NEEDS_REVIEW') || rec.includes('PENDING')) return 'needs_review'; // Amber
    return 'needs_review';
});

const reasoningParsed = computed(() => parseReasoning(props.alertData?.recommendation_reason || ''));
</script>

<template>
    <div class="executive-summary-wrapper">
        <div v-if="alertData.narrative_summary" class="executive-summary">
            <div class="summary-header">
                <div class="header-left-group">
                    <h4><span class="ai-icon">AI</span> Investigation Summary</h4>
                    <div class="summary-tabs">
                        <button :class="{ active: summaryTab === 'narrative' }" @click="summaryTab = 'narrative'">Summary</button>
                        <button :class="{ active: summaryTab === 'recommendation' }" @click="summaryTab = 'recommendation'">Recommendation</button>
                    </div>
                </div>
                <button class="refresh-btn" @click="emit('refresh')" :disabled="isGeneratingSummary" title="Regenerate Summary">
                    <div v-if="isGeneratingSummary" class="spinner-icon"></div>
                    <span v-else>↻</span>
                </button>
            </div>
            <div :class="{ 'dimmed': isGeneratingSummary }">
                <!-- NARRATIVE TAB -->
                <div v-if="summaryTab === 'narrative'">
                    <h4>
                        <span class="theme-label">Theme:</span> 
                        {{ alertData.narrative_theme }}
                    </h4>
                    <p class="summary-text">{{ alertData.narrative_summary }}</p>
                    
                    <!-- Event Breakdown Grid -->
                    <div class="events-grid">
                        <div v-if="parseEvents(alertData.bullish_events).length" class="event-col bullish">
                            <h5><span class="indicator">+</span> Bullish Factors</h5>
                            <ul>
                                <li v-for="(event, i) in parseEvents(alertData.bullish_events)" :key="i">{{ event }}</li>
                            </ul>
                        </div>
                        
                        <div v-if="parseEvents(alertData.bearish_events).length" class="event-col bearish">
                            <h5><span class="indicator">-</span> Bearish Factors</h5>
                            <ul>
                                <li v-for="(event, i) in parseEvents(alertData.bearish_events)" :key="i">{{ event }}</li>
                            </ul>
                        </div>
                        
                        <div v-if="parseEvents(alertData.neutral_events).length" class="event-col neutral">
                            <h5><span class="indicator">~</span> Neutral / Context</h5>
                            <ul>
                                <li v-for="(event, i) in parseEvents(alertData.neutral_events)" :key="i">{{ event }}</li>
                            </ul>
                        </div>
                    </div>
                </div>

                <!-- RECOMMENDATION TAB -->
                <div v-if="summaryTab === 'recommendation'">
                    <div v-if="alertData.recommendation" class="recommendation-banner" :class="recommendationClass">
                        <div class="rec-icon">
                            <span v-if="recommendationClass === 'reject'">✅</span>
                            <span v-else-if="recommendationClass === 'approve_l2'">⚠️</span>
                            <span v-else>🟡</span>
                        </div>
                        <div class="rec-text">
                            <div class="rec-title">
                                {{ alertData.recommendation }}
                            </div>
                        </div>
                    </div>
                    
                    <div class="reasoning-section">
                        <h5>Decision Logic & Evidence:</h5>
                        <ul v-if="reasoningParsed.intro.length">
                            <li v-for="(point, i) in reasoningParsed.intro" :key="`intro-${i}`">{{ point }}</li>
                        </ul>
                        <div v-for="(section, idx) in reasoningParsed.sections" :key="`section-${idx}`" class="reason-subsection">
                            <h6>{{ section.title }}</h6>
                            <ul>
                                <li v-for="(item, i) in section.items" :key="`item-${idx}-${i}`">{{ item }}</li>
                            </ul>
                        </div>
                        <div v-if="!alertData.recommendation_reason" class="empty-reasoning">
                            No detailed reasoning available. Regenerate the summary to get facts.
                        </div>
                    </div>
                </div>
            </div>

            <span class="summary-meta">Generated: {{ new Date(alertData.summary_generated_at).toLocaleString() }}</span>
        </div>
        
        <div v-else class="summary-placeholder">
             <button class="generate-btn" @click="emit('analyze')" :disabled="isGeneratingSummary">
                <span v-if="isGeneratingSummary" class="spinner-sm"></span>
                <span v-else>Analyze with AI</span>
            </button>
        </div>
    </div>
</template>

<style scoped>
.executive-summary-wrapper {
    border-bottom: 1px solid var(--color-border);
    background: var(--color-background);
}

.executive-summary {
    background: var(--color-background);
    padding: 1.25rem;
}

.summary-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 0.75rem;
}

.executive-summary h4 {
    margin: 0;
    color: var(--color-text-main);
    font-size: 0.9rem;
    display: flex;
    align-items: center;
    gap: 6px;
    font-weight: 700;
}

.ai-icon {
    background: var(--color-accent);
    color: white;
    font-size: 0.65rem;
    font-weight: 700;
    padding: 2px 6px;
    border-radius: 4px;
    letter-spacing: 0.5px;
}

.executive-summary p {
    margin: 0;
    font-size: 0.9rem;
    color: var(--color-primary-light);
    line-height: 1.6;
}

.summary-meta {
    display: block;
    margin-top: 8px;
    font-size: 0.7rem;
    color: var(--color-text-subtle);
}

.refresh-btn {
    background: transparent;
    border: none;
    color: var(--color-text-subtle);
    cursor: pointer;
    font-size: 1rem;
    padding: 2px 6px;
    border-radius: 4px;
}

.refresh-btn:hover {
    background: var(--color-surface-hover);
    color: var(--color-text-muted);
}

.summary-placeholder {
    padding: 1rem;
    display: flex;
    justify-content: center;
    background: var(--color-surface);
}

.generate-btn {
    background: var(--color-accent);
    color: white;
    border: none;
    padding: 0.6rem 1.2rem;
    border-radius: 6px;
    font-weight: 600;
    font-size: 0.85rem;
    cursor: pointer;
    display: flex;
    align-items: center;
    gap: 8px;
    box-shadow: var(--shadow-sm);
    transition: all 0.2s;
}

.generate-btn:hover:not(:disabled) {
    transform: translateY(-1px);
    background: var(--color-accent-hover);
    box-shadow: var(--shadow-md);
}

.generate-btn:disabled {
    opacity: 0.7;
    cursor: wait;
}

.spinner-sm {
    width: 14px;
    height: 14px;
    border: 2px solid rgba(255,255,255,0.3);
    border-top-color: white;
    border-radius: 50%;
    animation: spin 1s linear infinite;
}

.spinner-icon {
    width: 14px;
    height: 14px;
    border: 2px solid var(--color-border);
    border-top-color: var(--color-accent);
    border-radius: 50%;
    animation: Spin 0.8s linear infinite;
}

.dimmed {
    opacity: 0.5;
    pointer-events: none;
    transition: opacity 0.3s ease;
}

@keyframes Spin {
    to { transform: rotate(360deg); }
}

/* Header Grouping for Tabs */
.header-left-group {
    display: flex;
    align-items: center;
    gap: 1.5rem;
}

/* Tabs Styling */
.summary-tabs {
    display: flex;
    background: var(--color-surface-hover);
    padding: 3px;
    border-radius: 6px;
    gap: 2px;
}

.summary-tabs button {
    border: none;
    background: transparent;
    padding: 4px 12px;
    font-size: 0.75rem;
    font-weight: 600;
    color: var(--color-text-muted);
    border-radius: 4px;
    cursor: pointer;
    transition: all 0.2s;
}

.summary-tabs button:hover {
    color: var(--color-primary-light);
}

.summary-tabs button.active {
    background: var(--color-surface);
    color: var(--color-accent);
    box-shadow: var(--shadow-sm);
}

/* Reasoning Section */
.reasoning-section {
    padding-top: 0.5rem;
}

.reasoning-section h5 {
    margin: 0 0 0.5rem 0;
    font-size: 0.85rem;
    font-weight: 700;
    color: var(--color-primary-light);
    text-transform: uppercase;
    letter-spacing: 0.5px;
}

.reasoning-section ul {
    margin: 0;
    padding-left: 1.25rem;
}

.reasoning-section li {
    font-size: 0.9rem;
    color: var(--color-primary-light);
    margin-bottom: 0.5rem;
    line-height: 1.5;
}

.reason-subsection {
    margin-top: 0.85rem;
}

.reason-subsection h6 {
    margin: 0 0 0.35rem 0;
    font-size: 0.85rem;
    font-weight: 700;
    color: var(--color-text-main);
}

.empty-reasoning {
    font-style: italic;
    color: var(--color-text-subtle);
    font-size: 0.85rem;
}

/* Events Grid */
.events-grid {
    display: flex;
    gap: 1.5rem;
    margin-top: 1rem;
    padding-top: 1rem;
    border-top: 1px solid var(--color-border);
}
.event-col { flex: 1; }
.event-col h5 { margin: 0 0 0.5rem 0; font-size: 0.85rem; font-weight: 700; display: flex; align-items: center; gap: 6px; }
.event-col ul { margin: 0; padding-left: 1.2rem; }
.event-col li { font-size: 0.85rem; color: var(--color-text-muted); margin-bottom: 0.25rem; }
.event-col.bullish h5 { color: var(--color-success-text); }
.event-col.bullish .indicator { background: var(--color-success-bg); color: var(--color-success-text); padding: 2px 6px; border-radius: 4px; font-size: 0.7rem; }
.event-col.bearish h5 { color: var(--color-danger-text); }
.event-col.bearish .indicator { background: var(--color-danger-bg); color: var(--color-danger-text); padding: 2px 6px; border-radius: 4px; font-size: 0.7rem; }
.event-col.neutral h5 { color: var(--color-text-muted); }
.event-col.neutral .indicator { background: var(--color-surface-hover); color: var(--color-text-muted); padding: 2px 6px; border-radius: 4px; font-size: 0.7rem; }

/* Recommendation Banner Styles */
.recommendation-banner {
    display: flex;
    align-items: flex-start;
    gap: 12px;
    padding: 12px;
    border-radius: 8px;
    margin-bottom: 16px;
    border: 1px solid transparent;
}
.recommendation-banner.reject {
    background-color: var(--color-success-bg);
    border-color: #bbf7d0;
    color: var(--color-success-text);
}
.recommendation-banner.approve_l2 {
    background-color: var(--color-danger-bg);
    border-color: #fecaca;
    color: var(--color-danger-text);
}
.recommendation-banner.needs_review {
    background-color: var(--color-warning-bg);
    border-color: #fde68a;
    color: var(--color-warning-text);
}
.rec-icon {
    font-size: 1.5rem;
    line-height: 1;
}
.rec-title {
    font-weight: 700;
    font-size: 0.9rem;
    text-transform: uppercase;
    margin-bottom: 4px;
}
</style>

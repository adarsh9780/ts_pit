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
        const isHeader = !isBullet && clean.endsWith(':');

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
    border-bottom: 1px solid #e2e8f0;
    background: #f8fafc;
}

.executive-summary {
    background: linear-gradient(to right, #fbf7ff, #f8fafc);
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
    color: #4c1d95;
    font-size: 0.9rem;
    display: flex;
    align-items: center;
    gap: 6px;
    font-weight: 700;
}

.ai-icon {
    background: linear-gradient(135deg, #4c1d95, #7c3aed);
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
    color: #334155;
    line-height: 1.6;
}

.summary-meta {
    display: block;
    margin-top: 8px;
    font-size: 0.7rem;
    color: #94a3b8;
}

.refresh-btn {
    background: transparent;
    border: none;
    color: #94a3b8;
    cursor: pointer;
    font-size: 1rem;
    padding: 2px 6px;
    border-radius: 4px;
}

.refresh-btn:hover {
    background: #e2e8f0;
    color: #64748b;
}

.summary-placeholder {
    padding: 1rem;
    display: flex;
    justify-content: center;
    background: #fff;
}

.generate-btn {
    background: linear-gradient(135deg, #7c3aed, #6d28d9);
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
    box-shadow: 0 2px 4px rgba(124, 58, 237, 0.2);
    transition: all 0.2s;
}

.generate-btn:hover:not(:disabled) {
    transform: translateY(-1px);
    box-shadow: 0 4px 6px rgba(124, 58, 237, 0.3);
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
    border: 2px solid #cbd5e1;
    border-top-color: #6366f1;
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
    background: #e2e8f0;
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
    color: #64748b;
    border-radius: 4px;
    cursor: pointer;
    transition: all 0.2s;
}

.summary-tabs button:hover {
    color: #334155;
}

.summary-tabs button.active {
    background: white;
    color: #4c1d95; /* Deep Purple to match header */
    box-shadow: 0 1px 2px rgba(0,0,0,0.05);
}

/* Reasoning Section */
.reasoning-section {
    padding-top: 0.5rem;
}

.reasoning-section h5 {
    margin: 0 0 0.5rem 0;
    font-size: 0.85rem;
    font-weight: 700;
    color: #334155;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}

.reasoning-section ul {
    margin: 0;
    padding-left: 1.25rem;
}

.reasoning-section li {
    font-size: 0.9rem;
    color: #334155;
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
    color: #1e293b;
}

.empty-reasoning {
    font-style: italic;
    color: #94a3b8;
    font-size: 0.85rem;
}

/* Events Grid */
.events-grid {
    display: flex;
    gap: 1.5rem;
    margin-top: 1rem;
    padding-top: 1rem;
    border-top: 1px solid #e2e8f0;
}
.event-col { flex: 1; }
.event-col h5 { margin: 0 0 0.5rem 0; font-size: 0.85rem; font-weight: 700; display: flex; align-items: center; gap: 6px; }
.event-col ul { margin: 0; padding-left: 1.2rem; }
.event-col li { font-size: 0.85rem; color: #475569; margin-bottom: 0.25rem; }
.event-col.bullish h5 { color: #166534; }
.event-col.bullish .indicator { background: #dcfce7; color: #166534; padding: 2px 6px; border-radius: 4px; font-size: 0.7rem; }
.event-col.bearish h5 { color: #991b1b; }
.event-col.bearish .indicator { background: #fee2e2; color: #991b1b; padding: 2px 6px; border-radius: 4px; font-size: 0.7rem; }
.event-col.neutral h5 { color: #475569; }
.event-col.neutral .indicator { background: #f1f5f9; color: #475569; padding: 2px 6px; border-radius: 4px; font-size: 0.7rem; }

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
    background-color: #f0fdf4; /* Green-50 */
    border-color: #bbf7d0;     /* Green-200 */
    color: #166534;            /* Green-800 */
}
.recommendation-banner.approve_l2 {
    background-color: #fef2f2; /* Red-50 */
    border-color: #fecaca;     /* Red-200 */
    color: #991b1b;            /* Red-800 */
}
.recommendation-banner.needs_review {
    background-color: #fffbeb; /* Amber-50 */
    border-color: #fde68a;     /* Amber-200 */
    color: #92400e;            /* Amber-800 */
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

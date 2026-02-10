<script setup>
import { computed } from 'vue';

const props = defineProps({
    news: { type: Array, default: () => [] }, // The FILTERED news list
    themes: { type: Array, default: () => [] }, // List of themes for dropdown
    activeTheme: { type: String, default: 'All' },
    config: { type: Object, default: () => ({}) }
});

const emit = defineEmits(['update:activeTheme', 'hover-materiality', 'leave-materiality']);

const localTheme = computed({
    get: () => props.activeTheme,
    set: (val) => emit('update:activeTheme', val)
});

// Helper for materiality colors
const getMaterialityColor = (code) => {
    if (!props.config || !props.config.materiality_colors) return '#808080';
    return props.config.materiality_colors[code] || props.config.materiality_colors['DEFAULT'] || '#808080';
};

const resolveArticleId = (article) => article?.id ?? article?.article_id ?? article?.art_id ?? '-';
</script>

<template>
    <div class="card news-panel">
        <div class="card-header news-header">
            <h3>Relevant News</h3>
            <div class="theme-selector">
                 <select v-model="localTheme" class="theme-dropdown">
                    <option v-for="theme in themes" :key="theme" :value="theme">{{ theme.replace(/_/g, ' ') }}</option>
                </select>
            </div>
        </div>
        <div class="card-body scrollable">
            
            <slot name="summary"></slot>

            <div v-if="news.length > 0" class="news-feed">
                <div v-for="article in news" :key="resolveArticleId(article)" class="news-item" :class="{ 'analyzed': article.analysis }">
                    <div class="news-meta">
                        <span class="news-date">#{{ resolveArticleId(article) }} • {{ article.created_date }}</span>
                        <span class="news-theme">{{ article.theme.replace(/_/g, ' ') }}</span>
                    </div>
                    <h4 class="news-title">{{ article.title }}</h4>
                    
                    <!-- AI Analysis Block -->
                    <div v-if="article.analysis" class="analysis-block">
                        <div class="analysis-label">AI Logic:</div>
                        <p class="analysis-content">{{ article.analysis }}</p>
                    </div>
                    
                    <div v-if="article.summary" class="news-summary">{{ article.summary }}</div>
                    
                    <div class="news-footer">
                        <span class="sentiment-indicator" :class="article.sentiment.split(':')[0].toLowerCase()">{{ article.sentiment.split(':')[0] }}</span>
                        <template v-if="config && config.has_materiality && article.materiality">
                            <span class="separator">•</span>
                            <span class="materiality-indicator" 
                                  :style="{ color: getMaterialityColor(article.materiality) }"
                                  @mouseenter="emit('hover-materiality', $event, article.materiality_details)"
                                  @mouseleave="emit('leave-materiality')"
                            >
                                {{ article.materiality }}
                            </span>
                        </template>
                        
                        <template v-if="article.impact_label">
                            <span class="separator">•</span>
                            <span class="impact-badge" :class="article.impact_label.toLowerCase()">
                                <span class="impact-label">{{ article.impact_label }}</span>
                                <span class="impact-score" v-if="article.impact_score">({{ article.impact_score.toFixed(1) }}σ)</span>
                            </span>
                        </template>
                    </div>
                </div>
            </div>
             <div v-else class="empty-state">No news found for this specific theme.</div>
        </div>
    </div>
</template>

<style scoped>
.card { background: white; border-radius: 0.75rem; border: 1px solid #e2e8f0; box-shadow: 0 1px 3px rgba(0,0,0,0.05); display: flex; flex-direction: column; }
.card-header { padding: 1rem 1.5rem; border-bottom: 1px solid #f1f5f9; background: #ffffff; flex-shrink: 0; }
.news-header { display: flex; justify-content: space-between; align-items: center; }
.card-header h3 { margin: 0; font-size: 1rem; font-weight: 600; color: #334155; }

.theme-dropdown { padding: 0.25rem 0.5rem; border: 1px solid #cbd5e1; border-radius: 0.375rem; font-size: 0.875rem; color: #334155; background-color: white; }

.card-body { flex: 1; position: relative; min-height: 0; }
.news-panel { flex: 1; min-width: 450px; display: flex; flex-direction: column; height: 100%; }
.scrollable { overflow-y: auto; padding: 0; height: 100%; }
.news-feed { padding: 1.5rem; }
.news-item { margin-bottom: 1.25rem; padding: 1rem; background: #f8fafc; border-radius: 0.5rem; border: 1px solid #e2e8f0; transition: all 0.2s ease; overflow: visible; }
.news-item:last-child { margin-bottom: 0; }
.news-meta { display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem; font-size: 0.75rem; }
.news-date { color: #64748b; font-weight: 500; }
.news-theme { color: #6366f1; font-weight: 600; background: #eef2ff; padding: 0 0.5rem; border-radius: 4px; font-size: 0.7rem; }
.news-title { margin: 0 0 0.5rem 0; font-size: 1rem; color: #1e293b; line-height: 1.4; }
.news-summary { font-size: 0.875rem; color: #475569; line-height: 1.5; margin-bottom: 0.75rem; }
.sentiment-indicator { font-size: 0.75rem; font-weight: 600; }
.sentiment-indicator.bullish { color: #16a34a; }
.sentiment-indicator.bearish { color: #dc2626; }
.sentiment-indicator.neutral { color: #64748b; }
.separator { margin: 0 0.5rem; color: #cbd5e1; }

/* Analysis Block */
.news-item.analyzed {
    border-left: 3px solid #7c3aed;
    background: #fdfbff;
}
.analysis-block {
    margin: 8px 0 12px 0;
    padding: 8px 12px;
    background: #f3e8ff;
    border-radius: 6px;
    font-size: 0.85rem;
    border: 1px solid #e9d5ff;
}
.analysis-label {
    font-weight: 700;
    color: #6b21a8;
    margin-bottom: 4px;
    font-size: 0.75rem;
    text-transform: uppercase;
}

/* Materiality Indicator */
.materiality-indicator {
    font-size: 0.75rem;
    font-weight: 700;
    cursor: help;
    display: inline-block;
    color: #475569;
}

/* Impact Badges */
.news-footer { display: flex; align-items: center; flex-wrap: wrap; margin-top: 0.75rem; }
.impact-badge { font-size: 0.75rem; font-weight: 600; display: inline-flex; gap: 4px; align-items: center; }
.impact-badge.low,
.impact-badge.noise { color: #94a3b8; }
.impact-badge.medium,
.impact-badge.significant { color: #d97706; }
.impact-badge.high,
.impact-badge.extreme { color: #7c3aed; background: #f3e8ff; padding: 0 4px; border-radius: 4px; }
.impact-score { font-weight: 400; font-size: 0.7rem; opacity: 0.8; }

.empty-state { padding: 2rem; text-align: center; color: #94a3b8; font-style: italic; display: flex; align-items: center; justify-content: center; height: 100%; }
</style>

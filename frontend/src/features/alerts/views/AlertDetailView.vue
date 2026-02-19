<script setup>
import { ref, onMounted, onBeforeUnmount, computed, watch, shallowRef } from 'vue';
import ConfirmDialog from '../../../components/ConfirmDialog.vue';
import VChart from 'vue-echarts';
import { use } from 'echarts/core';
import { CanvasRenderer } from 'echarts/renderers';
import { LineChart, ScatterChart, BarChart, CandlestickChart } from 'echarts/charts';
import { GridComponent, TooltipComponent, LegendComponent, MarkAreaComponent, MarkLineComponent } from 'echarts/components';
import AlertHeader from '../../../components/alert/AlertHeader.vue';
import AlertChart from '../../../components/alert/AlertChart.vue';
import AlertSummary from '../../../components/alert/AlertSummary.vue';
import AlertNews from '../../../components/alert/AlertNews.vue';
import { useAlertDetail } from '../composables/useAlertDetail.js';

// Register ECharts components
use([CanvasRenderer, LineChart, ScatterChart, BarChart, CandlestickChart, GridComponent, TooltipComponent, LegendComponent, MarkAreaComponent, MarkLineComponent]);

const ALERT_DETAIL_UI_STATE_NS = 'ts_pit.alert_detail.ui_state.v1';

const props = defineProps({
  alertId: {
    type: [String, Number],
    required: true
  }
});
const emit = defineEmits(['toggle-agent']);
const detailApi = useAlertDetail();

const alertData = ref(null);
const prices = ref({ ticker: [], industry: [], industry_name: '' });
const news = ref([]);
const activeTheme = ref('All');
const selectedPeriod = ref('alert');  // Default to alert-centered view
const isLoadingPrices = ref(false);
const config = ref(null);
const viewMode = ref('chart');
const isGeneratingSummary = ref(false);
const summaryTab = ref('narrative'); // 'narrative' or 'recommendation'
const selectedBubbleArticleIds = ref(null); // List of article IDs for the selected bubble

// Confirm Dialog State
const showConfirmDialog = ref(false);
const confirmAction = ref(null);
const confirmTitle = ref('');
const confirmMessage = ref('');

const openConfirm = (title, message, action) => {
    confirmTitle.value = title;
    confirmMessage.value = message;
    confirmAction.value = action;
    showConfirmDialog.value = true;
};

const handleConfirm = () => {
    if (confirmAction.value) confirmAction.value();
    showConfirmDialog.value = false;
};

const handleCancel = () => {
    showConfirmDialog.value = false;
};

// Chart refs
const chartRef = shallowRef(null);
const chartLabels = ref([]);
const tickerSeriesData = ref([]);
const tickerRebasedSeriesData = ref([]);  // Rebased to 100 for comparison
const industrySeriesData = ref([]);
const industryRebasedSeriesData = ref([]);  // Rebased to 100 for comparison
const volumeSeriesData = ref([]);
const bubbleSeriesData = ref([]);
const candlestickSeriesData = ref([]);  // OHLC data for candlestick chart
const chartType = ref('line');  // 'line' or 'candle'
const priceMode = ref('actual');  // 'actual' or 'rebased' - controls which pair of lines to show

const periods = [
    { label: 'Alert', value: 'alert' },  // Custom: start_date-10 to end_date+10
    { label: '1M', value: '1mo' },
    { label: '3M', value: '3mo' },
    { label: '6M', value: '6mo' },
    { label: '1Y', value: '1y' },
    { label: 'YTD', value: 'ytd' },
    { label: 'Max', value: 'max' },
];
const periodValues = new Set(periods.map((period) => period.value));
const allowedViewModes = new Set(['chart', 'table']);
const allowedChartTypes = new Set(['line', 'candle']);
const allowedPriceModes = new Set(['actual', 'rebased']);
const allowedSummaryTabs = new Set(['narrative', 'recommendation']);

const getDetailUiStateKey = (alertId) => `${ALERT_DETAIL_UI_STATE_NS}:${String(alertId)}`;

const restoreDetailUiState = (alertId) => {
    if (!alertId) return;
    try {
        const raw = localStorage.getItem(getDetailUiStateKey(alertId));
        if (!raw) return;

        const parsed = JSON.parse(raw);
        if (!parsed || typeof parsed !== 'object') return;

        if (typeof parsed.activeTheme === 'string') activeTheme.value = parsed.activeTheme;
        if (typeof parsed.selectedPeriod === 'string' && periodValues.has(parsed.selectedPeriod)) {
            selectedPeriod.value = parsed.selectedPeriod;
        }
        if (typeof parsed.viewMode === 'string' && allowedViewModes.has(parsed.viewMode)) {
            viewMode.value = parsed.viewMode;
        }
        if (typeof parsed.chartType === 'string' && allowedChartTypes.has(parsed.chartType)) {
            chartType.value = parsed.chartType;
        }
        if (typeof parsed.priceMode === 'string' && allowedPriceModes.has(parsed.priceMode)) {
            priceMode.value = parsed.priceMode;
        }
        if (typeof parsed.summaryTab === 'string' && allowedSummaryTabs.has(parsed.summaryTab)) {
            summaryTab.value = parsed.summaryTab;
        }
    } catch (error) {
        console.warn('Failed to restore alert detail UI state:', error);
    }
};

const persistDetailUiState = () => {
    if (!props.alertId) return;
    try {
        localStorage.setItem(
            getDetailUiStateKey(props.alertId),
            JSON.stringify({
                activeTheme: activeTheme.value,
                selectedPeriod: selectedPeriod.value,
                viewMode: viewMode.value,
                chartType: chartType.value,
                priceMode: priceMode.value,
                summaryTab: summaryTab.value
            })
        );
    } catch (error) {
        console.warn('Failed to persist alert detail UI state:', error);
    }
};

// Materiality color scale
const getMaterialityColor = (code) => {
    if (!config.value || !config.value.materiality_colors) return '#808080';
    return config.value.materiality_colors[code] || config.value.materiality_colors['DEFAULT'] || '#808080';
    if (!config.value || !config.value.materiality_colors) return '#808080';
    return config.value.materiality_colors[code] || config.value.materiality_colors['DEFAULT'] || '#808080';
};

// Tooltip State
const showTooltip = ref(false);
const tooltipData = ref(null);
const tooltipPos = ref({ x: 0, y: 0 });

const handleTooltipEnter = (event, details) => {
    if (!details) return;
    tooltipData.value = details;
    showTooltip.value = true;
    
    // Position tooltip near the mouse/element but ensuring it fits
    const rect = event.target.getBoundingClientRect();
    // Default: Top-Centered relative to element
    let x = rect.left + (rect.width / 2) - 140; // Center 280px tooltip
    let y = rect.top - 120; // Above
    
    // Adjust logic if close to edges (simple version)
    if (x < 10) x = 10;
    if (y < 10) y = rect.bottom + 10; // Show below if top is clipped
    
    tooltipPos.value = { x, y };
};

const handleTooltipLeave = () => {
    showTooltip.value = false;
};

const handleTooltipLeave = () => {
    showTooltip.value = false;
};

const handleChartClick = (params) => {
    // If background clicked, reset selection
    if (!params || !params.data) {
        selectedBubbleArticleIds.value = null;
        return;
    }

    // Check if it's a bubble click
    if (params.componentType === 'series' && params.seriesType === 'scatter' && params.seriesName === 'News Events') {
        const articleIds = params.data.articleIds;
        
        // Toggle behavior: if clicking the same bubble, reset.
        if (selectedBubbleArticleIds.value && 
            articleIds && 
            JSON.stringify(selectedBubbleArticleIds.value.sort()) === JSON.stringify(articleIds.sort())) {
            selectedBubbleArticleIds.value = null;
        } else {
            selectedBubbleArticleIds.value = articleIds;
        }
    } else {
        // If clicking other series or background, reset
        selectedBubbleArticleIds.value = null;
    }
};

const chartOptions = computed(() => {
    if (!chartLabels.value.length) return {};
    
    // Calculate mark area for period highlighting
    let markAreaData = [];
    let alertMarkerDate = null;
    
    if (alertData.value && chartLabels.value.length > 0) {
        let targetStart = alertData.value.start_date;
        let targetEnd = alertData.value.end_date;
        
        // Helper to find closest available date in chartLabels
        const findClosestDate = (target, labels) => {
            if (!target) return labels[0];
            if (labels.includes(target)) return target;
            let closest = labels[0];
            let minDiff = Infinity;
            const targetTime = new Date(target).getTime();
            
            for (const label of labels) {
                const diff = Math.abs(new Date(label).getTime() - targetTime);
                if (diff < minDiff) {
                    minDiff = diff;
                    closest = label;
                }
            }
            return closest;
        };

        targetStart = findClosestDate(targetStart, chartLabels.value);
        targetEnd = findClosestDate(targetEnd, chartLabels.value);
        alertMarkerDate = findClosestDate(alertData.value.alert_date, chartLabels.value);

        markAreaData = [[
            { xAxis: targetStart },
            { xAxis: targetEnd }
        ]];
    }
    
    const series = [];
    
    // Ticker series - Candlestick or Line based on chartType
    if (chartType.value === 'candle') {
        series.push({
            name: alertData.value ? alertData.value.ticker : 'Ticker',
            type: 'candlestick',
            data: candlestickSeriesData.value,
            itemStyle: {
                color: '#16a34a',       // Up candle fill (green)
                color0: '#dc2626',      // Down candle fill (red)
                borderColor: '#16a34a', // Up candle border
                borderColor0: '#dc2626' // Down candle border
            },
            markArea: {
                silent: true,
                itemStyle: {
                    color: 'rgba(250, 204, 21, 0.15)',
                    borderColor: '#eab308',
                    borderWidth: 2,
                    borderType: 'dashed'
                },
                data: markAreaData
            },
            markLine: alertMarkerDate ? {
                symbol: ['none', 'none'],
                silent: true,
                lineStyle: {
                    type: 'dotted',
                    color: '#ef4444',
                    width: 2
                },
                label: {
                    show: true,
                    formatter: 'Alert Date',
                    position: 'insideEndTop',
                    color: '#ef4444',
                    fontSize: 10
                },
                data: [{ xAxis: alertMarkerDate }]
            } : undefined
        });
    } else {
        // Line mode - show either Actual or Rebased pair based on priceMode
        if (priceMode.value === 'actual') {
            // ACTUAL MODE: Stock Actual + Industry Actual
            series.push({
                name: alertData.value ? alertData.value.ticker : 'Ticker',
                type: 'line',
                data: tickerSeriesData.value,
                smooth: false,
                symbol: 'none',
                lineStyle: { color: '#3b82f6', width: 2 },
                itemStyle: { color: '#3b82f6' },
                emphasis: { focus: 'series' },
                markArea: {
                    silent: true,
                    itemStyle: {
                        color: 'rgba(250, 204, 21, 0.15)',
                        borderColor: '#eab308',
                        borderWidth: 2,
                        borderType: 'dashed'
                    },
                    data: markAreaData
                },
                markLine: alertMarkerDate ? {
                    symbol: ['none', 'none'],
                    silent: true,
                    lineStyle: {
                        type: 'dotted',
                        color: '#ef4444',
                        width: 2
                    },
                    label: {
                        show: true,
                        formatter: 'Alert Date',
                        position: 'insideEndTop',
                        color: '#ef4444',
                        fontSize: 10
                    },
                    data: [{ xAxis: alertMarkerDate }]
                } : undefined
            });
            
            // Industry Actual (on secondary y-axis for different scale)
            series.push({
                name: `${prices.value.industry_name || 'Industry'}`,
                type: 'line',
                data: industrySeriesData.value,
                smooth: false,
                yAxisIndex: 1,
                symbol: 'none',
                lineStyle: { color: '#94a3b8', width: 2, type: 'dashed' },
                itemStyle: { color: '#94a3b8' },
                emphasis: { focus: 'series' }
            });
        } else {
            // REBASED MODE: Stock Rebased + Industry Rebased (both start at 100)
            series.push({
                name: `${alertData.value ? alertData.value.ticker : 'Ticker'} (Rebased)`,
                type: 'line',
                data: tickerRebasedSeriesData.value,
                smooth: false,
                symbol: 'none',
                lineStyle: { color: '#3b82f6', width: 2 },
                itemStyle: { color: '#3b82f6' },
                emphasis: { focus: 'series' },
                markArea: {
                    silent: true,
                    itemStyle: {
                        color: 'rgba(250, 204, 21, 0.15)',
                        borderColor: '#eab308',
                        borderWidth: 2,
                        borderType: 'dashed'
                    },
                    data: markAreaData
                },
                markLine: alertMarkerDate ? {
                    symbol: ['none', 'none'],
                    silent: true,
                    lineStyle: {
                        type: 'dotted',
                        color: '#ef4444',
                        width: 2
                    },
                    label: {
                        show: true,
                        formatter: 'Alert Date',
                        position: 'insideEndTop',
                        color: '#ef4444',
                        fontSize: 10
                    },
                    data: [{ xAxis: alertMarkerDate }]
                } : undefined
            });
            
            // Industry Rebased (same y-axis since both start at 100)
            series.push({
                name: `${prices.value.industry_name || 'Industry'} (Rebased)`,
                type: 'line',
                data: industryRebasedSeriesData.value,
                smooth: false,
                symbol: 'none',
                lineStyle: { color: '#94a3b8', width: 2, type: 'dashed' },
                itemStyle: { color: '#94a3b8' },
                emphasis: { focus: 'series' }
            });
        }
    }

    
    // Bubble y-values are based on actual prices, so keep them only in actual line mode.
    if (chartType.value !== 'candle' && priceMode.value === 'actual' && bubbleSeriesData.value.length > 0) {
        series.push({
            name: 'News Events',
            type: 'scatter',
            data: bubbleSeriesData.value,
            symbolSize: 16,
            itemStyle: {
                borderColor: '#fff',
                borderWidth: 1
            },
            emphasis: { focus: 'series' }
        });
    }
    
    // Volume is shown in tooltip only (no bar series)
    
    return {
        animation: true,
        animationDuration: 300,
        grid: {
            left: '3%',
            right: '6%',
            bottom: '3%',
            top: '60px',
            containLabel: true
        },
        tooltip: {
            trigger: 'axis',
            axisPointer: {
                type: 'cross',
                crossStyle: { color: '#999' }
            },
            backgroundColor: 'rgba(50, 50, 50, 0.9)',
            borderColor: '#333',
            borderWidth: 1,
            textStyle: { color: '#fff', fontSize: 12 },
            formatter: function(params) {
                if (!params || params.length === 0) return '';
                
                // Get the date from the first param
                const date = params[0].axisValue;
                let html = `<div style="font-weight: 600; margin-bottom: 8px; border-bottom: 1px solid #555; padding-bottom: 4px;">${date}</div>`;
                
                // Process line series
                params.forEach(p => {
                    if (p.seriesType === 'line' && p.value !== null && p.value !== undefined) {
                        const color = p.color;
                        const isDashed = p.seriesName.includes('Index');
                        const lineStyle = isDashed ? 'border-top: 2px dashed' : 'border-top: 2px solid';
                        html += `<div style="display: flex; align-items: center; gap: 8px; margin: 4px 0;">
                            <span style="width: 20px; ${lineStyle} ${color};"></span>
                            <span>${p.seriesName}:</span>
                            <span style="font-weight: 600; margin-left: auto;">${Number(p.value).toFixed(2)}</span>
                        </div>`;
                    }
                    // Show volume
                    if (p.seriesType === 'line' && p.seriesName.includes(alertData.value?.ticker)) {
                        // Get volume for this date from volumeSeriesData
                        const dateIndex = chartLabels.value.indexOf(date);
                        if (dateIndex >= 0 && volumeSeriesData.value[dateIndex]) {
                            const vol = volumeSeriesData.value[dateIndex];
                            const formatted = vol >= 1000000 ? (vol / 1000000).toFixed(2) + 'M' : vol >= 1000 ? (vol / 1000).toFixed(1) + 'K' : vol;
                            html += `<div style="display: flex; align-items: center; gap: 8px; margin: 4px 0; color: #aaa;">
                                <span style="width: 20px; height: 10px; background: rgba(156, 163, 175, 0.6);"></span>
                                <span>Volume:</span>
                                <span style="font-weight: 600; margin-left: auto;">${formatted}</span>
                            </div>`;
                        }
                    }
                });
                
                // Find bubble data for this date (only if materiality is enabled)
                if (config.value && config.value.has_materiality) {
                    const bubbles = bubbleSeriesData.value.filter(b => b.value[0] === date);
                    if (bubbles.length > 0) {
                        html += `<div style="margin-top: 8px; border-top: 1px solid #555; padding-top: 8px; font-weight: 600;">News Events</div>`;
                        bubbles.forEach(b => {
                            const color = b.itemStyle.color;
                            html += `<div style="display: flex; align-items: center; gap: 8px; margin: 4px 0;">
                                <span style="width: 10px; height: 10px; border-radius: 50%; background: ${color}; border: 1px solid #fff;"></span>
                                <span>${b.materiality}:</span>
                                <span style="font-weight: 600; margin-left: auto;">${b.count} article${b.count > 1 ? 's' : ''}</span>
                            </div>`;
                        });
                    }
                }
                
                return html;
            }
        },
        legend: {
            show: true,
            top: 10,
            right: 10,
            textStyle: { fontSize: 11 },
            itemWidth: 20,
            itemHeight: 10
        },
        xAxis: {
            type: 'category',
            data: chartLabels.value,
            axisLine: { lineStyle: { color: '#ccc' } },
            axisTick: { show: false },
            axisLabel: {
                color: '#666',
                fontSize: 11,
                interval: 'auto',
                rotate: 0
            },
            splitLine: { show: false }
        },
        yAxis: [
            {
                type: 'value',
                axisLine: { show: false },
                axisTick: { show: false },
                axisLabel: { color: '#666', fontSize: 11 },
                splitLine: { lineStyle: { color: '#f0f0f0' } },
                scale: true  // Scale axis to data range for better visualization
            },
            // Secondary axis only when in 'actual' line mode (for Industry comparison)
            ...(chartType.value !== 'candle' && priceMode.value === 'actual' ? [{
                type: 'value',
                name: prices.value.industry_name || 'Industry',
                position: 'right',
                axisLine: { show: false },
                axisTick: { show: false },
                axisLabel: { 
                    color: '#94a3b8', 
                    fontSize: 10
                },
                splitLine: { show: false },
                scale: true  // Scale to data range for better visualization
            }] : [])
        ],
        series
    };
});

const fetchAlertDetail = async () => {
    if (!props.alertId) return;
    try {
        const data = await detailApi.fetchAlertDetail(props.alertId);
        alertData.value = data;
        return data;
    } catch (error) {
        console.error('Error fetching alert detail:', error);
    }
};

const analyzeArticles = async () => {
    if (!filteredNews.value || filteredNews.value.length === 0) return;
    
    isGeneratingSummary.value = true; // Use loading state to show spinner
    
    try {
        // Iterate through all visible articles and analyze them
        // We use Promise.all to run them in parallel (or sequential if prefer less load)
        // Parallel is better for UX speed.
        const results = await detailApi.analyzeArticles(filteredNews.value);
        results.forEach((item) => {
            if (!item.ok) {
                console.error(`Failed to analyze article ${item.article.id}:`, item.error);
                return;
            }
            const { article, result } = item;
            article.theme = result.theme;
            if (result.summary) {
                article.summary = result.summary;
            }
            article.analysis = result.analysis;
        });
        
        // After correcting all article themes, generate the MASTER summary
        // This will now use the enriched data from the backend to create a unified narrative
        await generateSummary();
        
    } catch (error) {
        console.error('Error in analysis batch:', error);
    } finally {
        isGeneratingSummary.value = false;
    }
};

const generateSummary = async () => {
    isGeneratingSummary.value = true;
    try {
        const response = await detailApi.generateSummary(props.alertId);
        // Update local state with new summary data
        if (alertData.value) {
            alertData.value.narrative_theme = response.narrative_theme;
            alertData.value.narrative_summary = response.narrative_summary;
            alertData.value.bullish_events = response.bullish_events;
            alertData.value.bearish_events = response.bearish_events;
            alertData.value.neutral_events = response.neutral_events;
            alertData.value.recommendation = response.recommendation;
            alertData.value.recommendation_reason = response.recommendation_reason;
            alertData.value.summary_generated_at = response.summary_generated_at;
        }
    } catch (error) {
        console.error('Error generating summary:', error);
        alert('Failed to generate summary. Please check backend logs.');
    } finally {
        isGeneratingSummary.value = false;
    }
};

const refreshSummary = () => {
    openConfirm(
        "Regenerate Summary", 
        "Are you sure you want to regenerate the summary? This will use AI credits.", 
        generateSummary
    );
};

const updateStatus = async (newStatus) => {
    try {
        await detailApi.updateStatus(props.alertId, newStatus);
        alertData.value.status = newStatus;
    } catch (error) {
        console.error('Error updating status:', error);
    }
};

const fetchPrices = async (period) => {
    isLoadingPrices.value = true;
    try {
        prices.value = await detailApi.fetchPrices(alertData.value, period);
        prepareChartData();
    } catch (error) {
        console.error('Error fetching prices:', error);
    } finally {
        isLoadingPrices.value = false;
    }
};

const fetchNews = async (isin, startDate, endDate) => {
    try {
        news.value = await detailApi.fetchNews({
            isin,
            start_date: startDate,
            end_date: endDate
        });
    } catch (error) {
        console.error('Error fetching news:', error);
    }
};

const fetchConfig = async () => {
    try {
        config.value = await detailApi.fetchConfig();
    } catch (error) {
        console.error('Error fetching config:', error);
    }
};

const prepareChartData = () => {
    if (!prices.value.ticker || prices.value.ticker.length === 0) return;
    
    // Deduplicate ticker prices - keep last occurrence of each date
    const seenDates = new Map();
    prices.value.ticker.forEach(p => seenDates.set(p.date, p));
    const tickerPrices = Array.from(seenDates.values());
    
    const industryPrices = prices.value.industry;
    const labels = tickerPrices.map(p => p.date);
    
    // Prepare ticker data - actual close prices (not rebased)
    const tickerData = tickerPrices.map(p => Number(p.close));
    
    // Prepare volume data (for tooltip, not bars)
    const volumeData = tickerPrices.map(p => Number(p.volume || 0));
    
    // Prepare candlestick OHLC data - format: [open, close, low, high]
    const candlestickData = tickerPrices.map(p => [
        Number(p.open ?? p.close),
        Number(p.close),
        Number(p.low ?? Math.min(p.open || p.close, p.close)),
        Number(p.high ?? Math.max(p.open || p.close, p.close))
    ]);
    
    // Map for quick lookups
    const tickerMap = new Map();
    tickerPrices.forEach(p => tickerMap.set(p.date, Number(p.close)));

    // Prepare rebased ticker data (rebased to 100 for comparison with industry)
    const tickerStart = tickerPrices[0].close;
    const tickerRebasedData = tickerPrices.map(p => (p.close / tickerStart) * 100);

    // Prepare industry data - REBASED to 100 for comparison
    let industryData = [];
    let industryRebasedData = [];
    if (industryPrices && industryPrices.length > 0) {
        const indMap = new Map(industryPrices.map(p => [p.date, p.close]));
        const industryStart = industryPrices[0].close;

        industryData = labels.map(date => {
            const val = indMap.get(date);
            return val != null ? Number(val) : null;  // Actual price
        });
        
        industryRebasedData = labels.map(date => {
            const val = indMap.get(date);
            return val ? (Number(val) / Number(industryStart)) * 100 : null;  // Rebased to 100
        });
    }

    // Prepare bubble data for news events
    const bubbleData = [];
    
    if (news.value && news.value.length > 0) {
        // Helper: find closest label index for a given date
        const findClosestLabelIndex = (targetDate, labels) => {
            const exactIndex = labels.indexOf(targetDate);
            if (exactIndex >= 0) return exactIndex;
            for (let i = labels.length - 1; i >= 0; i--) {
                if (labels[i] <= targetDate) return i;
            }
            return labels.length > 0 ? 0 : -1;
        };

        // Materiality priority order
        const materialityOrder = [
            'HHH', 'HHM', 'HHL', 'HMH', 'HMM', 'HML', 'HLH', 'HLM', 'HLL',
            'MHH', 'MHM', 'MHL', 'MMH', 'MMM', 'MML', 'MLH', 'MLM', 'MLL',
            'LHH', 'LHM', 'LHL', 'LMH', 'LMM', 'LML', 'LLH', 'LLM', 'LLL'
        ];

        // Group articles by date and materiality
        const dateMatGroups = new Map();
        
        news.value.forEach(article => {
            const dateIndex = findClosestLabelIndex(article.created_date, labels);
            const matchedLabel = dateIndex >= 0 ? labels[dateIndex] : null;
            if (!matchedLabel) return;
            
            const mat = article.materiality || 'DEFAULT';
            
            if (!dateMatGroups.has(matchedLabel)) {
                dateMatGroups.set(matchedLabel, new Map());
            }
            const matMap = dateMatGroups.get(matchedLabel);
            
            // Store count AND article IDs
            if (!matMap.has(mat)) {
                matMap.set(mat, { count: 0, articleIds: [] });
            }
            const entry = matMap.get(mat);
            entry.count += 1;
            entry.articleIds.push(article.id || article.article_id || article.art_id);
        });

        // For each date, create bubbles: TOP 3 + "rest" with count
        dateMatGroups.forEach((matMap, dateLabel) => {
            const yBase = tickerMap.get(dateLabel);
            if (yBase === undefined) return;
            
            const sortedMats = Array.from(matMap.entries())
                .sort((a, b) => {
                    const idxA = materialityOrder.indexOf(a[0]);
                    const idxB = materialityOrder.indexOf(b[0]);
                    return (idxA === -1 ? 999 : idxA) - (idxB === -1 ? 999 : idxB);
                });
            
            // Take top 3
            const top3 = sortedMats.slice(0, 3);
            // Combine rest into one "Others" category
            const restMats = sortedMats.slice(3);
            const restCount = restMats.reduce((sum, [, { count }]) => sum + count, 0);
            const restArticleIds = restMats.flatMap(([, { articleIds }]) => articleIds);
            
            // Add top 3 bubbles (reversed for stacking order)
            top3.reverse().forEach((entry, stackIndex) => {
                const [mat, { count, articleIds }] = entry;
                const offset = stackIndex * 4;
                
                bubbleData.push({
                    value: [dateLabel, yBase + offset],
                    materiality: mat,
                    count: count,
                    articleIds: articleIds,
                    itemStyle: { color: getMaterialityColor(mat) }
                });
            });
            
            // Add "Others" bubble if there are more categories
            if (restCount > 0) {
                const offset = top3.length * 4;
                bubbleData.push({
                    value: [dateLabel, yBase + offset],
                    materiality: 'Others',
                    count: restCount,
                    articleIds: restArticleIds,
                    itemStyle: { color: getMaterialityColor('DEFAULT') }
                });
            }
        });
    }
    
    // Update reactive refs
    chartLabels.value = labels;
    tickerSeriesData.value = tickerData;
    tickerRebasedSeriesData.value = tickerRebasedData;
    industrySeriesData.value = industryData;
    industryRebasedSeriesData.value = industryRebasedData;
    volumeSeriesData.value = volumeData;
    bubbleSeriesData.value = bubbleData;
    candlestickSeriesData.value = candlestickData;
};

const uniqueThemes = computed(() => {
    if (!news.value) return ['All'];
    const themes = new Set(news.value.map(a => a.theme));
    return ['All', ...Array.from(themes)];
});

const filteredNews = computed(() => {
    let result = news.value;
    
    // 1. Filter by Theme
    if (activeTheme.value !== 'All') {
        result = result.filter(article => article.theme === activeTheme.value);
    }
    
    // 2. Sort by "Selected Bubble" if active
    if (selectedBubbleArticleIds.value && selectedBubbleArticleIds.value.length > 0) {
        // Partition articles into matches and others
        const matches = [];
        const others = [];
        
        const selectedIdsSet = new Set(selectedBubbleArticleIds.value.map(String));
        
        result.forEach(article => {
            const artId = String(article.id || article.article_id || article.art_id);
            if (selectedIdsSet.has(artId)) {
                matches.push(article);
            } else {
                others.push(article);
            }
        });
        
        // Return concatenated list: matches first
        return [...matches, ...others];
    }
    
    return result;
});

watch(selectedPeriod, async (newPeriod) => {
    if (alertData.value) await fetchPrices(newPeriod);
});

// Keep chart state combinations valid across toggle transitions.
watch(priceMode, (mode) => {
    if (mode === 'rebased') {
        viewMode.value = 'chart';
        chartType.value = 'line';
    }
});

watch([viewMode, chartType], ([nextViewMode, nextChartType]) => {
    if (priceMode.value === 'rebased' && (nextViewMode !== 'chart' || nextChartType !== 'line')) {
        priceMode.value = 'actual';
    }
});

watch(
    [activeTheme, selectedPeriod, viewMode, chartType, priceMode, summaryTab],
    () => {
        persistDetailUiState();
    }
);

onMounted(async () => {
    await fetchConfig();
    restoreDetailUiState(props.alertId);
    await loadData();
});

watch(() => props.alertId, async (newId) => {
    if (newId) {
        restoreDetailUiState(newId);
        alertData.value = null;
        await loadData();
    }
});

const priceMap = computed(() => {
    if (!prices.value.ticker) return new Map();
    const map = new Map();
    prices.value.ticker.forEach(p => {
        map.set(p.date, p);
    });
    return map;
});

// getPriceChange removed - using backend impact score instead

const activeMaterialityColumns = computed(() => {
    if (!news.value) return [];
    // Get all unique materiality codes present in the current news set
    const mats = new Set(news.value.map(a => a.materiality || 'DEFAULT'));
    // Sort them based on priority
    const order = [
        'HHH', 'HHM', 'HHL', 'HMH', 'HMM', 'HML', 'HLH', 'HLM', 'HLL',
        'MHH', 'MHM', 'MHL', 'MMH', 'MMM', 'MML', 'MLH', 'MLM', 'MLL',
        'LHH', 'LHM', 'LHL', 'LMH', 'LMM', 'LML', 'LLH', 'LLM', 'LLL'
    ];
    const sorted = Array.from(mats).sort((a, b) => {
        const idxA = order.indexOf(a);
        const idxB = order.indexOf(b);
        return (idxA === -1 ? 999 : idxA) - (idxB === -1 ? 999 : idxB);
    });
    // Return top 3 + 'Others' if more exist
    if (sorted.length > 3) {
        return [...sorted.slice(0, 3), 'Others'];
    }
    return sorted;
});

const tableData = computed(() => {
    if (!chartLabels.value.length) return [];

    return chartLabels.value.map((date, index) => {
        const hasTicker = tickerSeriesData.value[index] !== undefined;
        const hasIndustry = industrySeriesData.value[index] !== undefined;
        
        // Find Ticker Price (Close)
        const price = priceMap.value.get(date);
        
        // Get Article Counts for this date - top 3 + Others
        const counts = {};
        activeMaterialityColumns.value.forEach(mat => {
            counts[mat] = 0;
        });

        // Populate counts
        if (news.value) {
            // Get which materialities are "top 3" (not Others)
            const top3Mats = activeMaterialityColumns.value.filter(m => m !== 'Others');
            
            news.value.forEach(article => {
                // Approximate date matching (simple string match)
                const createdDate = typeof article.created_date === 'string' ? article.created_date : '';
                if (createdDate === date || createdDate.startsWith(date)) {
                    const mat = article.materiality || 'DEFAULT';
                    if (top3Mats.includes(mat)) {
                        counts[mat]++;
                    } else if (counts['Others'] !== undefined) {
                        counts['Others']++;
                    }
                }
            });
        }
        
        return {
            date,
            tickerClose: price?.close != null ? price.close.toFixed(2) : '-',
            tickerRebased: tickerSeriesData.value[index] != null ? tickerSeriesData.value[index].toFixed(2) : '-',
            industryRebased: industrySeriesData.value[index] != null ? industrySeriesData.value[index].toFixed(2) : '-',
            counts
        };
    }).reverse(); // Show newest first
});

const loadData = async () => {
    if (!props.alertId) return;
    try {
        const bundle = await detailApi.loadAlertBundle(props.alertId, selectedPeriod.value);
        if (!bundle) return;
        alertData.value = bundle.alert;
        prices.value = bundle.prices;
        news.value = bundle.news;
        if (activeTheme.value !== 'All' && !news.value.some((article) => article.theme === activeTheme.value)) {
            activeTheme.value = 'All';
        }
        prepareChartData();
    } catch (error) {
        console.error('Error loading alert bundle:', error);
    }
};

const captureCurrentChartImage = () => {
    const canvas = document.querySelector('.chart canvas');
    if (!canvas || typeof canvas.toDataURL !== 'function') {
        return null;
    }
    try {
        return canvas.toDataURL('image/png');
    } catch (e) {
        console.error('Failed to capture chart image:', e);
        return null;
    }
};

onMounted(() => {
    window.__tsPitCaptureAlertChart = captureCurrentChartImage;
});

onBeforeUnmount(() => {
    if (window.__tsPitCaptureAlertChart === captureCurrentChartImage) {
        delete window.__tsPitCaptureAlertChart;
    }
});

</script>


<template>
    <div class="detail-container" v-if="alertData">
        <AlertHeader 
            :alertData="alertData" 
            :alertId="alertId" 
            :newsCount="news ? news.length : 0"
            :validStatuses="config?.valid_statuses || []"
            @update-status="updateStatus"
            @toggle-agent="emit('toggle-agent')"
        />
        
        <div class="dashboard-grid">
            <AlertChart 
                class="layout-chart"
                :chartLabels="chartLabels"
                :chartOptions="chartOptions"
                v-model:viewMode="viewMode"
                v-model:chartType="chartType"
                v-model:priceMode="priceMode"
                v-model:selectedPeriod="selectedPeriod"
                :isLoading="isLoadingPrices"
                :tableData="tableData"
                :activeMaterialityColumns="activeMaterialityColumns"
                :config="config"
                @bubble-click="handleChartClick"
            />
            
            <AlertNews 
                class="layout-news"
                :news="filteredNews"
                :themes="uniqueThemes"
                v-model:activeTheme="activeTheme"
                :config="config"
                @hover-materiality="handleTooltipEnter"
                @leave-materiality="handleTooltipLeave"
            >
                <template #summary>
                    <AlertSummary 
                        :alertData="alertData"
                        :isGeneratingSummary="isGeneratingSummary"
                        @refresh="refreshSummary"
                        @analyze="analyzeArticles"
                    />
                </template>
            </AlertNews>
        </div>
    </div>
    <div v-else class="loading-screen"><div class="spinner"></div> Generating Dashboard...</div>

    <ConfirmDialog 
        :is-open="showConfirmDialog"
        :title="confirmTitle"
        :message="confirmMessage"
        confirm-text="Proceed"
        @confirm="handleConfirm"
        @cancel="handleCancel"
    />

  <!-- Global Tooltip Element -->
  <div v-if="showTooltip && tooltipData" 
       class="details-tooltip"
       :style="{ top: tooltipPos.y + 'px', left: tooltipPos.x + 'px' }"
  >
        <div class="tip-row"><strong>P1 (Entity):</strong> {{ tooltipData.p1.score }} - {{ tooltipData.p1.reason }}</div>
        <div class="tip-row"><strong>P2 (Time):</strong> {{ tooltipData.p2.score }} - {{ tooltipData.p2.reason }}</div>
        <div class="tip-row"><strong>P3 (Theme):</strong> {{ tooltipData.p3.score }} - {{ tooltipData.p3.reason }}</div>
  </div>
</template>

<style scoped>
/* Original styles below */
.detail-container { 
    background-color: #f8fafc; 
    height: 100%; 
    width: 100%; 
    display: flex; 
    flex-direction: column; 
    overflow: hidden; /* Main container fixed */
    font-family: var(--font-family-ui);
    container-type: inline-size; /* Enable Container Query */
    container-name: details;
}

/* Default: Side-by-Side (Full Height) */
.dashboard-grid { 
    flex: 1; 
    display: flex; 
    flex-direction: row; /* Force row by default */
    padding: 1.5rem 2rem; 
    gap: 1.5rem; 
    height: 100%; 
    min-height: 0; 
    box-sizing: border-box; 
    width: 100%; 
    overflow: hidden; /* Internal panels scroll */
}

/* Items fill height in side-by-side */
.layout-chart {
    flex: 2;
    min-width: 0; 
    height: 100%;
}

.layout-news {
    flex: 1;
    min-width: 0;
    height: 100%;
}

/* Stacked Layout via Container Query */
@container details (max-width: 1100px) {
    .dashboard-grid {
        flex-direction: column;
        height: auto;
        overflow-y: auto; /* Grid scrolls when stacked */
    }
    
    .layout-chart, .layout-news {
        flex: none;
        width: 100%;
        height: auto;
        min-height: 500px;
    }
}

/* Global Tooltip Styles */
.details-tooltip {
    position: fixed;
    z-index: 9999;
    background-color: #1e293b;
    color: #fff;
    width: 280px;
    padding: 12px;
    border-radius: 6px;
    font-size: 0.75rem;
    box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
    pointer-events: none; /* Allow clicking through if needed */
    line-height: 1.4;
}

.tip-row {
    margin-bottom: 4px;
    border-bottom: 1px solid #334155;
    padding-bottom: 4px;
}
.tip-row:last-child {
    margin-bottom: 0;
    border-bottom: none;
    padding-bottom: 0;
}

.loading-screen { display: flex; align-items: center; justify-content: center; height: 100%; color: #64748b; font-weight: 500; gap: 10px; }
.spinner { width: 20px; height: 20px; border: 3px solid #e2e8f0; border-top-color: #3b82f6; border-radius: 50%; animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }


</style>

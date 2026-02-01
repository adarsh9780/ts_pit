<script setup>
import { ref, onMounted, computed, watch, shallowRef } from 'vue';
import axios from 'axios';
import VChart from 'vue-echarts';
import { use } from 'echarts/core';
import { CanvasRenderer } from 'echarts/renderers';
import { LineChart, ScatterChart, BarChart } from 'echarts/charts';
import { GridComponent, TooltipComponent, LegendComponent, MarkAreaComponent } from 'echarts/components';

// Register ECharts components
use([CanvasRenderer, LineChart, ScatterChart, BarChart, GridComponent, TooltipComponent, LegendComponent, MarkAreaComponent]);

const props = defineProps({
  alertId: {
    type: [String, Number],
    required: true
  }
});

const alertData = ref(null);
const prices = ref({ ticker: [], industry: [], industry_name: '' });
const news = ref([]);
const activeTheme = ref('All');
const selectedPeriod = ref('1mo');
const isLoadingPrices = ref(false);
const config = ref(null);
const viewMode = ref('chart');
const isGeneratingSummary = ref(false);

// Chart refs
const chartRef = shallowRef(null);
const chartLabels = ref([]);
const tickerSeriesData = ref([]);
const industrySeriesData = ref([]);
const volumeSeriesData = ref([]);
const bubbleSeriesData = ref([]);

const periods = [
    { label: '1M', value: '1mo' },
    { label: '3M', value: '3mo' },
    { label: '6M', value: '6mo' },
    { label: '1Y', value: '1y' },
    { label: 'YTD', value: 'ytd' },
    { label: 'Max', value: 'max' },
];

// Materiality color scale
const getMaterialityColor = (code) => {
    if (!config.value || !config.value.materiality_colors) return '#808080';
    return config.value.materiality_colors[code] || config.value.materiality_colors['DEFAULT'] || '#808080';
};

const chartOptions = computed(() => {
    if (!chartLabels.value.length) return {};
    
    // Calculate mark area for period highlighting
    // Calculate mark area for period highlighting
    let markAreaData = [];
    if (alertData.value && chartLabels.value.length > 0) {
        let targetStart = alertData.value.start_date;
        let targetEnd = alertData.value.end_date;
        
        // Helper to find closest available date in chartLabels
        const findClosestDate = (target, labels) => {
            if (labels.includes(target)) return target;
            // Find closest (assuming sorted labels)
            // Simple approach: find first label >= target (start) or last label <= target (end)
            // For visualization, finding the closest sorted string is usually 'good enough' for dates YYYY-MM-DD
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

        markAreaData = [[
            { xAxis: targetStart },
            { xAxis: targetEnd }
        ]];
    }
    
    const series = [
        {
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
            }
        },
        {
            name: `${prices.value.industry_name || 'Industry'} Index`,
            type: 'line',
            data: industrySeriesData.value,
            smooth: false,
            yAxisIndex: 1,
            symbol: 'none',
            lineStyle: { color: '#94a3b8', width: 2, type: 'dashed' },
            itemStyle: { color: '#94a3b8' },
            emphasis: { focus: 'series' }
        }

    ];
    
    // Add scatter series for bubbles if we have data
    if (bubbleSeriesData.value.length > 0) {
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
                splitLine: { lineStyle: { color: '#f0f0f0' } }
            },
            {
                type: 'value',
                name: 'Industry',
                position: 'right',
                axisLine: { show: false },
                axisTick: { show: false },
                axisLabel: { 
                    color: '#94a3b8', 
                    fontSize: 10
                },
                splitLine: { show: false }
            }
        ],
        series
    };
});

const fetchAlertDetail = async () => {
    if (!props.alertId) return;
    try {
        const response = await axios.get(`http://localhost:8000/alerts/${props.alertId}`);
        alertData.value = response.data;
        return response.data;
    } catch (error) {
        console.error('Error fetching alert detail:', error);
    }
};

const generateSummary = async () => {
    isGeneratingSummary.value = true;
    try {
        const response = await axios.post(`http://localhost:8000/alerts/${props.alertId}/summary`);
        // Update local state with new summary data
        if (alertData.value) {
            alertData.value.narrative_theme = response.data.narrative_theme;
            alertData.value.narrative_summary = response.data.narrative_summary;
            alertData.value.summary_generated_at = response.data.summary_generated_at;
        }
    } catch (error) {
        console.error('Error generating summary:', error);
        alert('Failed to generate summary. Please check backend logs.');
    } finally {
        isGeneratingSummary.value = false;
    }
};

const refreshSummary = () => {
    if (confirm("Are you sure you want to regenerate the summary? This will use AI credits.")) {
        generateSummary();
    }
};

const updateStatus = async (newStatus) => {
    try {
        await axios.patch(`http://localhost:8000/alerts/${props.alertId}/status`, { status: newStatus });
        alertData.value.status = newStatus;
    } catch (error) {
        console.error('Error updating status:', error);
    }
};

const getStatusClass = (status) => {
    const classes = { 'Pending': 'status-pending', 'Approved': 'status-approved', 'Rejected': 'status-rejected' };
    return classes[status] || '';
};

const fetchPrices = async (ticker, period) => {
    isLoadingPrices.value = true;
    try {
        const response = await axios.get(`http://localhost:8000/prices/${ticker}`, { params: { period } });
        prices.value = response.data;
        prepareChartData();
    } catch (error) {
        console.error('Error fetching prices:', error);
    } finally {
        isLoadingPrices.value = false;
    }
};

const fetchNews = async (isin, startDate, endDate) => {
    try {
        const response = await axios.get(`http://localhost:8000/news/${isin}`, {
            params: { start_date: startDate, end_date: endDate }
        });
        news.value = response.data;
    } catch (error) {
        console.error('Error fetching news:', error);
    }
};

const fetchConfig = async () => {
    try {
        const response = await axios.get('http://localhost:8000/config');
        config.value = response.data;
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
    const tickerData = tickerPrices.map(p => p.close);
    
    // Prepare volume data (for tooltip, not bars)
    const volumeData = tickerPrices.map(p => p.volume || 0);
    
    // Map for quick lookups
    const tickerMap = new Map();
    tickerPrices.forEach(p => tickerMap.set(p.date, p.close));

    // Prepare industry data - actual close prices on secondary y-axis
    let industryData = [];
    if (industryPrices && industryPrices.length > 0) {
        const indMap = new Map(industryPrices.map(p => [p.date, p.close]));

        industryData = labels.map(date => {
            const val = indMap.get(date);
            return val ?? null;  // Actual price, not rebased
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
            matMap.set(mat, (matMap.get(mat) || 0) + 1);
        });

        // For each date, create bubbles sorted by materiality
        dateMatGroups.forEach((matMap, dateLabel) => {
            const yBase = tickerMap.get(dateLabel);
            if (yBase === undefined) return;
            
            const sortedMats = Array.from(matMap.entries())
                .sort((a, b) => {
                    const idxA = materialityOrder.indexOf(a[0]);
                    const idxB = materialityOrder.indexOf(b[0]);
                    return (idxA === -1 ? 999 : idxA) - (idxB === -1 ? 999 : idxB);
                });
            
            sortedMats.reverse().forEach((entry, stackIndex) => {
                const [mat, count] = entry;
                const offset = stackIndex * 4;
                
                bubbleData.push({
                    value: [dateLabel, yBase + offset],
                    materiality: mat,
                    count: count,
                    itemStyle: { color: getMaterialityColor(mat) }
                });
            });
        });
    }
    
    // Update reactive refs
    chartLabels.value = labels;
    tickerSeriesData.value = tickerData;
    industrySeriesData.value = industryData;
    volumeSeriesData.value = volumeData;
    bubbleSeriesData.value = bubbleData;
};

const uniqueThemes = computed(() => {
    if (!news.value) return ['All'];
    const themes = new Set(news.value.map(a => a.theme));
    return ['All', ...Array.from(themes)];
});

const filteredNews = computed(() => {
    if (activeTheme.value === 'All') return news.value;
    return news.value.filter(article => article.theme === activeTheme.value);
});

watch(selectedPeriod, async (newPeriod) => {
    if (alertData.value) await fetchPrices(alertData.value.ticker, newPeriod);
});

onMounted(async () => {
    await fetchConfig();
    await loadData();
});

watch(() => props.alertId, async (newId) => {
    if (newId) {
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

const getPriceChange = (date) => {
    const price = priceMap.value.get(date);
    if (!price || price.open == null || price.close == null) return null;
    // Calculate intraday change: (Close - Open) / Open
    const change = ((price.close - price.open) / price.open) * 100;
    return {
        value: change.toFixed(2),
        isPositive: change >= 0,
        open: price.open.toFixed(2),
        close: price.close.toFixed(2),
        diff: Math.abs(price.close - price.open).toFixed(2)
    };
};

const activeMaterialityColumns = computed(() => {
    if (!news.value) return [];
    // Get all unique materiality codes present in the current news set
    const mats = new Set(news.value.map(a => a.materiality || 'DEFAULT'));
    // Sort them based on some priority if needed, or just alphabetically
    const order = [
        'HHH', 'HHM', 'HHL', 'HMH', 'HMM', 'HML', 'HLH', 'HLM', 'HLL',
        'MHH', 'MHM', 'MHL', 'MMH', 'MMM', 'MML', 'MLH', 'MLM', 'MLL',
        'LHH', 'LHM', 'LHL', 'LMH', 'LMM', 'LML', 'LLH', 'LLM', 'LLL'
    ];
    return Array.from(mats).sort((a, b) => {
        const idxA = order.indexOf(a);
        const idxB = order.indexOf(b);
        return (idxA === -1 ? 999 : idxA) - (idxB === -1 ? 999 : idxB);
    });
});

const tableData = computed(() => {
    if (!chartLabels.value.length) return [];

    return chartLabels.value.map((date, index) => {
        const hasTicker = tickerSeriesData.value[index] !== undefined;
        const hasIndustry = industrySeriesData.value[index] !== undefined;
        
        // Find Ticker Price (Close)
        const price = priceMap.value.get(date);
        
        // Get Article Counts for this date
        const counts = {};
        activeMaterialityColumns.value.forEach(mat => {
            counts[mat] = 0;
        });

        // Populate counts
        if (news.value) {
            news.value.forEach(article => {
                // Approximate date matching (simple string match)
                if (article.created_date === date || article.created_date.startsWith(date)) {
                    const mat = article.materiality || 'DEFAULT';
                    if (counts[mat] !== undefined) counts[mat]++;
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
    const alert = await fetchAlertDetail();
    if (alert) {
        await fetchPrices(alert.ticker, selectedPeriod.value);
        await fetchNews(alert.isin, alert.start_date, alert.end_date);
        prepareChartData();
    }
};
</script>

<template>
    <div class="detail-container" v-if="alertData">
        <header class="header">
            <div class="header-content">
                <div class="header-main">
                    <div class="header-left">
                        <h1>{{ alertData.ticker }} <span class="subtitle">{{ alertData.instrument_name }}</span></h1>
                        <div class="meta-tags">
                           <span class="tag isin">{{ alertData.isin }}</span>
                           <span class="tag type" :class="alertData.trade_type.toLowerCase()">{{ alertData.trade_type }}</span>
                           <span class="status-badge" :class="getStatusClass(alertData.status)">{{ alertData.status }}</span>
                           <!-- Cluster Theme Badge -->
                           <span v-if="alertData.narrative_theme" class="tag theme-badge" title="AI Generated Theme">
                               {{ alertData.narrative_theme }}
                           </span>
                        </div>
                        <div class="alert-metrics">
                            <span class="metric-item"><strong>Alert Date:</strong> {{ alertData.alert_date }}</span>
                            <span class="separator">•</span>
                            <span class="metric-item"><strong>Start:</strong> {{ alertData.start_date }}</span>
                            <span class="separator">•</span>
                            <span class="metric-item"><strong>End:</strong> {{ alertData.end_date }}</span>
                            <span class="separator">•</span>
                            <span class="metric-item"><strong>Articles:</strong> {{ news ? news.length : 0 }}</span>
                        </div>
                    </div>
                    <div class="header-actions">
                        <button class="action-btn approve-btn" @click="updateStatus('Approved')" :disabled="alertData.status === 'Approved'">✓ Approve for L2</button>
                        <button class="action-btn reject-btn" @click="updateStatus('Rejected')" :disabled="alertData.status === 'Rejected'">✗ Reject</button>
                    </div>
                </div>
            </div>
        </header>
        
        <div class="dashboard-grid">
            <div class="card chart-panel">
                <div class="card-header chart-header">
                    <h3>Price Performance</h3>
                    <div class="header-controls">
                        <div class="view-toggle">
                            <button :class="{ active: viewMode === 'chart' }" @click="viewMode = 'chart'">Chart</button>
                            <button :class="{ active: viewMode === 'table' }" @click="viewMode = 'table'">Table</button>
                        </div>
                        <div class="period-selector">
                            <button v-for="period in periods" :key="period.value" :class="{ active: selectedPeriod === period.value }" @click="selectedPeriod = period.value">{{ period.label }}</button>
                        </div>
                    </div>
                </div>
                <div class="card-body chart-wrapper">
                    <div v-if="isLoadingPrices" class="loading-overlay"><div class="spinner"></div></div>
                    
                    <template v-if="!isLoadingPrices">
                        <v-chart v-if="viewMode === 'chart' && chartLabels.length" ref="chartRef" class="chart" :option="chartOptions" autoresize />
                        
                        <div v-else-if="viewMode === 'table' && chartLabels.length" class="table-container">
                            <table class="data-table">
                                <thead>
                                    <tr>
                                        <th>Date</th>
                                        <th>Close</th>
                                        <th>Rebased</th>
                                        <th>Ind. Rebased</th>
                                        <th v-for="mat in activeMaterialityColumns" :key="mat" :style="{ color: getMaterialityColor(mat) }">{{ mat }}</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    <tr v-for="row in tableData" :key="row.date">
                                        <td>{{ row.date }}</td>
                                        <td>{{ row.tickerClose }}</td>
                                        <td>{{ row.tickerRebased }}</td>
                                        <td>{{ row.industryRebased }}</td>
                                        <td v-for="mat in activeMaterialityColumns" :key="mat" class="count-cell">
                                            <span v-if="row.counts[mat] > 0" class="count-badge" :style="{ backgroundColor: getMaterialityColor(mat) }">
                                                {{ row.counts[mat] }}
                                            </span>
                                            <span v-else class="empty-cell">-</span>
                                        </td>
                                    </tr>
                                </tbody>
                            </table>
                        </div>
                        
                        <div v-else class="loading-state">No price data available.</div>
                    </template>
                </div>
            </div>
            
            <div class="card news-panel">
                <div class="card-header news-header">
                    <h3>Relevant News</h3>
                    <div class="theme-selector">
                         <select v-model="activeTheme" class="theme-dropdown">
                            <option v-for="theme in uniqueThemes" :key="theme" :value="theme">{{ theme.replace(/_/g, ' ') }}</option>
                        </select>
                    </div>
                </div>
                <div class="card-body scrollable">
                    
                    <!-- Executive Summary Card -->
                    <div class="executive-summary-wrapper">
                        <div v-if="alertData.narrative_summary" class="executive-summary">
                            <div class="summary-header">
                                <h4><span class="ai-icon">AI</span> Investigation Summary</h4>
                                <button class="refresh-btn" @click="refreshSummary" :disabled="isGeneratingSummary" title="Regenerate Summary">
                                    {{ isGeneratingSummary ? '...' : '↻' }}
                                </button>
                            </div>
                            <p>{{ alertData.narrative_summary }}</p>
                            <span class="summary-meta">Generated: {{ new Date(alertData.summary_generated_at).toLocaleString() }}</span>
                        </div>
                        
                        <div v-else class="summary-placeholder">
                             <button class="generate-btn" @click="generateSummary" :disabled="isGeneratingSummary">
                                <span v-if="isGeneratingSummary" class="spinner-sm"></span>
                                <span v-else>Generate AI Summary</span>
                            </button>
                        </div>
                    </div>

                    <div v-if="filteredNews.length > 0" class="news-feed">
                        <div v-for="article in filteredNews" :key="article.art_id" class="news-item">
                            <div class="news-meta">
                                <span class="news-date">{{ article.created_date }}</span>
                                <span class="news-theme">{{ article.theme.replace(/_/g, ' ') }}</span>
                            </div>
                            <h4 class="news-title">{{ article.title }}</h4>
                            <p v-if="article.summary" class="news-summary">{{ article.summary }}</p>
                            <div class="news-footer">
                                <span class="sentiment-indicator" :class="article.sentiment.split(':')[0].toLowerCase()">{{ article.sentiment.split(':')[0] }}</span>
                                <template v-if="config && config.has_materiality && article.materiality">
                                    <span class="separator">•</span>
                                    <span class="materiality-indicator" :style="{ color: getMaterialityColor(article.materiality) }">{{ article.materiality }}</span>
                                </template>
                                
                                <template v-if="getPriceChange(article.created_date)">
                                    <span class="separator">•</span>
                                    <span class="price-change" 
                                          :class="getPriceChange(article.created_date).isPositive ? 'positive' : 'negative'"
                                          :title="`Open: ${getPriceChange(article.created_date).open} | Close: ${getPriceChange(article.created_date).close} | Diff: ${getPriceChange(article.created_date).diff}`">
                                        {{ getPriceChange(article.created_date).isPositive ? '+' : '' }}{{ getPriceChange(article.created_date).value }}%
                                    </span>
                                </template>
                            </div>
                        </div>
                    </div>
                     <div v-else class="empty-state">No news found for this specific theme.</div>
                </div>
            </div>
        </div>
    </div>
    <div v-else class="loading-screen"><div class="spinner"></div> Generating Dashboard...</div>
</template>

<style scoped>
.detail-container { background-color: #f8fafc; height: 100%; width: 100%; display: flex; flex-direction: column; overflow-y: auto; font-family: 'Inter', sans-serif; }
.header { background: white; border-bottom: 1px solid #e2e8f0; padding: 1rem 2rem; box-shadow: 0 1px 2px rgba(0,0,0,0.05); flex-shrink: 0; }
.header-main { display: flex; justify-content: space-between; align-items: flex-start; margin-top: 0.5rem; }
.header-left { flex: 1; }
.header-actions { display: flex; gap: 0.75rem; }
.action-btn { padding: 0.5rem 1rem; border: none; border-radius: 0.5rem; font-size: 0.875rem; font-weight: 600; cursor: pointer; transition: all 0.2s; }
.action-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.approve-btn { background: #dcfce7; color: #166534; }
.approve-btn:hover:not(:disabled) { background: #bbf7d0; }
.reject-btn { background: #fee2e2; color: #991b1b; }
.reject-btn:hover:not(:disabled) { background: #fecaca; }
h1 { margin: 0; font-size: 1.5rem; color: #0f172a; display: flex; align-items: baseline; gap: 0.75rem; }
.subtitle { font-size: 1rem; color: #64748b; font-weight: 400; }
.meta-tags { margin-top: 0.75rem; display: flex; gap: 0.5rem; align-items: center; }
.tag { padding: 0.25rem 0.75rem; border-radius: 9999px; font-size: 0.75rem; font-weight: 600; }
.tag.isin { background-color: #f1f5f9; color: #475569; }
.tag.type { text-transform: uppercase; }
.tag.type.buy { background-color: #dcfce7; color: #166534; }
.tag.type.sell { background-color: #fee2e2; color: #991b1b; }
.status-badge { padding: 0.25rem 0.75rem; border-radius: 0.375rem; font-size: 0.75rem; font-weight: 600; }
.status-pending { background-color: #fef3c7; color: #92400e; }
.status-approved { background-color: #dcfce7; color: #166534; }
.status-rejected { background-color: #fee2e2; color: #991b1b; }
.alert-metrics { margin-top: 12px; font-size: 0.9em; color: #4b5563; display: flex; align-items: center; gap: 8px; }
.metric-item strong { font-weight: 600; color: #1f2937; }
.separator { color: #9ca3af; }
.dashboard-grid { flex: 1; display: flex; flex-direction: row; padding: 1.5rem 2rem; gap: 1.5rem; height: 100%; min-height: 0; box-sizing: border-box; width: 100%; }
.card { background: white; border-radius: 0.75rem; border: 1px solid #e2e8f0; box-shadow: 0 1px 3px rgba(0,0,0,0.05); display: flex; flex-direction: column; overflow: hidden; }
.card-header { padding: 1rem 1.5rem; border-bottom: 1px solid #f1f5f9; background: #ffffff; flex-shrink: 0; }
.chart-header, .news-header { display: flex; justify-content: space-between; align-items: center; }
.period-selector { display: flex; gap: 0.5rem; background: #f1f5f9; padding: 0.25rem; border-radius: 6px; }
.period-selector button { border: none; background: transparent; padding: 0.25rem 0.5rem; font-size: 0.75rem; color: #64748b; border-radius: 4px; cursor: pointer; font-weight: 500; }
.period-selector button:hover { color: #334155; background: rgba(255,255,255,0.5); }
.period-selector button.active { background: white; color: #3b82f6; box-shadow: 0 1px 2px rgba(0,0,0,0.05); font-weight: 600; }
.loading-overlay { position: absolute; top: 0; left: 0; right: 0; bottom: 0; background: rgba(255,255,255,0.7); display: flex; align-items: center; justify-content: center; z-index: 10; }
.theme-dropdown { padding: 0.25rem 0.5rem; border: 1px solid #cbd5e1; border-radius: 0.375rem; font-size: 0.875rem; color: #334155; background-color: white; }
.card-header h3 { margin: 0; font-size: 1rem; font-weight: 600; color: #334155; }
.card-body { flex: 1; position: relative; min-height: 0; }
.chart-panel { flex: 2; min-width: 0; height: 100%; }
.chart-wrapper { height: 100%; width: 100%; }
.chart { width: 100%; height: 100%; min-height: 400px; }
.news-panel { flex: 1; min-width: 450px; display: flex; flex-direction: column; height: 100%; }
.scrollable { overflow-y: auto; padding: 0; height: 100%; }
.news-feed { padding: 1.5rem; }
.news-item { margin-bottom: 1.25rem; padding: 1rem; background: #f8fafc; border-radius: 0.5rem; border: 1px solid #e2e8f0; transition: all 0.2s ease; }
.news-item:hover { border-color: #cbd5e1; box-shadow: 0 2px 4px rgba(0,0,0,0.04); }
.news-item:last-child { margin-bottom: 0; }
.news-meta { display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem; font-size: 0.75rem; }
.news-date { color: #64748b; font-weight: 500; }
.news-theme { color: #6366f1; font-weight: 600; background: #eef2ff; padding: 0 0.5rem; border-radius: 4px; font-size: 0.7rem; }
.news-title { margin: 0 0 0.5rem 0; font-size: 1rem; color: #1e293b; line-height: 1.4; }
.news-summary { font-size: 0.875rem; color: #475569; line-height: 1.5; margin-bottom: 0.75rem; }
.sentiment-indicator { font-size: 0.75rem; font-weight: 600; }
.sentiment-indicator.bullish { color: #16a34a; }
.sentiment-indicator.bearish { color: #dc2626; }
.sentiment-indicator { font-size: 0.75rem; font-weight: 600; }
.sentiment-indicator.bullish { color: #16a34a; }
.sentiment-indicator.bearish { color: #dc2626; }
.sentiment-indicator.neutral { color: #64748b; }
.separator { margin: 0 0.5rem; color: #cbd5e1; }
.materiality-indicator { font-size: 0.75rem; font-weight: 600; color: #475569; }
.price-change { font-size: 0.75rem; font-weight: 600; }
.price-change.positive { color: #16a34a; }
.price-change.negative { color: #dc2626; }
.loading-screen, .loading-state { display: flex; align-items: center; justify-content: center; height: 100%; color: #64748b; font-weight: 500; gap: 10px; }
.spinner { width: 20px; height: 20px; border: 3px solid #e2e8f0; border-top-color: #3b82f6; border-radius: 50%; animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.empty-state { padding: 2rem; text-align: center; color: #94a3b8; font-style: italic; display: flex; align-items: center; justify-content: center; height: 100%; }

.header-controls { display: flex; gap: 1rem; align-items: center; }
.view-toggle { display: flex; background: #f1f5f9; padding: 2px; border-radius: 6px; }
.view-toggle button { border: none; background: transparent; padding: 4px 12px; font-size: 0.75rem; color: #64748b; border-radius: 4px; cursor: pointer; font-weight: 500; }
.view-toggle button:hover { color: #334155; }
.view-toggle button.active { background: white; color: #3b82f6; box-shadow: 0 1px 2px rgba(0,0,0,0.05); font-weight: 600; }

.table-container { height: 100%; overflow: auto; padding: 0; }
.data-table { width: 100%; border-collapse: collapse; font-size: 0.8rem; text-align: right; }
.data-table th, .data-table td { padding: 8px 12px; border-bottom: 1px solid #f1f5f9; white-space: nowrap; }
.data-table th { position: sticky; top: 0; background: #fff; font-weight: 600; color: #64748b; text-align: right; z-index: 1; }
.data-table th:first-child, .data-table td:first-child { text-align: left; }
.data-table tbody tr:hover { background-color: #f8fafc; }
.count-cell { text-align: center !important; }
.data-table th.count-header { text-align: center !important; } /* Need to adjust th above if matching */
.count-badge { color: white; border-radius: 12px; padding: 2px 8px; font-size: 0.7rem; font-weight: bold; min-width: 20px; display: inline-block; }
.empty-cell { color: #cbd5e1; }

/* AI Summary Styles */
.theme-badge {
    background-color: #f3e8ff;
    color: #7e22ce;
    border: 1px solid #d8b4fe;
    display: inline-flex;
    align-items: center;
    gap: 4px;
}

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

</style>

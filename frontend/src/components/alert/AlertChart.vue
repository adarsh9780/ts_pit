<script setup>
import { computed, ref } from 'vue';
import VChart from 'vue-echarts';

// Define Props
const props = defineProps({
  chartLabels: { type: Array, default: () => [] },
  chartOptions: { type: Object, default: () => ({}) },
  viewMode: { type: String, default: 'chart' },
  chartType: { type: String, default: 'line' },
  priceMode: { type: String, default: 'actual' },
  selectedPeriod: { type: String, default: 'alert' },
  isLoading: { type: Boolean, default: false },
  tableData: { type: Array, default: () => [] },
  activeMaterialityColumns: { type: Array, default: () => [] },
  config: { type: Object, default: () => ({}) }
});

// Define Emits for bidirectional binding
const emit = defineEmits([
    'update:viewMode', 
    'update:chartType', 
    'update:priceMode', 
    'update:selectedPeriod'
]);

// Helper for materiality colors
const getMaterialityColor = (code) => {
    if (!props.config || !props.config.materiality_colors) return '#808080';
    return props.config.materiality_colors[code] || props.config.materiality_colors['DEFAULT'] || '#808080';
};

const periods = [
    { label: 'Alert', value: 'alert' },
    { label: '1M', value: '1mo' },
    { label: '3M', value: '3mo' },
    { label: '6M', value: '6mo' },
    { label: '1Y', value: '1y' },
    { label: 'YTD', value: 'ytd' },
    { label: 'Max', value: 'max' },
];

const isRebasedDisabled = computed(() => props.viewMode !== 'chart' || props.chartType !== 'line');
</script>

<template>
    <div class="card chart-panel">
        <div class="card-header chart-header">
            <h3>Price Performance</h3>
            <div class="header-controls">
                <div class="view-toggle chart-mode-toggle">
                    <button 
                        :class="{ active: viewMode === 'chart' && chartType === 'line' }" 
                        @click="emit('update:viewMode', 'chart'); emit('update:chartType', 'line')"
                    >Line</button>
                    <button 
                        :class="{ active: viewMode === 'chart' && chartType === 'candle' }" 
                        @click="emit('update:viewMode', 'chart'); emit('update:chartType', 'candle'); emit('update:priceMode', 'actual')"
                    >Candle</button>
                    <button 
                        :class="{ active: viewMode === 'table' }" 
                        @click="emit('update:viewMode', 'table'); emit('update:priceMode', 'actual')"
                    >Table</button>
                </div>
                <div class="view-toggle price-mode-toggle">
                    <button 
                        :class="{ active: priceMode === 'actual' }" 
                        @click="emit('update:priceMode', 'actual')"
                    >Actual</button>
                    <button 
                        :class="{ active: priceMode === 'rebased', disabled: isRebasedDisabled }"
                        :disabled="isRebasedDisabled"
                        @click="!isRebasedDisabled && emit('update:priceMode', 'rebased')"
                    >Rebased</button>
                </div>
                <div class="period-selector">
                    <button 
                        v-for="period in periods" 
                        :key="period.value" 
                        :class="{ active: selectedPeriod === period.value }" 
                        @click="emit('update:selectedPeriod', period.value)"
                    >{{ period.label }}</button>
                </div>
            </div>
        </div>
        <div class="card-body chart-wrapper">
            <div v-if="isLoading" class="loading-overlay"><div class="spinner"></div></div>
            
            <template v-if="!isLoading">
                <v-chart
                    v-if="viewMode === 'chart' && chartLabels.length"
                    :key="`${chartType}-${priceMode}-${selectedPeriod}`"
                    class="chart"
                    :option="chartOptions"
                    autoresize
                />
                
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
</template>

<style scoped>
.card { background: white; border-radius: 0.75rem; border: 1px solid #e2e8f0; box-shadow: 0 1px 3px rgba(0,0,0,0.05); display: flex; flex-direction: column; }
.card-header { padding: 1rem 1.5rem; border-bottom: 1px solid #f1f5f9; background: #ffffff; flex-shrink: 0; position: relative; z-index: 2; }
.chart-header { 
    display: flex; 
    justify-content: space-between; 
    align-items: center; 
    flex-wrap: wrap; 
    gap: 1rem; 
}
.card-header h3 { margin: 0; font-size: 1rem; font-weight: 600; color: #334155; white-space: nowrap; }

.header-controls { 
    display: flex; 
    gap: 0.5rem; 
    align-items: center; 
    flex-wrap: wrap; 
    justify-content: flex-end;
}
.view-toggle { display: flex; background: #f1f5f9; padding: 2px; border-radius: 6px; white-space: nowrap; }
.view-toggle button { border: none; background: transparent; padding: 4px 10px; font-size: 0.75rem; color: #64748b; border-radius: 4px; cursor: pointer; font-weight: 500; }
.view-toggle button:hover { color: #334155; }
.view-toggle button.active { background: white; color: #3b82f6; box-shadow: 0 1px 2px rgba(0,0,0,0.05); font-weight: 600; }
.view-toggle button.disabled { opacity: 0.5; cursor: not-allowed; }

.period-selector { display: flex; gap: 0.25rem; background: #f1f5f9; padding: 0.25rem; border-radius: 6px; white-space: nowrap; overflow-x: auto; max-width: 100%; }
.period-selector button { border: none; background: transparent; padding: 0.25rem 0.5rem; font-size: 0.75rem; color: #64748b; border-radius: 4px; cursor: pointer; font-weight: 500; }
.period-selector button:hover { color: #334155; background: rgba(255,255,255,0.5); }
.period-selector button.active { background: white; color: #3b82f6; box-shadow: 0 1px 2px rgba(0,0,0,0.05); font-weight: 600; }

.card-body { flex: 1; position: relative; min-height: 0; z-index: 1; }
.chart-panel { flex: 2; min-width: 0; height: 100%; }
.chart-wrapper { height: 100%; width: 100%; }
.chart { width: 100%; height: 100%; min-height: 400px; }

.loading-overlay { position: absolute; top: 0; left: 0; right: 0; bottom: 0; background: rgba(255,255,255,0.7); display: flex; align-items: center; justify-content: center; z-index: 10; }
.loading-state { display: flex; align-items: center; justify-content: center; height: 100%; color: #64748b; font-weight: 500; gap: 10px; }
.spinner { width: 20px; height: 20px; border: 3px solid #e2e8f0; border-top-color: #3b82f6; border-radius: 50%; animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

.table-container { height: 100%; overflow: auto; padding: 0; }
.data-table { width: 100%; border-collapse: collapse; font-size: 0.8rem; text-align: right; }
.data-table th, .data-table td { padding: 8px 12px; border-bottom: 1px solid #f1f5f9; white-space: nowrap; }
.data-table th { position: sticky; top: 0; background: #fff; font-weight: 600; color: #64748b; text-align: right; z-index: 1; }
.data-table th:first-child, .data-table td:first-child { text-align: left; }
.data-table tbody tr:hover { background-color: #f8fafc; }
.count-cell { text-align: center !important; }
.count-badge { color: white; border-radius: 12px; padding: 2px 8px; font-size: 0.7rem; font-weight: bold; min-width: 20px; display: inline-block; }
.empty-cell { color: #cbd5e1; }
</style>

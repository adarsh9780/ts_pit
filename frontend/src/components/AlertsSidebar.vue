<script setup>
import { ref, computed, watch } from 'vue';

const props = defineProps({
  alerts: {
    type: Array,
    required: true
  },
  selectedId: {
    type: [String, Number],
    default: null
  },
  availableDates: {
    type: Array,
    default: () => []
  },
  validStatuses: {
    type: Array,
    default: () => ['NEEDS_REVIEW', 'ESCALATE_L2', 'DISMISS']
  },
  searchValue: {
    type: String,
    default: ''
  },
  statusValue: {
    type: String,
    default: ''
  },
  typeValue: {
    type: String,
    default: ''
  },
  dateValue: {
    type: String,
    default: ''
  }
});

const emit = defineEmits(['select', 'filter-date', 'filter-search', 'filter-status', 'filter-type']);

const searchQuery = ref(props.searchValue);
const statusFilter = ref(props.statusValue);
const typeFilter = ref(props.typeValue);
const dateFilter = ref(props.dateValue);

watch(() => props.searchValue, (value) => {
  searchQuery.value = value || '';
});

watch(() => props.statusValue, (value) => {
  statusFilter.value = value || '';
});

watch(() => props.typeValue, (value) => {
  typeFilter.value = value || '';
});

watch(() => props.dateValue, (value) => {
  dateFilter.value = value || '';
});

// Computed filtered alerts to show counts
const filteredCount = computed(() => {
  // Logic usually handled by parent or backend, but good to know for UI
  return props.alerts.length; 
});

const resolveAlertId = (alert) => {
  if (!alert || typeof alert !== 'object') return alert;
  return alert.id ?? alert.alert_id ?? alert.alertId ?? alert['Alert ID'] ?? null;
};

const onSelect = (alert) => {
  const resolvedId = resolveAlertId(alert);
  emit('select', { id: resolvedId, alert });
};

// Filter handlers
const onSearch = () => emit('filter-search', searchQuery.value);
const onStatusChange = () => emit('filter-status', statusFilter.value);
const onTypeChange = (type) => {
  typeFilter.value = typeFilter.value === type ? '' : type; // Toggle
  emit('filter-type', typeFilter.value);
};
const onDateChange = () => emit('filter-date', dateFilter.value);

const formatTime = (dateStr) => {
   if (!dateStr) return '';
   return dateStr.split('T')[1]?.slice(0, 5) || dateStr; // Simple time extraction if local time
};

const statusClassMap = {
    NEEDS_REVIEW: 'status-dot-warning',
    ESCALATE_L2: 'status-dot-danger',
    DISMISS: 'status-dot-success',
    Pending: 'status-dot-warning',
    Approved: 'status-dot-danger',
    Rejected: 'status-dot-success'
};

const getStatusClass = (status) => statusClassMap[status] || 'status-dot-warning';

const getTypeClass = (type) => {
    return type?.toLowerCase() === 'buy' ? 'badge-buy' : 'badge-sell';
};
</script>

<template>
  <div class="sidebar">
    <!-- Header / Filters -->
    <div class="sidebar-header">
      <div class="search-box">
        <input 
          v-model="searchQuery" 
          @input="onSearch"
          type="text" 
          placeholder="Search Ticker or Company..." 
          class="input-search"
        />
      </div>
      
      <div class="filters-row">
        <select v-model="dateFilter" @change="onDateChange" class="select-sm">
          <option value="">All Dates</option>
          <option v-for="date in availableDates" :key="date" :value="date">{{ date }}</option>
        </select>
        
        <select v-model="statusFilter" @change="onStatusChange" class="select-sm">
          <option value="">All Status</option>
          <option v-for="status in validStatuses" :key="status" :value="status">{{ status }}</option>
        </select>
      </div>

       <div class="type-toggles">
          <button 
            :class="['type-btn', { active: typeFilter === 'Buy' }]" 
            @click="onTypeChange('Buy')"
          >Buy</button>
          <button 
            :class="['type-btn', { active: typeFilter === 'Sell' }]" 
            @click="onTypeChange('Sell')"
          >Sell</button>
       </div>
       
       <div class="list-stats">
          <span>{{ alerts.length }} Alerts</span>
       </div>
    </div>

    <!-- Alert List -->
    <div class="alert-list">
      <div 
        v-for="alert in alerts" 
        :key="resolveAlertId(alert) ?? `${alert.ticker}-${alert.execution_date}`"
        class="alert-card"
        :class="{ active: selectedId === resolveAlertId(alert) }"
        @click="onSelect(alert)"
      >
        <div class="card-header">
          <div class="ticker-box">
            <span class="ticker">{{ alert.ticker }}</span>
            <span class="type-badge" :class="getTypeClass(alert.trade_type)">
              {{ alert.trade_type }}
            </span>
          </div>
          <span class="date">{{ alert.execution_date }}</span>
        </div>
        
        <div class="card-body">
            <span class="instrument">{{ alert.instrument_name }}</span>
            <div class="date-range">
                <span class="range-date">Start: {{ alert.start_date || '-' }}</span>
                <span class="range-date">End: {{ alert.end_date || '-' }}</span>
            </div>
        </div>
        
        <div class="card-footer">
            <span class="alert-id">Alert ID: #{{ resolveAlertId(alert) ?? '-' }}</span>
            <div class="status-indicator">
                <span class="status-dot" :class="getStatusClass(alert.status)"></span>
                <span class="status-text">{{ alert.status }}</span>
            </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.sidebar {
  display: flex;
  flex-direction: column;
  height: 100%;
  background-color: var(--color-surface);
  border-right: 1px solid var(--color-border);
}

.sidebar-header {
  padding: var(--spacing-4);
  background-color: var(--color-background);
  border-bottom: 1px solid var(--color-border);
  display: flex;
  flex-direction: column;
  gap: var(--spacing-3);
}

.input-search {
  width: 100%;
  padding: var(--spacing-2) var(--spacing-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  font-size: var(--font-size-sm);
  outline: none;
  transition: border-color 0.2s;
}

.input-search:focus {
  border-color: var(--color-accent);
}

.filters-row {
  display: flex;
  gap: var(--spacing-2);
}

.select-sm {
  flex: 1;
  padding: var(--spacing-1) var(--spacing-2);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  font-size: var(--font-size-xs);
  background: var(--color-surface);
  color: var(--color-text-main);
  cursor: pointer;
}

.type-toggles {
  display: flex;
  background: var(--color-border);
  padding: 2px;
  border-radius: var(--radius-sm);
}

.type-btn {
  flex: 1;
  border: none;
  background: transparent;
  padding: 4px;
  font-size: var(--font-size-xs);
  cursor: pointer;
  border-radius: var(--radius-sm);
  color: var(--color-text-muted);
  transition: all 0.2s;
}

.type-btn.active {
  background: var(--color-surface);
  color: var(--color-text-main);
  box-shadow: var(--shadow-sm);
  font-weight: var(--font-weight-medium);
}

.list-stats {
  font-size: var(--font-size-xs);
  color: var(--color-text-subtle);
  text-align: right;
}

.alert-list {
  flex: 1;
  overflow-y: auto;
  padding: var(--spacing-2);
}

.alert-card {
  background: var(--color-surface);
  border: 1px solid transparent;
  border-radius: var(--radius-md);
  padding: var(--spacing-3);
  margin-bottom: var(--spacing-2);
  cursor: pointer;
  transition: all 0.2s;
  border-bottom: 1px solid var(--color-divider);
}

.alert-card:hover {
  background-color: var(--color-surface-hover);
}

.alert-card.active {
  background-color: var(--color-accent-subtle);
  border-color: var(--color-accent);
  box-shadow: var(--shadow-sm);
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--spacing-1);
}

.ticker-box {
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
}

.ticker {
  font-weight: var(--font-weight-bold);
  font-size: var(--font-size-base);
  color: var(--color-text-main);
}

.type-badge {
  font-size: 10px;
  text-transform: uppercase;
  font-weight: 800;
  padding: 2px 6px;
  border-radius: 4px;
}

.badge-buy {
  background-color: var(--color-success-bg);
  color: var(--color-success-text);
}

.badge-sell {
  background-color: var(--color-danger-bg);
  color: var(--color-danger-text);
}

.date {
  font-size: var(--font-size-xs);
  color: var(--color-text-subtle);
}

.card-body {
    margin-bottom: var(--spacing-2);
}

.instrument {
    font-size: var(--font-size-sm);
    color: var(--color-text-muted);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    display: block;
    margin-bottom: 4px;
}

.date-range {
    display: flex;
    gap: 8px;
    font-size: 10px;
    color: var(--color-text-subtle);
}

.range-date {
    background: var(--color-background);
    padding: 1px 4px;
    border-radius: 4px;
}

.card-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.alert-id {
    font-size: 10px;
    color: var(--color-text-subtle);
    font-family: var(--font-family-ui);
}

.status-indicator {
    display: flex;
    align-items: center;
    gap: var(--spacing-1);
}

.status-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
}

.status-dot-success { background-color: var(--color-success); }
.status-dot-danger { background-color: var(--color-danger); }
.status-dot-warning { background-color: var(--color-warning); }

.status-text {
    font-size: var(--font-size-xs);
    font-weight: var(--font-weight-medium);
}
</style>

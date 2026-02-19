<script setup>
import { ref, onMounted, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import AlertsSidebar from '../../../components/AlertsSidebar.vue';
import AlertDetail from './AlertDetailView.vue'; 
import AgentPanel from '../../agent/components/AgentPanelFeature.vue';
import { getAlerts, getConfig } from '../../../api/service.js';

const DASHBOARD_UI_STATE_KEY = 'ts_pit.dashboard.ui_state.v1';

// State
const alerts = ref([]);
const filteredAlerts = ref([]);
const selectedAlertId = ref(null);
const loading = ref(true);
const availableDates = ref([]);
const mappings = ref({}); // Keep mappings if needed by children
const validStatuses = ref(['NEEDS_REVIEW', 'ESCALATE_L2', 'DISMISS']);
const isSidebarCollapsed = ref(false);
const isAgentOpen = ref(false); // Controls Agent Panel visibility
const route = useRoute();
const router = useRouter();

const resolveAlertId = (item) => {
  if (item == null) return null;
  if (typeof item === 'object') {
    return item.id ?? item.alert_id ?? item.alertId ?? item['Alert ID'] ?? null;
  }
  return item;
};

const normalizeAlertId = (item) => {
  const id = resolveAlertId(item);
  if (id == null || id === '') return null;
  return String(id);
};

const currentFilters = ref({
  search: '',
  status: '',
  type: '',
  date: ''
});

const persistUiState = () => {
  try {
    localStorage.setItem(
      DASHBOARD_UI_STATE_KEY,
      JSON.stringify({
        filters: currentFilters.value,
        isSidebarCollapsed: isSidebarCollapsed.value,
        isAgentOpen: isAgentOpen.value
      })
    );
  } catch (error) {
    console.warn('Failed to persist dashboard UI state:', error);
  }
};

const restoreUiState = () => {
  try {
    const raw = localStorage.getItem(DASHBOARD_UI_STATE_KEY);
    if (!raw) return;
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed === 'object') {
      const hasRouteAlert = Boolean(normalizeAlertId(route.params.alertId));
      const filters = parsed.filters ?? {};
      currentFilters.value = {
        search: typeof filters.search === 'string' ? filters.search : '',
        status: typeof filters.status === 'string' ? filters.status : '',
        type: typeof filters.type === 'string' ? filters.type : '',
        // Always default to latest available date on load.
        date: ''
      };
      isSidebarCollapsed.value = hasRouteAlert ? Boolean(parsed.isSidebarCollapsed) : false;
      isAgentOpen.value = hasRouteAlert ? Boolean(parsed.isAgentOpen) : false;
    }
  } catch (error) {
    console.warn('Failed to restore dashboard UI state:', error);
  }
};

const toggleSidebar = () => {
  isSidebarCollapsed.value = !isSidebarCollapsed.value;
  persistUiState();
};

// Toggle Agent Panel
const toggleAgent = () => {
  isAgentOpen.value = !isAgentOpen.value;
  persistUiState();
};

const fetchConfig = async () => {
  try {
    const data = await getConfig();
    mappings.value = data;
    if (Array.isArray(data?.valid_statuses) && data.valid_statuses.length > 0) {
      validStatuses.value = data.valid_statuses;
    }
  } catch (error) {
    console.error('Error fetching config:', error);
  }
};

// Dashboard Layout Logic
const fetchAlerts = async (date = null) => {
  loading.value = true;
  try {
    const params = date ? { date } : {};
    alerts.value = await getAlerts(params);
    
    // Extract dates and default date only when there is no restored user preference.
    if (!date && alerts.value.length > 0) {
      const dates = [...new Set(alerts.value.map(a => a.alert_date))].sort().reverse();
      availableDates.value = dates;

      if (dates.length > 0 && !currentFilters.value.date) {
        currentFilters.value.date = dates[0];
      }
    }
    applyFilters();
  } catch (error) {
    console.error('Error fetching alerts:', error);
  } finally {
    loading.value = false;
  }
};

// Selection Handler
const onAlertSelect = (payload) => {
  const id = normalizeAlertId(payload?.id != null ? payload.id : payload);
  if (!id) return;
  selectedAlertId.value = id;
  // Auto-collapse on selection if not already collapsed
  if (!isSidebarCollapsed.value) {
    isSidebarCollapsed.value = true;
    persistUiState();
  }
  if (route.params.alertId !== id) {
    router.push({ name: 'AlertDetail', params: { alertId: id } });
  }
};

const normalizeTradeType = (value) => String(value || '').trim().toLowerCase();
const toNumber = (value) => {
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
};
const deriveTradeType = (alert) => {
  const direct = normalizeTradeType(alert?.trade_type);
  if (direct === 'buy' || direct === 'sell') return direct;

  const altKeys = ['tradeSide', 'trade_side', 'side', 'type', 'buy_sell'];
  for (const key of altKeys) {
    const value = normalizeTradeType(alert?.[key]);
    if (value === 'buy' || value === 'sell') return value;
  }

  const buyQty = toNumber(alert?.buy_quantity ?? alert?.buyQty);
  const sellQty = toNumber(alert?.sell_quantity ?? alert?.sellQty);
  if (buyQty > sellQty) return 'buy';
  if (sellQty > buyQty) return 'sell';
  return '';
};

const applyFilters = () => {
    let result = alerts.value;
    const { search, status, type, date } = currentFilters.value;

    if (date) {
        // Filter locally by date
        result = result.filter(a => a.alert_date === date);
    }

    if (search) {
        const q = search.toLowerCase();
        result = result.filter(a => 
            String(a.ticker || '').toLowerCase().includes(q) || 
            String(a.company_name || '').toLowerCase().includes(q)
        );
    }
    
    if (status) {
         result = result.filter(a => a.status === status);
    }
    
    if (type) {
         const targetType = normalizeTradeType(type);
         result = result.filter(a => deriveTradeType(a) === targetType);
    }

    filteredAlerts.value = result;
};

// Event Handlers from Sidebar
const onFilterSearch = (val) => { currentFilters.value.search = val; applyFilters(); };
const onFilterStatus = (val) => { currentFilters.value.status = val; applyFilters(); };
const onFilterType = (val) => { currentFilters.value.type = val; applyFilters(); };
const onFilterDate = (val) => { 
    currentFilters.value.date = val; 
    applyFilters();
};

watch(
  () => route.params.alertId,
  (nextAlertId) => {
    selectedAlertId.value = normalizeAlertId(nextAlertId);
    if (!selectedAlertId.value) {
      if (isSidebarCollapsed.value) isSidebarCollapsed.value = false;
      if (isAgentOpen.value) isAgentOpen.value = false;
      persistUiState();
    }
  },
  { immediate: true }
);

watch(
  () => isAgentOpen.value,
  () => {
    persistUiState();
  }
);

watch(
  currentFilters,
  () => {
    persistUiState();
  },
  { deep: true }
);

onMounted(async () => {
  restoreUiState();
  await fetchConfig();
  await fetchAlerts();
});

</script>

<template>
  <div class="dashboard-container">
    <div class="sidebar-pane" :class="{ collapsed: isSidebarCollapsed }">
        <div class="app-brand">
            <h2 v-if="!isSidebarCollapsed">InsiderTrade<span class="brand-accent">Monitor</span></h2>
            <button class="toggle-btn" @click="toggleSidebar" title="Toggle Sidebar">
                {{ isSidebarCollapsed ? '☰' : '«' }}
            </button>
        </div>
        <div class="sidebar-content" :style="{ opacity: isSidebarCollapsed ? 0 : 1 }">
             <AlertsSidebar 
                :alerts="filteredAlerts" 
                :availableDates="availableDates"
                :selectedId="selectedAlertId"
                :validStatuses="validStatuses"
                :searchValue="currentFilters.search"
                :statusValue="currentFilters.status"
                :typeValue="currentFilters.type"
                :dateValue="currentFilters.date"
                @select="onAlertSelect"
                @filter-search="onFilterSearch"
                @filter-status="onFilterStatus"
                @filter-type="onFilterType"
                @filter-date="onFilterDate"
            />
        </div>
    </div>
    
    <div class="main-content-pane">
        <div v-if="loading && alerts.length === 0" class="empty-state">
            <p>Loading alerts...</p>
        </div>
        
        <div v-else-if="selectedAlertId !== null && selectedAlertId !== undefined && selectedAlertId !== ''" class="detail-wrapper">
             <AlertDetail 
                :key="selectedAlertId" 
                :alertId="selectedAlertId" 
                @toggle-agent="toggleAgent"
             /> 
        </div>
        
        <div v-else class="empty-state">
            <div class="empty-content">
                <h3>Select an alert to investigate</h3>
                <p>Choose an item from the sidebar to view metrics and news.</p>
            </div>
        </div>
    </div>

    <!-- Agent Panel (Right Side) -->
    <transition name="slide-panel">
        <AgentPanel 
            v-if="isAgentOpen" 
            :alertId="selectedAlertId" 
            @close="isAgentOpen = false" 
        />
    </transition>
  </div>
</template>

<style scoped>
.dashboard-container {
    display: flex;
    height: 100vh;
    width: 100%;
    overflow: hidden;
    background-color: var(--color-background);
}

.sidebar-pane {
    width: var(--sidebar-width);
    display: flex;
    flex-direction: column;
    border-right: 1px solid var(--color-border);
    background: var(--color-surface);
    flex-shrink: 0;
    transition: width 0.3s cubic-bezier(0.4, 0, 0.2, 1);
    position: relative;
    overflow: hidden;
}

.sidebar-pane.collapsed {
    width: 60px; /* Collapsed width */
}

.sidebar-content {
    flex: 1;
    overflow: hidden;
    transition: opacity 0.2s ease;
    width: var(--sidebar-width); /* Maintain width to prevent squashing during transition */
}

.sidebar-pane.collapsed .sidebar-content {
     pointer-events: none; /* Prevent interaction when hidden */
}

.app-brand {
    padding: var(--spacing-4);
    border-bottom: 1px solid var(--color-border);
    display: flex;
    justify-content: space-between;
    align-items: center;
    height: var(--header-height);
    white-space: nowrap;
}

.toggle-btn {
    background: transparent;
    border: none;
    cursor: pointer;
    font-size: 1.2rem;
    color: var(--color-text-muted);
    padding: 4px 8px;
    border-radius: 4px;
    transition: background 0.2s;
}

.toggle-btn:hover {
    background: var(--color-surface-hover);
    color: var(--color-primary);
}

.app-brand h2 {
    margin: 0;
    font-size: var(--font-size-lg);
    font-weight: 800;
    color: var(--color-primary);
    letter-spacing: -0.5px;
}

.brand-accent {
    color: var(--color-accent);
}

.main-content-pane {
    flex: 1;
    overflow: hidden; /* Detail view handles its own scroll */
    position: relative;
    background-color: var(--color-background);
}

.detail-wrapper {
    height: 100%;
    overflow-y: auto;
}

.empty-state {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 100%;
    color: var(--color-text-subtle);
}

.empty-content {
    text-align: center;
}

.empty-content h3 {
    margin: 0 0 var(--spacing-2) 0;
    color: var(--color-text-main);
}

/* Agent Toggle Button */
.agent-toggle-btn {
    position: absolute;
    top: 20px;
    right: 20px;
    z-index: 100;
    background-color: var(--color-primary);
    color: white;
    border: none;
    padding: 8px 16px;
    border-radius: 20px;
    font-weight: 600;
    box-shadow: 0 2px 8px rgba(0,0,0,0.2);
    cursor: pointer;
    transition: transform 0.2s, background-color 0.2s;
    display: flex;
    align-items: center;
    gap: 6px;
}

.agent-toggle-btn:hover {
    transform: translateY(-2px);
    background-color: var(--color-primary-hover, #0056b3);
}

/* Slide Panel Transition */
.slide-panel-enter-active,
.slide-panel-leave-active {
    transition: transform 0.3s cubic-bezier(0.16, 1, 0.3, 1);
}

.slide-panel-enter-from,
.slide-panel-leave-to {
    transform: translateX(100%);
}
</style>

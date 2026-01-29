<script setup>
import { ref, onMounted, computed } from 'vue';
import axios from 'axios';
import AlertsSidebar from '../components/AlertsSidebar.vue';
import AlertDetail from './AlertDetail.vue'; 

// State
const alerts = ref([]);
const filteredAlerts = ref([]);
const selectedAlertId = ref(null);
const loading = ref(true);
const availableDates = ref([]);
const mappings = ref({}); // Keep mappings if needed by children
const isSidebarCollapsed = ref(false);

const toggleSidebar = () => {
    isSidebarCollapsed.value = !isSidebarCollapsed.value;
};

// Dashboard Layout Logic
const fetchAlerts = async (date = null) => {
  loading.value = true;
  try {
    const params = date ? { date } : {};
    const response = await axios.get('http://localhost:8000/alerts', { params });
    alerts.value = response.data;
    applyFilters(); // Initial filter application
    
    // Extract dates if not already set (or always update if needed)
    if (!date && alerts.value.length > 0) {
      const dates = [...new Set(alerts.value.map(a => a.alert_date))].sort().reverse();
      availableDates.value = dates;
      
      // Default to the latest date (Today - 1 concept)
      if (dates.length > 0) {
          currentFilters.value.date = dates[0];
          // Re-apply filter immediately locally since we have all data
          // Or if we need strict backend filtering, we call fetchAlerts(dates[0])
          // Given the current implementation fetches ALL then filters locally in applyFilters...
          // Wait, fetchAlerts takes a date param to filter on backend? 
          // Line 25: const params = date ? { date } : {}; -> Yes it does.
          
          // So we should probably fetch LATEST DATE only by default?
          // But to know the latest date we need to fetch all or have a metadata endpoint.
          // Current optimized approach:
          // 1. Fetch all (or is it efficient?) -> It fetches all if date is null.
          // 2. Find latest date.
          // 3. Set filter.
          
          // Better UX: select the date and filter the list we just got.
          applyFilters();
      }
    } else {
        applyFilters();
    }
  } catch (error) {
    console.error('Error fetching alerts:', error);
  } finally {
    loading.value = false;
  }
};

onMounted(async () => {
  await fetchAlerts();
});

// Selection Handler
// Selection Handler
const onAlertSelect = (id) => {
  selectedAlertId.value = id;
  // Auto-collapse on selection if not already collapsed
  if (!isSidebarCollapsed.value) {
    isSidebarCollapsed.value = true;
  }
};

// Filter State
const currentFilters = ref({
    search: '',
    status: '',
    type: '',
    date: ''
});

const applyFilters = () => {
    let result = alerts.value;
    const { search, status, type, date } = currentFilters.value;

    if (date) {
        // Filter locally by date
        result = result.filter(a => a.alert_date === date);
    }

    if (search) {
        const q = search.toLowerCase();
        result = result.filter(a => a.ticker.toLowerCase().includes(q));
    }
    
    if (status) {
         result = result.filter(a => a.status === status);
    }
    
    if (type) {
         result = result.filter(a => a.trade_type === type);
    }

    filteredAlerts.value = result;
};

// Event Handlers from Sidebar
const onFilterSearch = (val) => { currentFilters.value.search = val; applyFilters(); };
const onFilterStatus = (val) => { currentFilters.value.status = val; applyFilters(); };
const onFilterType = (val) => { currentFilters.value.type = val; applyFilters(); };
const onFilterDate = (val) => { 
    currentFilters.value.date = val; 
    fetchAlerts(val || null); // Re-fetch from backend as original implementation did
};

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
        
        <div v-else-if="selectedAlertId" class="detail-wrapper">
             <!-- Temporarily passing ID, we will refactor AlertDetail to accept prop -->
             <!-- For now, we render a placeholder if AlertDetail isn't ready as a component -->
             <!-- But since I declared import AlertDetail, I need to make sure it works or I wrap it -->
             <AlertDetail :key="selectedAlertId" :alertId="selectedAlertId" /> 
        </div>
        
        <div v-else class="empty-state">
            <div class="empty-content">
                <h3>Select an alert to investigate</h3>
                <p>Choose an item from the sidebar to view metrics and news.</p>
            </div>
        </div>
    </div>
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
</style>

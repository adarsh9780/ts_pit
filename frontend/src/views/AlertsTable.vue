<script setup>
import { ref, onMounted, computed } from 'vue';
import axios from 'axios';
import { useRouter } from 'vue-router';

const alerts = ref([]);
const config = ref({});
const router = useRouter();
const selectedDate = ref('');
const availableDates = ref([]);

// Display columns from config (with fallback)
const displayColumns = computed(() => {
  return config.value.display_columns || ['id', 'ticker', 'instrument_name', 'trade_type', 'execution_date', 'alert_date', 'start_date', 'end_date', 'status'];
});

const fetchConfig = async () => {
  try {
    const response = await axios.get('http://localhost:8000/config');
    config.value = response.data;
  } catch (error) {
    console.error('Error fetching config:', error);
  }
};

const fetchAlerts = async (date = null) => {
  try {
    const params = date ? { date } : {};
    const response = await axios.get('http://localhost:8000/alerts', { params });
    alerts.value = response.data;
    
    // Extract unique dates for the date filter
    if (!date && alerts.value.length > 0) {
      const dates = [...new Set(alerts.value.map(a => a.alert_date))].sort().reverse();
      availableDates.value = dates;
    }
  } catch (error) {
    console.error('Error fetching alerts:', error);
  }
};

const updateStatus = async (alertId, newStatus, event) => {
  event.stopPropagation(); // Prevent row click
  try {
    await axios.patch(`http://localhost:8000/alerts/${alertId}/status`, { status: newStatus });
    // Update locally
    const alert = alerts.value.find(a => a.id === alertId);
    if (alert) alert.status = newStatus;
  } catch (error) {
    console.error('Error updating status:', error);
  }
};

const goToDetail = (alertId, event) => {
  // Check if Ctrl/Cmd is pressed for new tab, otherwise same tab
  if (event.ctrlKey || event.metaKey) {
    const route = router.resolve({ name: 'AlertDetail', params: { id: alertId } });
    window.open(route.href, '_blank');
  } else {
    router.push({ name: 'AlertDetail', params: { id: alertId } });
  }
};

const onDateChange = () => {
  fetchAlerts(selectedDate.value || null);
};

const clearDateFilter = () => {
  selectedDate.value = '';
  fetchAlerts();
};

const getColumnLabel = (key) => {
  // Use labels from config if available
  const labels = config.value.column_labels || {};
  if (labels[key]) return labels[key];
  // Fallback: capitalize and replace underscores
  return key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
};

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

onMounted(async () => {
  await fetchConfig();
  await fetchAlerts();
});
</script>

<template>
  <div class="page-container">
    <div class="header">
      <div class="header-content">
        <div>
          <h1>Financial Alerts Dashboard</h1>
          <p class="subtitle">Trade monitoring & investigation tool</p>
        </div>
        <div class="header-stats">
          <div class="stat">
            <span class="stat-value">{{ alerts.length }}</span>
            <span class="stat-label">Total Alerts</span>
          </div>
          <div class="stat">
            <span class="stat-value">{{ alerts.filter(a => a.status === 'NEEDS_REVIEW').length }}</span>
            <span class="stat-label">Needs Review</span>
          </div>
        </div>
      </div>
    </div>
    
    <div class="content-wrapper">
      <!-- Filters -->
      <div class="filters-bar">
        <div class="filter-group">
          <label>Filter by Alert Date:</label>
          <select v-model="selectedDate" @change="onDateChange" class="date-select">
            <option value="">All Dates</option>
            <option v-for="date in availableDates" :key="date" :value="date">{{ date }}</option>
          </select>
          <button v-if="selectedDate" @click="clearDateFilter" class="clear-btn">Clear</button>
        </div>
        <div class="legend">
          <span class="legend-hint">💡 Click row to view • Ctrl+Click for new tab</span>
        </div>
      </div>
      
      <div class="card">
        <div class="table-container">
          <table>
            <thead>
              <tr>
                <th v-for="col in displayColumns" :key="col">{{ getColumnLabel(col) }}</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="alert in alerts" :key="alert.id" @click="goToDetail(alert.id, $event)" class="clickable-row">
                <td v-for="col in displayColumns" :key="col">
                  <!-- Alert ID with link styling -->
                  <span v-if="col === 'id'" class="alert-id-link">{{ alert[col] }}</span>
                  <!-- Trade type badge -->
                  <span v-else-if="col === 'trade_type' && alert[col]" class="tag" :class="alert[col].toLowerCase()">{{ alert[col] }}</span>
                  <!-- Status badge -->
                  <span v-else-if="col === 'status'" class="status-badge" :class="getStatusClass(alert[col])">{{ alert[col] }}</span>
                  <!-- Default -->
                  <span v-else>{{ alert[col] }}</span>
                </td>
                <td class="actions-cell" @click.stop>
                  <button 
                    class="action-btn escalate" 
                    @click="updateStatus(alert.id, 'ESCALATE_L2', $event)"
                    :disabled="alert.status === 'ESCALATE_L2'"
                    title="Escalate to Level 2"
                  >!</button>
                  <button 
                    class="action-btn dismiss" 
                    @click="updateStatus(alert.id, 'DISMISS', $event)"
                    :disabled="alert.status === 'DISMISS'"
                    title="Dismiss"
                  >✓</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page-container {
    background-color: #f8fafc;
    min-height: 100vh;
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
}

.header {
    background: linear-gradient(135deg, #1e293b 0%, #334155 100%);
    padding: 2rem 3rem;
    color: white;
}

.header-content {
    display: flex;
    justify-content: space-between;
    align-items: center;
    max-width: 1400px;
    margin: 0 auto;
}

h1 {
    margin: 0;
    font-size: 1.875rem;
    font-weight: 700;
}

.subtitle {
    margin: 0.5rem 0 0 0;
    color: #94a3b8;
    font-size: 1rem;
}

.header-stats {
    display: flex;
    gap: 2rem;
}

.stat {
    text-align: center;
}

.stat-value {
    display: block;
    font-size: 2rem;
    font-weight: 700;
}

.stat-label {
    font-size: 0.875rem;
    color: #94a3b8;
}

.content-wrapper {
    padding: 2rem 3rem;
    max-width: 1400px;
    margin: 0 auto;
}

.filters-bar {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 1.5rem;
    background: white;
    padding: 1rem 1.5rem;
    border-radius: 0.75rem;
    border: 1px solid #e2e8f0;
}

.filter-group {
    display: flex;
    align-items: center;
    gap: 0.75rem;
}

.filter-group label {
    font-weight: 500;
    color: #475569;
}

.date-select {
    padding: 0.5rem 1rem;
    border: 1px solid #e2e8f0;
    border-radius: 0.5rem;
    font-size: 0.875rem;
    min-width: 160px;
    background: white;
    cursor: pointer;
}

.date-select:focus {
    outline: none;
    border-color: #3b82f6;
    box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
}

.clear-btn {
    padding: 0.5rem 1rem;
    background: #f1f5f9;
    border: none;
    border-radius: 0.5rem;
    font-size: 0.875rem;
    cursor: pointer;
    color: #64748b;
    transition: all 0.2s;
}

.clear-btn:hover {
    background: #e2e8f0;
}

.legend {
    color: #64748b;
    font-size: 0.875rem;
}

.legend-hint {
    background: #f1f5f9;
    padding: 0.5rem 1rem;
    border-radius: 2rem;
}

.card {
    background: white;
    border-radius: 0.75rem;
    border: 1px solid #e2e8f0;
    box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05);
    overflow: hidden;
}

.table-container {
    overflow-x: auto;
}

table {
    width: 100%;
    border-collapse: collapse;
    white-space: nowrap;
}

th {
    background-color: #f8fafc;
    color: #475569;
    font-weight: 600;
    text-align: left;
    padding: 1rem 1.5rem;
    border-bottom: 2px solid #e2e8f0;
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
}

td {
    padding: 1rem 1.5rem;
    border-bottom: 1px solid #f1f5f9;
    color: #1e293b;
    font-size: 0.925rem;
}

.clickable-row {
    cursor: pointer;
    transition: all 0.15s ease;
}

.clickable-row:hover {
    background-color: #f8fafc;
    transform: translateX(2px);
}

.clickable-row:hover .alert-id-link {
    color: #3b82f6;
    text-decoration: underline;
}

.alert-id-link {
    color: #3b82f6;
    font-weight: 600;
    transition: all 0.15s;
}

/* Tags */
.tag {
    padding: 0.25rem 0.75rem;
    border-radius: 9999px;
    font-size: 0.75rem;
    font-weight: 600;
    letter-spacing: 0.025em;
    text-transform: uppercase;
}

.tag.buy {
    background-color: #dcfce7;
    color: #166534;
}

.tag.sell {
    background-color: #fee2e2;
    color: #991b1b;
}

/* Status badges */
.status-badge {
    padding: 0.25rem 0.75rem;
    border-radius: 0.375rem;
    font-size: 0.75rem;
    font-weight: 600;
}

.status-needs-review {
    background-color: #fef3c7;
    color: #92400e;
}

.status-escalate-l2 {
    background-color: #fee2e2;
    color: #991b1b;
}

.status-dismiss {
    background-color: #dcfce7;
    color: #166534;
}

/* Action buttons */
.actions-cell {
    display: flex;
    gap: 0.5rem;
}

.action-btn {
    width: 2rem;
    height: 2rem;
    border: none;
    border-radius: 0.375rem;
    cursor: pointer;
    font-size: 0.875rem;
    transition: all 0.2s;
    display: flex;
    align-items: center;
    justify-content: center;
}

.action-btn:disabled {
    opacity: 0.3;
    cursor: not-allowed;
}

.action-btn.dismiss {
    background: #dcfce7;
    color: #166534;
}

.action-btn.dismiss:hover:not(:disabled) {
    background: #bbf7d0;
}

.action-btn.escalate {
    background: #fee2e2;
    color: #991b1b;
}

.action-btn.escalate:hover:not(:disabled) {
    background: #fecaca;
}
</style>

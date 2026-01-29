import { createRouter, createWebHistory } from 'vue-router';
import AlertsTable from '../views/AlertsTable.vue';
import AlertDetail from '../views/AlertDetail.vue';

const routes = [
    {
        path: '/',
        name: 'Dashboard',
        component: () => import('../views/DashboardLayout.vue')
    }
];

const router = createRouter({
    history: createWebHistory(import.meta.env.BASE_URL),
    routes
});

export default router;

import { createRouter, createWebHistory } from 'vue-router';

const routes = [
    {
        path: '/',
        name: 'Dashboard',
        component: () => import('../views/DashboardLayout.vue')
    },
    {
        path: '/:alertId',
        name: 'AlertDetail',
        component: () => import('../views/DashboardLayout.vue')
    }
];

const router = createRouter({
    history: createWebHistory(import.meta.env.BASE_URL),
    routes
});

export default router;

import { Api } from './generated/index.js';

const baseURL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

const api = new Api({ baseURL });

export default api;

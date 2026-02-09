import api from './client.js';
import { API_BASE_URL } from './index.js';

export const getConfig = async () => {
  const response = await api.config.getConfigEndpointConfigGet();
  return response.data;
};

export const getAlerts = async (query = {}) => {
  const response = await api.alerts.getAlertsAlertsGet(query);
  return response.data;
};

export const updateAlertStatus = async (alertId, status) => {
  const response = await api.alerts.updateAlertStatusAlertsAlertIdStatusPatch(alertId, { status });
  return response.data;
};

export const getAlertDetail = async (alertId) => {
  const response = await api.alerts.getAlertDetailAlertsAlertIdGet(alertId);
  return response.data;
};

export const analyzeArticle = async (articleId) => {
  const response = await api.articles.analyzeArticleArticlesIdAnalyzePost(articleId);
  return response.data;
};

export const generateSummary = async (alertId) => {
  const response = await api.alerts.generateSummaryAlertsAlertIdSummaryPost(alertId);
  return response.data;
};

export const getPrices = async (ticker, query = {}) => {
  const response = await api.prices.getPricesPricesTickerGet(ticker, query);
  return response.data;
};

export const getNews = async (isin, query = {}) => {
  const response = await api.news.getNewsNewsIsinGet(isin, query);
  return response.data;
};

export const getChatHistory = async (sessionId) => {
  const response = await api.agent.getChatHistoryAgentHistorySessionIdGet(sessionId);
  return response.data;
};

export const deleteChatHistory = async (sessionId) => {
  const response = await api.agent.deleteChatHistoryAgentHistorySessionIdDelete(sessionId);
  return response.data;
};

export const uploadChartSnapshot = async (payload) => {
  const response = await api.reports.uploadChartSnapshotReportsChartSnapshotPost(payload);
  return response.data;
};

export const listArtifacts = async (sessionId) => {
  const response = await api.artifacts.listSessionArtifactsArtifactsSessionIdGet(sessionId);
  return response.data;
};

export const getAgentChatUrl = () => `${API_BASE_URL}/agent/chat`;

export const buildArtifactDownloadUrl = (sessionId, relativePath) => {
  const url = new URL(`${API_BASE_URL}/artifacts/${sessionId}/download`);
  url.searchParams.set('path', relativePath);
  return url.toString();
};

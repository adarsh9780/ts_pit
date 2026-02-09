import {
  analyzeArticle,
  generateSummary as generateAlertSummary,
  getAlertDetail,
  getConfig,
  getNews,
  getPrices,
  updateAlertStatus,
} from '../../../api/service.js';

const formatDate = (d) => d.toISOString().split('T')[0];

const getPriceQueryForPeriod = (alert, period) => {
  if (period !== 'alert' || !alert) return { period };

  const startDate = new Date(alert.start_date);
  const endDate = new Date(alert.end_date);
  startDate.setDate(startDate.getDate() - 10);
  endDate.setDate(endDate.getDate() + 10);

  return {
    start_date: formatDate(startDate),
    end_date: formatDate(endDate),
  };
};

export function useAlertDetail() {
  const fetchAlertDetail = async (alertId) => getAlertDetail(alertId);

  const fetchConfig = async () => getConfig();

  const fetchPrices = async (alert, period) => {
    const query = getPriceQueryForPeriod(alert, period);
    return getPrices(alert.ticker, query);
  };

  const fetchNews = async (alert) =>
    getNews(alert.isin, {
      start_date: alert.start_date,
      end_date: alert.end_date,
    });

  const generateSummary = async (alertId) => generateAlertSummary(alertId);

  const updateStatus = async (alertId, status) => updateAlertStatus(alertId, status);

  const analyzeArticles = async (articles = []) => {
    return Promise.all(
      articles.map(async (article) => {
        try {
          const result = await analyzeArticle(article.id);
          return { ok: true, article, result };
        } catch (error) {
          return { ok: false, article, error };
        }
      })
    );
  };

  const loadAlertBundle = async (alertId, period) => {
    const alert = await fetchAlertDetail(alertId);
    const [prices, news] = await Promise.all([
      fetchPrices(alert, period),
      fetchNews(alert),
    ]);

    return { alert, prices, news };
  };

  return {
    fetchAlertDetail,
    fetchConfig,
    fetchPrices,
    fetchNews,
    generateSummary,
    updateStatus,
    analyzeArticles,
    loadAlertBundle,
  };
}

import unittest
from unittest.mock import patch

from ts_pit.agent_v3 import tools
from ts_pit import reporting
from ts_pit.config import get_config


class NewsQueryExpansionTests(unittest.TestCase):
    def test_prepare_search_query_adds_company_name_for_ticker(self):
        with patch.object(
            tools,
            "_lookup_instrument_names_for_tickers",
            return_value={"TSLA": "Tesla Inc"},
        ):
            query = tools._prepare_search_query("TSLA stock news", "2025-10-30")
        self.assertIn("TSLA stock news", query)
        self.assertIn('"Tesla Inc"', query)
        self.assertIn("October 2025", query)

    def test_prepare_search_query_does_not_duplicate_company_name(self):
        with patch.object(
            tools,
            "_lookup_instrument_names_for_tickers",
            return_value={"TSLA": "Tesla Inc"},
        ):
            query = tools._prepare_search_query('TSLA "Tesla Inc" stock news', None)
        self.assertEqual(query, 'TSLA "Tesla Inc" stock news')

    def test_report_query_includes_ticker_and_company_name(self):
        cfg = get_config()
        alert = {
            cfg.get_column("alerts", "ticker"): "TSLA",
            cfg.get_column("alerts", "instrument_name"): "Tesla Inc",
        }
        query = reporting._build_web_news_query(alert, cfg)
        self.assertIn("TSLA", query)
        self.assertIn('"Tesla Inc"', query)
        self.assertIn("stock company news", query)

    def test_coerce_refined_search_query_rejects_missing_ticker(self):
        out = tools._coerce_refined_search_query(
            "Tesla Inc earnings news",
            fallback_query='TSLA "Tesla Inc" stock news',
            tickers=["TSLA"],
        )
        self.assertIsNone(out)

    def test_coerce_refined_search_query_accepts_valid_candidate(self):
        out = tools._coerce_refined_search_query(
            'TSLA "Tesla Inc" stock news October 2025',
            fallback_query='TSLA "Tesla Inc" stock news',
            tickers=["TSLA"],
        )
        self.assertEqual(out, 'TSLA "Tesla Inc" stock news October 2025')


if __name__ == "__main__":
    unittest.main()

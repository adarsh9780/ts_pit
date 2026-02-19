import asyncio
import json
import unittest
from unittest.mock import patch

from ts_pit.agent_v3 import tools


class GetArticlesByTickersToolTests(unittest.TestCase):
    def test_rejects_empty_ticker_input(self):
        raw = asyncio.run(
            tools.get_articles_by_tickers.ainvoke({"tickers": " ,   ,  "})
        )
        parsed = json.loads(raw)
        self.assertFalse(parsed.get("ok"))
        self.assertEqual(
            (parsed.get("error") or {}).get("code"),
            "INVALID_INPUT",
        )

    def test_fetches_multiple_tickers_and_combines_payload(self):
        def fake_fetch_articles_for_ticker_via_alerts(
            ticker: str,
            *,
            start_date: str | None = None,
            end_date: str | None = None,
            max_articles_per_ticker: int = 200,
        ):
            if ticker == "AAPL":
                return {
                    "ticker": "AAPL",
                    "alert_ids": ["101"],
                    "articles": [
                        {
                            "id": "a1",
                            "ticker": "AAPL",
                            "title": "Apple launches update",
                            "materiality": "HHM",
                        }
                    ],
                    "article_count": 1,
                }
            return {
                "ticker": "MSFT",
                "alert_ids": ["202"],
                "articles": [
                    {
                        "id": "m1",
                        "ticker": "MSFT",
                        "title": "Microsoft guidance",
                        "materiality": "HMM",
                    }
                ],
                "article_count": 1,
            }

        with patch(
            "ts_pit.agent_v3.tools._fetch_articles_for_ticker_via_alerts",
            side_effect=fake_fetch_articles_for_ticker_via_alerts,
        ) as mocked:
            raw = asyncio.run(
                tools.get_articles_by_tickers.ainvoke(
                    {
                        "tickers": "AAPL, MSFT",
                        "start_date": "2025-01-01",
                        "end_date": "2025-01-31",
                        "max_articles_per_ticker": 50,
                    }
                )
            )

        parsed = json.loads(raw)
        self.assertTrue(parsed.get("ok"))
        meta = parsed.get("meta") or {}
        self.assertEqual(meta.get("ticker_count"), 2)
        self.assertEqual(meta.get("combined_count"), 2)

        data = parsed.get("data") or {}
        self.assertEqual(data.get("tickers"), ["AAPL", "MSFT"])
        self.assertEqual(len(data.get("combined_articles") or []), 2)
        by_ticker = data.get("by_ticker") or {}
        self.assertEqual((by_ticker.get("AAPL") or {}).get("article_count"), 1)
        self.assertEqual((by_ticker.get("MSFT") or {}).get("article_count"), 1)
        self.assertEqual(mocked.call_count, 2)


if __name__ == "__main__":
    unittest.main()

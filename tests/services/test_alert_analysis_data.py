import sqlite3
import unittest

from backend.services.alert_analysis_data import (
    resolve_alert_row,
    build_alert_articles,
    build_price_history,
)


class _FakeConfig:
    def __init__(self):
        self.tables = {
            "alerts": "alerts",
            "articles": "articles",
            "article_themes": "article_themes",
            "prices": "prices",
        }

    def get_table_name(self, key):
        return self.tables[key]

    def get_column(self, table, key):
        mapping = {
            "alerts": {
                "id": "alert_id",
                "isin": "isin",
                "ticker": "ticker",
                "start_date": "start_date",
                "end_date": "end_date",
            },
            "articles": {
                "id": "article_id",
                "isin": "isin",
                "created_date": "created_date",
                "title": "title",
                "summary": "summary",
                "impact_score": "impact_score",
                "theme": "theme",
            },
            "article_themes": {
                "art_id": "art_id",
                "theme": "theme",
                "summary": "summary",
                "analysis": "analysis",
                "p1_prominence": "p1_prominence",
            },
            "prices": {
                "ticker": "ticker",
                "date": "date",
                "close": "close",
            },
        }
        return mapping[table][key]


class AlertAnalysisDataTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.cursor = self.conn.cursor()
        self.config = _FakeConfig()

        self.cursor.execute(
            "CREATE TABLE alerts (alert_id INTEGER, isin TEXT, ticker TEXT, start_date TEXT, end_date TEXT)"
        )
        self.cursor.execute(
            "CREATE TABLE articles (article_id INTEGER, isin TEXT, title TEXT, summary TEXT, created_date TEXT, impact_score REAL, theme TEXT)"
        )
        self.cursor.execute(
            "CREATE TABLE article_themes (art_id INTEGER, theme TEXT, summary TEXT, analysis TEXT, p1_prominence TEXT)"
        )
        self.cursor.execute(
            "CREATE TABLE prices (ticker TEXT, date TEXT, close REAL)"
        )

        self.cursor.execute(
            "INSERT INTO alerts VALUES (101, 'US123', 'NVDA', '2026-02-01', '2026-02-10')"
        )
        self.cursor.execute(
            "INSERT INTO articles VALUES (1, 'US123', 'T1', 'S1', '2026-02-09', 2.2, 'EARNINGS_ANNOUNCEMENT')"
        )
        self.cursor.execute(
            "INSERT INTO article_themes VALUES (1, 'EARNINGS_ANNOUNCEMENT', 'AI summary', 'AI analysis', 'H')"
        )
        self.cursor.execute("INSERT INTO prices VALUES ('NVDA', '2026-02-09', 120.5)")
        self.cursor.execute("INSERT INTO prices VALUES ('NVDA', '2026-02-10', 121.2)")
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_resolve_alert_row_supports_numeric_string(self):
        row, matched_col, matched_value = resolve_alert_row(
            self.config,
            self.cursor,
            "alerts",
            "101",
        )
        self.assertIsNotNone(row)
        self.assertEqual(matched_col, "alert_id")
        self.assertIn(matched_value, {"101", 101})

    def test_build_alert_articles_builds_materiality_payload(self):
        alert = {"isin": "US123"}
        articles = build_alert_articles(
            self.config,
            self.cursor,
            alert,
            "2026-02-01",
            "2026-02-10",
        )
        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0]["article_id"], 1)
        self.assertEqual(articles[0]["theme"], "EARNINGS_ANNOUNCEMENT")
        self.assertEqual(len(articles[0]["materiality"]), 3)

    def test_build_price_history_filters_window(self):
        alert = {
            "ticker": "NVDA",
            "start_date": "2026-02-01",
            "end_date": "2026-02-10",
        }
        prices = build_price_history(self.config, self.cursor, alert)
        self.assertEqual(len(prices), 2)
        self.assertEqual(prices[0]["date"], "2026-02-09")
        self.assertEqual(prices[1]["date"], "2026-02-10")


if __name__ == "__main__":
    unittest.main()

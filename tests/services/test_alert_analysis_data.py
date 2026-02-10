import os
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine, text


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
    @classmethod
    def setUpClass(cls):
        from backend.db import engine as db_engine
        from backend.services import alert_analysis_data, db_helpers

        cls._tmp_dir = tempfile.TemporaryDirectory()
        db_file = Path(cls._tmp_dir.name) / "alert_analysis_data_test.sqlite"
        cls.db_url = f"sqlite:///{db_file}"
        os.environ["DATABASE_URL"] = cls.db_url

        db_engine._ENGINE = None
        db_helpers._table_cache.clear()
        alert_analysis_data._table_cache.clear()
        alert_analysis_data.metadata.clear()

        seed_engine = create_engine(cls.db_url, future=True)
        with seed_engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE TABLE alerts (alert_id INTEGER, isin TEXT, ticker TEXT, start_date TEXT, end_date TEXT)"
                )
            )
            conn.execute(
                text(
                    "CREATE TABLE articles (article_id INTEGER, isin TEXT, title TEXT, summary TEXT, created_date TEXT, impact_score REAL, theme TEXT)"
                )
            )
            conn.execute(
                text(
                    "CREATE TABLE article_themes (art_id INTEGER, theme TEXT, summary TEXT, analysis TEXT, p1_prominence TEXT)"
                )
            )
            conn.execute(text("CREATE TABLE prices (ticker TEXT, date TEXT, close REAL)"))

            conn.execute(
                text(
                    "INSERT INTO alerts VALUES (101, 'US123', 'NVDA', '2026-02-01', '2026-02-10')"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO articles VALUES (1, 'US123', 'T1', 'S1', '2026-02-09', 2.2, 'EARNINGS_ANNOUNCEMENT')"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO article_themes VALUES (1, 'EARNINGS_ANNOUNCEMENT', 'AI summary', 'AI analysis', 'H')"
                )
            )
            conn.execute(text("INSERT INTO prices VALUES ('NVDA', '2026-02-09', 120.5)"))
            conn.execute(text("INSERT INTO prices VALUES ('NVDA', '2026-02-10', 121.2)"))

    @classmethod
    def tearDownClass(cls):
        from backend.db import engine as db_engine
        from backend.services import alert_analysis_data, db_helpers

        db_engine._ENGINE = None
        db_helpers._table_cache.clear()
        alert_analysis_data._table_cache.clear()
        alert_analysis_data.metadata.clear()
        os.environ.pop("DATABASE_URL", None)
        cls._tmp_dir.cleanup()

    def setUp(self):
        self.config = _FakeConfig()

    def test_resolve_alert_row_supports_numeric_string(self):
        from backend.services.alert_analysis_data import resolve_alert_row

        row, matched_col, matched_value = resolve_alert_row(
            self.config,
            None,
            "alerts",
            "101",
        )
        self.assertIsNotNone(row)
        self.assertEqual(matched_col, "alert_id")
        self.assertIn(matched_value, {"101", 101})

    def test_build_alert_articles_builds_materiality_payload(self):
        from backend.services.alert_analysis_data import build_alert_articles

        alert = {"isin": "US123"}
        articles = build_alert_articles(
            self.config,
            None,
            alert,
            "2026-02-01",
            "2026-02-10",
        )
        self.assertEqual(len(articles), 1)
        self.assertEqual(str(articles[0]["article_id"]), "1")
        self.assertEqual(articles[0]["theme"], "EARNINGS_ANNOUNCEMENT")
        self.assertEqual(len(articles[0]["materiality"]), 3)

    def test_build_price_history_filters_window(self):
        from backend.services.alert_analysis_data import build_price_history

        alert = {
            "ticker": "NVDA",
            "start_date": "2026-02-01",
            "end_date": "2026-02-10",
        }
        prices = build_price_history(self.config, None, alert)
        self.assertEqual(len(prices), 2)
        self.assertEqual(prices[0]["date"], "2026-02-09")
        self.assertEqual(prices[1]["date"], "2026-02-10")


if __name__ == "__main__":
    unittest.main()

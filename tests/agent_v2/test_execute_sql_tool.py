import importlib
import json
import os
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine, text


class ExecuteSqlToolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from backend import config as config_module
        from backend.config import get_config
        from backend.db import engine as db_engine

        cls._tmp_dir = tempfile.TemporaryDirectory()
        db_file = Path(cls._tmp_dir.name) / "agent_v2_execute_sql_test.sqlite"
        cls.db_url = f"sqlite:///{db_file}"
        os.environ["DATABASE_URL"] = cls.db_url

        # Reset singletons so tools module binds to this test DB.
        config_module._config = None
        db_engine._ENGINE = None
        cfg = get_config()

        alerts_table = cfg.get_table_name("alerts")
        articles_table = cfg.get_table_name("articles")
        prices_table = cfg.get_table_name("prices")
        themes_table = cfg.get_table_name("article_themes")
        prices_hourly_table = cfg.get_table_name("prices_hourly")

        a_id = cfg.get_column("alerts", "id")
        a_ticker = cfg.get_column("alerts", "ticker")
        a_status = cfg.get_column("alerts", "status")
        a_isin = cfg.get_column("alerts", "isin")
        a_start = cfg.get_column("alerts", "start_date")
        a_end = cfg.get_column("alerts", "end_date")

        ar_id = cfg.get_column("articles", "id")
        ar_isin = cfg.get_column("articles", "isin")
        ar_date = cfg.get_column("articles", "created_date")
        ar_title = cfg.get_column("articles", "title")
        ar_summary = cfg.get_column("articles", "summary")
        ar_theme = cfg.get_column("articles", "theme")
        ar_impact = cfg.get_column("articles", "impact_score")
        ar_label = cfg.get_column("articles", "impact_label")

        th_art_id = cfg.get_column("article_themes", "art_id")
        th_theme = cfg.get_column("article_themes", "theme")
        th_summary = cfg.get_column("article_themes", "summary")
        th_analysis = cfg.get_column("article_themes", "analysis")
        th_p1 = cfg.get_column("article_themes", "p1_prominence")

        p_ticker = cfg.get_column("prices", "ticker")
        p_date = cfg.get_column("prices", "date")
        p_close = cfg.get_column("prices", "close")

        ph_ticker = cfg.get_column("prices_hourly", "ticker")
        ph_date = cfg.get_column("prices_hourly", "date")
        ph_open = cfg.get_column("prices_hourly", "open")
        ph_high = cfg.get_column("prices_hourly", "high")
        ph_low = cfg.get_column("prices_hourly", "low")
        ph_close = cfg.get_column("prices_hourly", "close")
        ph_volume = cfg.get_column("prices_hourly", "volume")

        seed_engine = create_engine(cls.db_url, future=True)
        with seed_engine.begin() as conn:
            conn.execute(
                text(
                    f'''
                    CREATE TABLE "{alerts_table}" (
                        "{a_id}" INTEGER PRIMARY KEY,
                        "{a_ticker}" TEXT,
                        "{a_status}" TEXT,
                        "{a_isin}" TEXT,
                        "{a_start}" TEXT,
                        "{a_end}" TEXT
                    )
                    '''
                )
            )
            conn.execute(
                text(
                    f'''
                    CREATE TABLE "{articles_table}" (
                        "{ar_id}" INTEGER PRIMARY KEY,
                        "{ar_isin}" TEXT,
                        "{ar_date}" TEXT,
                        "{ar_title}" TEXT,
                        "{ar_summary}" TEXT,
                        "{ar_theme}" TEXT,
                        "{ar_impact}" REAL,
                        "{ar_label}" TEXT
                    )
                    '''
                )
            )
            conn.execute(
                text(
                    f'''
                    CREATE TABLE "{prices_table}" (
                        "{p_ticker}" TEXT,
                        "{p_date}" TEXT,
                        "{p_close}" REAL
                    )
                    '''
                )
            )
            conn.execute(
                text(
                    f'''
                    CREATE TABLE "{themes_table}" (
                        "{th_art_id}" INTEGER,
                        "{th_theme}" TEXT,
                        "{th_summary}" TEXT,
                        "{th_analysis}" TEXT,
                        "{th_p1}" TEXT
                    )
                    '''
                )
            )
            conn.execute(
                text(
                    f'''
                    CREATE TABLE "{prices_hourly_table}" (
                        "{ph_ticker}" TEXT,
                        "{ph_date}" TEXT,
                        "{ph_open}" REAL,
                        "{ph_high}" REAL,
                        "{ph_low}" REAL,
                        "{ph_close}" REAL,
                        "{ph_volume}" INTEGER
                    )
                    '''
                )
            )

            conn.execute(
                text(
                    f'''
                    INSERT INTO "{alerts_table}" ("{a_id}", "{a_ticker}", "{a_status}", "{a_isin}", "{a_start}", "{a_end}")
                    VALUES (1, 'HEMO.L', 'NEEDS_REVIEW', 'GB00BQL0M815', '2025-08-15', '2025-08-29')
                    '''
                )
            )
            conn.execute(
                text(
                    f'''
                    INSERT INTO "{articles_table}" ("{ar_id}", "{ar_isin}", "{ar_date}", "{ar_title}", "{ar_summary}", "{ar_theme}", "{ar_impact}", "{ar_label}")
                    VALUES (1001, 'GB00BQL0M815', '2025-08-28 00:39:05+00:00', 'Sample title', 'Sample summary', 'MACRO_SECTOR', 2.1, 'Medium')
                    '''
                )
            )
            conn.execute(
                text(
                    f'''
                    INSERT INTO "{prices_table}" ("{p_ticker}", "{p_date}", "{p_close}")
                    VALUES ('HEMO.L', '2025-08-28', 130.13)
                    '''
                )
            )
            conn.execute(
                text(
                    f'''
                    INSERT INTO "{themes_table}" ("{th_art_id}", "{th_theme}", "{th_summary}", "{th_analysis}", "{th_p1}")
                    VALUES (1001, 'MACRO_SECTOR', 'AI summary', 'AI analysis', 'L')
                    '''
                )
            )
            conn.execute(
                text(
                    f'''
                    INSERT INTO "{prices_hourly_table}" ("{ph_ticker}", "{ph_date}", "{ph_open}", "{ph_high}", "{ph_low}", "{ph_close}", "{ph_volume}")
                    VALUES ('HEMO.L', '2025-08-28 01:00:00', 129.0, 131.0, 128.5, 130.0, 100000)
                    '''
                )
            )

        # Import tools after DB seed/reset so module-level engine binds correctly.
        import backend.agent_v2.tools as tools_module

        cls.tools = importlib.reload(tools_module)
        cls.cfg = cfg

    @classmethod
    def tearDownClass(cls):
        from backend import config as config_module
        from backend.db import engine as db_engine

        db_engine._ENGINE = None
        config_module._config = None
        os.environ.pop("DATABASE_URL", None)
        cls._tmp_dir.cleanup()

    def _invoke_execute_sql(self, query: str) -> dict:
        raw = self.tools.execute_sql.invoke({"query": query})
        return json.loads(raw)

    def test_execute_sql_reads_all_core_tables(self):
        tables = [
            self.cfg.get_table_name("alerts"),
            self.cfg.get_table_name("articles"),
            self.cfg.get_table_name("prices"),
            self.cfg.get_table_name("article_themes"),
            self.cfg.get_table_name("prices_hourly"),
        ]
        for table_name in tables:
            with self.subTest(table=table_name):
                payload = self._invoke_execute_sql(
                    f'SELECT COUNT(*) AS n FROM "{table_name}"'
                )
                self.assertTrue(payload["ok"])
                self.assertGreaterEqual(payload["data"][0]["n"], 1)

    def test_execute_sql_rewrites_logical_columns(self):
        payload = self._invoke_execute_sql("SELECT id, ticker FROM alerts LIMIT 1")
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["meta"].get("query_rewritten"))
        self.assertEqual(len(payload["data"]), 1)

    def test_execute_sql_rewrite_is_table_aware_for_close_column(self):
        payload = self._invoke_execute_sql(
            "SELECT date, close FROM prices_hourly WHERE ticker = 'HEMO.L' LIMIT 1"
        )
        self.assertTrue(payload["ok"])
        self.assertEqual(len(payload["data"]), 1)
        row = payload["data"][0]
        self.assertIn("close", row)
        self.assertEqual(row["close"], 130.0)

    def test_execute_sql_rejects_non_select(self):
        payload = self._invoke_execute_sql("UPDATE alerts SET status='DISMISS'")
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "READ_ONLY_ENFORCED")

    def test_execute_sql_returns_db_error_for_invalid_column(self):
        payload = self._invoke_execute_sql("SELECT definitely_missing_col FROM alerts")
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "DB_ERROR")
        self.assertIn("DB_SCHEMA_REFERENCE.yaml", payload["error"]["message"])


if __name__ == "__main__":
    unittest.main()

import unittest
from unittest.mock import patch

import pandas as pd
from sqlalchemy import (
    Column,
    Date,
    Float,
    MetaData,
    String,
    Table,
    create_engine,
    select,
)

from ts_pit.services import price_cache


class _FakeConfig:
    def get_table_name(self, table_key):
        if table_key == "prices":
            return "prices"
        raise KeyError(table_key)

    def get_column(self, table_key, column_key):
        if table_key != "prices":
            raise KeyError(table_key)
        mapping = {
            "ticker": "ticker",
            "date": "date",
            "open": "open",
            "high": "high",
            "low": "low",
            "close": "close",
            "volume": "volume",
            "industry": "industry",
        }
        return mapping[column_key]


class PriceCacheTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        self.metadata = MetaData()
        self.prices = Table(
            "prices",
            self.metadata,
            Column("ticker", String),
            Column("date", Date),
            Column("open", Float),
            Column("high", Float),
            Column("low", Float),
            Column("close", Float),
            Column("volume", Float),
            Column("industry", String),
        )
        self.metadata.create_all(self.engine)

    def test_upsert_price_rows_coerces_iso_string_to_python_date_for_date_column(self):
        hist = pd.DataFrame(
            [
                {
                    "Date": "2025-10-09",
                    "Open": 145.05,
                    "High": 145.18,
                    "Low": 144.12,
                    "Close": 144.88,
                    "Volume": 11989400.0,
                }
            ]
        )

        with (
            patch.object(price_cache, "config", _FakeConfig()),
            patch.object(price_cache, "engine", self.engine),
            patch.object(price_cache, "get_table", return_value=self.prices),
        ):
            price_cache.upsert_price_rows(None, "XLK", hist, "ETF")

        with self.engine.connect() as conn:
            row = conn.execute(select(self.prices)).mappings().first()

        self.assertIsNotNone(row)
        self.assertEqual(str(row["date"]), "2025-10-09")
        self.assertEqual(row["ticker"], "XLK")


if __name__ == "__main__":
    unittest.main()

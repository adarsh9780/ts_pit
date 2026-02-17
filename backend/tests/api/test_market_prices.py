import unittest
from unittest.mock import patch

from sqlalchemy import Column, Float, MetaData, String, Table, create_engine

from ts_pit.api.routers import market
from ts_pit import config as app_config


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

    def get_sector_etf_mapping(self):
        return {"Technology": "XLK"}


class _FakeTicker:
    def __init__(self, _symbol):
        self.info = {"sector": "Technology"}


class MarketPricesTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        self.metadata = MetaData()
        self.prices = Table(
            "prices",
            self.metadata,
            Column("ticker", String),
            Column("date", String),
            Column("open", Float),
            Column("high", Float),
            Column("low", Float),
            Column("close", Float),
            Column("volume", Float),
            Column("industry", String),
        )
        self.metadata.create_all(self.engine)
        with self.engine.begin() as conn:
            conn.execute(
                self.prices.insert(),
                [
                    {
                        "ticker": "AAPL",
                        "date": "2026-01-10",
                        "open": 190.0,
                        "high": 194.0,
                        "low": 189.0,
                        "close": 193.0,
                        "volume": 1000.0,
                        "industry": "Consumer Electronics",
                    }
                ],
            )

    def test_get_prices_uses_default_period_for_ticker_and_etf(self):
        with (
            patch.object(market, "engine", self.engine),
            patch.object(market, "config", _FakeConfig()),
            patch.object(app_config, "config", _FakeConfig()),
            patch.object(market, "get_table", return_value=self.prices),
            patch.object(market, "remap_row", side_effect=lambda row, _table: row),
            patch.object(market.yf, "Ticker", _FakeTicker),
            patch.object(
                market,
                "fetch_and_cache_prices",
                side_effect=lambda t, p, *args, **kwargs: ("2026-01-01", t),
            ) as mocked_fetch,
        ):
            market.get_prices("AAPL", period=None)

        self.assertGreaterEqual(mocked_fetch.call_count, 2)
        self.assertEqual(mocked_fetch.call_args_list[0].args[0], "AAPL")
        self.assertEqual(mocked_fetch.call_args_list[0].args[1], "1y")
        self.assertEqual(mocked_fetch.call_args_list[1].args[0], "XLK")
        self.assertEqual(mocked_fetch.call_args_list[1].args[1], "1y")

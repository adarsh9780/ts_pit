from __future__ import annotations

from sqlalchemy import Text, and_, cast, func, inspect, select, update

from ..config import get_config
from ..db import get_engine
from .db_helpers import get_table


config = get_config()
engine = get_engine()


def _price_cols():
    table_name = config.get_table_name("prices")
    ticker_col = config.get_column("prices", "ticker")
    date_col = config.get_column("prices", "date")
    open_col = config.get_column("prices", "open")
    high_col = config.get_column("prices", "high")
    low_col = config.get_column("prices", "low")
    close_col = config.get_column("prices", "close")
    volume_col = config.get_column("prices", "volume")
    industry_col = config.get_column("prices", "industry")
    return {
        "table": table_name,
        "ticker": ticker_col,
        "date": date_col,
        "open": open_col,
        "high": high_col,
        "low": low_col,
        "close": close_col,
        "volume": volume_col,
        "industry": industry_col,
    }


def validate_price_schema(cursor=None):
    c = _price_cols()
    rows = inspect(engine).get_columns(c["table"])
    if not rows:
        raise RuntimeError(
            f'Missing required table "{c["table"]}". Run schema setup/migrations before using price cache.'
        )

    existing_cols = {row["name"] for row in rows}
    required_cols = [
        c["ticker"],
        c["date"],
        c["open"],
        c["high"],
        c["low"],
        c["close"],
        c["volume"],
        c["industry"],
    ]
    missing = [col for col in required_cols if col not in existing_cols]
    if missing:
        joined = ", ".join(missing)
        raise RuntimeError(
            f'Price table "{c["table"]}" is missing required columns: {joined}.'
        )


def needs_fetch(cursor, ticker: str, start_str: str) -> bool:
    c = _price_cols()
    prices = get_table(c["table"])
    stmt = select(func.min(cast(prices.c[c["date"]], Text)).label("min_date")).where(
        cast(prices.c[c["ticker"]], Text) == str(ticker)
    )
    with engine.connect() as conn:
        row = conn.execute(stmt).mappings().first()
    min_date = row["min_date"] if row else None
    if min_date is None:
        return True
    return str(min_date) > str(start_str)


def has_missing_ohlc(cursor, ticker: str) -> bool:
    c = _price_cols()
    prices = get_table(c["table"])
    stmt = select(func.count().label("cnt")).where(
        and_(
            cast(prices.c[c["ticker"]], Text) == str(ticker),
            (prices.c[c["high"]].is_(None) | prices.c[c["low"]].is_(None)),
        )
    )
    with engine.connect() as conn:
        row = conn.execute(stmt).mappings().first()
    return bool(row and row["cnt"] > 0)


def clear_ticker_prices(cursor, ticker: str):
    c = _price_cols()
    prices = get_table(c["table"])
    with engine.begin() as conn:
        conn.execute(
            prices.delete().where(cast(prices.c[c["ticker"]], Text) == str(ticker))
        )


def upsert_price_rows(cursor, ticker: str, hist, industry: str):
    c = _price_cols()
    prices = get_table(c["table"])
    data_to_insert: list[dict[str, object]] = []
    for _, r in hist.iterrows():
        data_to_insert.append(
            {
                c["ticker"]: ticker,
                c["date"]: r["Date"],
                c["open"]: r["Open"],
                c["high"]: r["High"],
                c["low"]: r["Low"],
                c["close"]: r["Close"],
                c["volume"]: r["Volume"],
                c["industry"]: industry,
            }
        )

    if not data_to_insert:
        return

    date_values = [str(item[c["date"]]) for item in data_to_insert]
    existing_stmt = select(cast(prices.c[c["date"]], Text).label("date")).where(
        and_(
            cast(prices.c[c["ticker"]], Text) == str(ticker),
            cast(prices.c[c["date"]], Text).in_(date_values),
        )
    )
    with engine.connect() as conn:
        existing_dates = {row["date"] for row in conn.execute(existing_stmt).mappings().all()}

    to_insert = [item for item in data_to_insert if str(item[c["date"]]) not in existing_dates]
    if not to_insert:
        return

    with engine.begin() as conn:
        conn.execute(prices.insert(), to_insert)


def get_alert_isin_for_ticker(cursor, ticker: str) -> str | None:
    alerts_table = config.get_table_name("alerts")
    ticker_col_alerts = config.get_column("alerts", "ticker")
    isin_col_alerts = config.get_column("alerts", "isin")
    alerts = get_table(alerts_table)
    stmt = (
        select(cast(alerts.c[isin_col_alerts], Text).label(isin_col_alerts))
        .where(cast(alerts.c[ticker_col_alerts], Text) == str(ticker))
        .limit(1)
    )
    with engine.connect() as conn:
        row = conn.execute(stmt).mappings().first()
    if row and row[isin_col_alerts]:
        return row[isin_col_alerts]
    return None


def update_alert_ticker(cursor, old_ticker: str, new_ticker: str, isin: str):
    alerts_table = config.get_table_name("alerts")
    ticker_col_alerts = config.get_column("alerts", "ticker")
    isin_col_alerts = config.get_column("alerts", "isin")
    alerts = get_table(alerts_table)
    stmt = (
        update(alerts)
        .where(cast(alerts.c[isin_col_alerts], Text) == str(isin))
        .where(cast(alerts.c[ticker_col_alerts], Text) == str(old_ticker))
        .values({ticker_col_alerts: new_ticker})
    )
    with engine.begin() as conn:
        conn.execute(stmt)

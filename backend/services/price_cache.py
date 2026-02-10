from __future__ import annotations

from ..config import get_config


config = get_config()


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


def validate_price_schema(cursor):
    c = _price_cols()
    cursor.execute(f'PRAGMA table_info("{c["table"]}")')
    rows = cursor.fetchall()
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
    cursor.execute(
        f'SELECT MIN("{c["date"]}") as min_date FROM "{c["table"]}" WHERE "{c["ticker"]}" = ?',
        (ticker,),
    )
    row = cursor.fetchone()
    if row["min_date"] is None:
        return True
    return row["min_date"] > start_str


def has_missing_ohlc(cursor, ticker: str) -> bool:
    c = _price_cols()
    cursor.execute(
        f'SELECT COUNT(*) as cnt FROM "{c["table"]}" '
        f'WHERE "{c["ticker"]}" = ? AND ("{c["high"]}" IS NULL OR "{c["low"]}" IS NULL)',
        (ticker,),
    )
    row = cursor.fetchone()
    return bool(row and row["cnt"] > 0)


def clear_ticker_prices(cursor, ticker: str):
    c = _price_cols()
    cursor.execute(f'DELETE FROM "{c["table"]}" WHERE "{c["ticker"]}" = ?', (ticker,))


def upsert_price_rows(cursor, ticker: str, hist, industry: str):
    c = _price_cols()
    data_to_insert = []
    for _, r in hist.iterrows():
        data_to_insert.append(
            (
                ticker,
                r["Date"],
                r["Open"],
                r["High"],
                r["Low"],
                r["Close"],
                r["Volume"],
                industry,
            )
        )

    cursor.executemany(
        f'''
        INSERT OR IGNORE INTO "{c["table"]}"
        ("{c["ticker"]}", "{c["date"]}", "{c["open"]}", "{c["high"]}", "{c["low"]}", "{c["close"]}", "{c["volume"]}", "{c["industry"]}")
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''',
        data_to_insert,
    )


def get_alert_isin_for_ticker(cursor, ticker: str) -> str | None:
    alerts_table = config.get_table_name("alerts")
    ticker_col_alerts = config.get_column("alerts", "ticker")
    isin_col_alerts = config.get_column("alerts", "isin")
    cursor.execute(
        f'SELECT "{isin_col_alerts}" FROM "{alerts_table}" WHERE "{ticker_col_alerts}" = ?',
        (ticker,),
    )
    row = cursor.fetchone()
    if row and row[isin_col_alerts]:
        return row[isin_col_alerts]
    return None


def update_alert_ticker(cursor, old_ticker: str, new_ticker: str, isin: str):
    alerts_table = config.get_table_name("alerts")
    ticker_col_alerts = config.get_column("alerts", "ticker")
    isin_col_alerts = config.get_column("alerts", "isin")
    cursor.execute(
        f'UPDATE "{alerts_table}" SET "{ticker_col_alerts}" = ? WHERE "{isin_col_alerts}" = ? AND "{ticker_col_alerts}" = ?',
        (new_ticker, isin, old_ticker),
    )

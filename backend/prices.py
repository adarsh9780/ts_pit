from __future__ import annotations

from .database import get_db_connection
from .logger import logprint
from .services.market_provider import (
    fetch_industry,
    fetch_price_history,
    get_ticker_from_isin,
    resolve_period_window,
)
from .services.price_cache import (
    clear_ticker_prices,
    get_alert_isin_for_ticker,
    has_missing_ohlc,
    needs_fetch,
    upsert_price_rows,
    update_alert_ticker,
    validate_price_schema,
)


def fetch_and_cache_prices(
    ticker: str,
    period: str,
    custom_start: str = None,
    custom_end: str = None,
    is_etf: bool = False,
):
    """
    Fetch missing OHLCV data from yfinance and cache it in DB.
    Keeps the original function contract used by routes/tools.
    """
    start_str, end_str = resolve_period_window(period, custom_start, custom_end)

    conn = get_db_connection()
    cursor = conn.cursor()
    validate_price_schema(cursor)

    should_fetch = needs_fetch(cursor, ticker, start_str)
    if not should_fetch and has_missing_ohlc(cursor, ticker):
        logprint(
            "Re-fetching prices due to missing OHLC values",
            level="INFO",
            ticker=ticker,
        )
        clear_ticker_prices(cursor, ticker)
        conn.commit()
        should_fetch = True

    if should_fetch:
        logprint("Fetching prices from yfinance", level="INFO", ticker=ticker)
        try:
            hist = fetch_price_history(ticker, period, start_str, end_str)

            if hist.empty and not is_etf:
                logprint("No history returned, attempting ISIN ticker resolution", level="WARNING", ticker=ticker)
                isin = get_alert_isin_for_ticker(cursor, ticker)
                if isin:
                    new_ticker = get_ticker_from_isin(isin)
                    if new_ticker and new_ticker != ticker:
                        logprint(
                            "Resolved ticker from ISIN",
                            level="INFO",
                            old_ticker=ticker,
                            new_ticker=new_ticker,
                            isin=isin,
                        )
                        update_alert_ticker(cursor, ticker, new_ticker, isin)
                        conn.commit()
                        conn.close()
                        return fetch_and_cache_prices(
                            new_ticker, period, custom_start, custom_end, is_etf
                        )

            if not hist.empty:
                industry = fetch_industry(ticker, is_etf)
                upsert_price_rows(cursor, ticker, hist, industry)
                conn.commit()
        except Exception as e:
            logprint("Price fetch/cache failed", level="ERROR", ticker=ticker, error=str(e))

    conn.close()
    return start_str, ticker

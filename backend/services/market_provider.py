from __future__ import annotations

from datetime import datetime
from typing import Optional

import pandas as pd
import requests
import yfinance as yf

from ..logger import logprint


def get_ticker_from_isin(isin: str) -> str | None:
    """Resolve a Yahoo ticker symbol for a given ISIN."""
    url = "https://query2.finance.yahoo.com/v1/finance/search"
    params = {"q": isin, "quotesCount": 1, "newsCount": 0}
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        )
    }

    try:
        response = requests.get(url, params=params, headers=headers, timeout=20)
        data = response.json()
        if "quotes" in data and data["quotes"]:
            return data["quotes"][0].get("symbol")
    except Exception as e:
        logprint("ISIN lookup failed", level="ERROR", isin=isin, error=str(e))
    return None


def resolve_period_window(period: str, custom_start: str | None, custom_end: str | None) -> tuple[str, str]:
    """Resolve request window into YYYY-MM-DD start/end strings."""
    if custom_start and custom_end:
        return custom_start, custom_end

    end_date = datetime.now()
    if period == "1mo":
        start_date = end_date - pd.DateOffset(months=1)
    elif period == "3mo":
        start_date = end_date - pd.DateOffset(months=3)
    elif period == "6mo":
        start_date = end_date - pd.DateOffset(months=6)
    elif period == "1y":
        start_date = end_date - pd.DateOffset(years=1)
    elif period == "ytd":
        start_date = datetime(end_date.year, 1, 1)
    elif period == "max":
        start_date = datetime(1900, 1, 1)
    else:
        start_date = end_date - pd.DateOffset(months=1)

    return start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")


def fetch_price_history(ticker: str, period: str, start_str: str, end_str: str):
    """Fetch OHLCV history from yfinance."""
    if period == "max":
        hist = yf.Ticker(ticker).history(period="max")
    else:
        hist = yf.Ticker(ticker).history(start=start_str, end=end_str)

    if hist.empty:
        return hist

    hist = hist.reset_index()
    hist["Date"] = hist["Date"].dt.strftime("%Y-%m-%d")
    return hist


def fetch_industry(ticker: str, is_etf: bool) -> str:
    """Fetch industry metadata for a ticker."""
    if is_etf:
        return "ETF"

    try:
        info = yf.Ticker(ticker).info
        return info.get("industry", "Unknown")
    except Exception as e:
        logprint("Industry lookup failed", level="WARNING", ticker=ticker, error=str(e))
        return "Unknown"


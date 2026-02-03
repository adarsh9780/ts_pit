import yfinance as yf
import requests
import pandas as pd
from datetime import datetime
from .database import get_db_connection
from .config import get_config

config = get_config()


def get_ticker_from_isin(isin: str) -> str | None:
    """
    Fetches the Yahoo Finance Ticker symbol for a given ISIN.
    """
    url = "https://query2.finance.yahoo.com/v1/finance/search"
    params = {"q": isin, "quotesCount": 1, "newsCount": 0}

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }

    try:
        response = requests.get(url, params=params, headers=headers)
        data = response.json()

        # Check if we got any quotes back
        if "quotes" in data and len(data["quotes"]) > 0:
            return data["quotes"][0]["symbol"]  # Return the first matching ticker
        else:
            return None
    except Exception as e:
        print(f"Error looking up ISIN {isin}: {e}")
        return None


def fetch_and_cache_prices(
    ticker: str,
    period: str,
    custom_start: str = None,
    custom_end: str = None,
    is_etf: bool = False,
):
    """Fetches missing price data from yfinance and caches it in the database."""
    # Convert period to start date
    end_date = datetime.now()
    start_date = None

    if custom_start and custom_end:
        start_str = custom_start
        end_str = custom_end
    else:
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
            start_date = datetime(1900, 1, 1)  # Effectively max
        else:
            start_date = end_date - pd.DateOffset(months=1)  # Default

        start_str = start_date.strftime("%Y-%m-%d")
        end_str = end_date.strftime("%Y-%m-%d")

    conn = get_db_connection()
    cursor = conn.cursor()

    # Get table and column names from config
    table_name = config.get_table_name("prices")
    ticker_col = config.get_column("prices", "ticker")
    date_col = config.get_column("prices", "date")
    open_col = config.get_column("prices", "open")
    high_col = config.get_column("prices", "high")
    low_col = config.get_column("prices", "low")
    close_col = config.get_column("prices", "close")
    volume_col = config.get_column("prices", "volume")
    industry_col = config.get_column("prices", "industry")

    # Ensure table exists with high/low columns for candlestick charts
    create_table_query = f'''
        CREATE TABLE IF NOT EXISTS "{table_name}" (
            "{ticker_col}" TEXT,
            "{date_col}" TEXT,
            "{open_col}" REAL,
            "{high_col}" REAL,
            "{low_col}" REAL,
            "{close_col}" REAL,
            "{volume_col}" INTEGER,
            "{industry_col}" TEXT,
            PRIMARY KEY ("{ticker_col}", "{date_col}")
        )
    '''
    cursor.execute(create_table_query)
    conn.commit()

    # Migration: Add high/low columns to existing tables (SQLite ignores if column exists)
    try:
        cursor.execute(f'ALTER TABLE "{table_name}" ADD COLUMN "{high_col}" REAL')
        conn.commit()
    except:
        pass  # Column already exists
    try:
        cursor.execute(f'ALTER TABLE "{table_name}" ADD COLUMN "{low_col}" REAL')
        conn.commit()
    except:
        pass  # Column already exists

    # Check if we have data for this range
    cursor.execute(
        f'SELECT MIN("{date_col}") as min_date, MAX("{date_col}") as max_date '
        f'FROM "{table_name}" WHERE "{ticker_col}" = ?',
        (ticker,),
    )
    row = cursor.fetchone()

    need_fetch = False
    if row["min_date"] is None:
        need_fetch = True
    else:
        db_min = row["min_date"]
        # If DB start is significantly after requested start, fetch more.
        if db_min > start_str:
            need_fetch = True

    # Check if existing data is missing high/low (needed for candlestick charts)
    if not need_fetch:
        cursor.execute(
            f'SELECT COUNT(*) as cnt FROM "{table_name}" '
            f'WHERE "{ticker_col}" = ? AND ("{high_col}" IS NULL OR "{low_col}" IS NULL)',
            (ticker,),
        )
        missing_row = cursor.fetchone()
        if missing_row and missing_row["cnt"] > 0:
            # Delete old data and re-fetch with high/low
            print(
                f"Re-fetching {ticker} to get high/low data for candlestick charts..."
            )
            cursor.execute(
                f'DELETE FROM "{table_name}" WHERE "{ticker_col}" = ?', (ticker,)
            )
            conn.commit()
            need_fetch = True

    if need_fetch:
        print(f"Fetching {ticker} from yfinance...")
        try:
            # Fetch data from yfinance
            if period == "max":
                hist = yf.Ticker(ticker).history(period="max")
            else:
                hist = yf.Ticker(ticker).history(start=start_str, end=end_str)

            if hist.empty and not is_etf:
                print(f"No data for {ticker}, trying ISIN lookup...")
                # Attempt to find ISIN and lookup correct ticker
                alerts_table = config.get_table_name("alerts")
                ticker_col_alerts = config.get_column("alerts", "ticker")
                isin_col_alerts = config.get_column("alerts", "isin")

                cursor.execute(
                    f'SELECT "{isin_col_alerts}" FROM "{alerts_table}" WHERE "{ticker_col_alerts}" = ?',
                    (ticker,),
                )
                row = cursor.fetchone()

                if row and row[isin_col_alerts]:
                    isin = row[isin_col_alerts]
                    new_ticker = get_ticker_from_isin(isin)

                    if new_ticker and new_ticker != ticker:
                        print(
                            f"Found new ticker for ISIN {isin}: {ticker} -> {new_ticker}"
                        )
                        # Update alerts table with new ticker
                        cursor.execute(
                            f'UPDATE "{alerts_table}" SET "{ticker_col_alerts}" = ? WHERE "{isin_col_alerts}" = ?',
                            (new_ticker, isin),
                        )
                        conn.commit()
                        conn.close()  # Close before recursive call

                        # Recursive call with new ticker
                        return fetch_and_cache_prices(
                            new_ticker, period, custom_start, custom_end, is_etf
                        )

            if not hist.empty:
                hist = hist.reset_index()
                # Ensure Date is string
                hist["Date"] = hist["Date"].dt.strftime("%Y-%m-%d")

                # Get industry info if not ETF
                industry = "Unknown"
                if not is_etf:
                    try:
                        # yfinance .info can raise exceptions or return partial data
                        ticker_obj = yf.Ticker(ticker)
                        # Accessing info property triggers the network call that might fail
                        info = ticker_obj.info
                        industry = info.get("industry", "Unknown")
                        print(
                            f"DEBUG: Successfully fetched industry for {ticker}: {industry}"
                        )
                    except Exception as e:
                        # Don't let metadata failure stop price data caching
                        print(
                            f"DEBUG: PATCH ACTIVE - Could not fetch industry for {ticker}. Error: {e}"
                        )
                        print(
                            f"DEBUG: Proceeding with industry='Unknown' to prevent crash."
                        )
                        industry = "Unknown"
                else:
                    industry = "ETF"

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
                            r["Volume"],  # Corrected to r
                            industry,
                        )
                    )

                # UPSERT logic with high/low columns
                cursor.executemany(
                    f'''
                    INSERT OR IGNORE INTO "{table_name}" 
                    ("{ticker_col}", "{date_col}", "{open_col}", "{high_col}", "{low_col}", "{close_col}", "{volume_col}", "{industry_col}")
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                    data_to_insert,
                )
                conn.commit()
        except Exception as e:
            print(f"Error fetching data for {ticker}: {e}")
            import traceback

            traceback.print_exc()

    conn.close()
    return start_str, ticker

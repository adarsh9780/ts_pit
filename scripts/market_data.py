import sqlite3
import yfinance as yf
import pandas as pd
import requests
import sys
from pathlib import Path

# Add backend directory to path to import config
# We allow this ONLY for config/config.yaml access, not logic code
current_dir = Path(__file__).resolve().parent
backend_dir = current_dir.parent / "backend"
sys.path.append(str(backend_dir))

try:
    from config import get_config
except ImportError:
    # Fallback if running from root
    sys.path.append(str(current_dir.parent))
    from backend.config import get_config

config = get_config()


def get_ticker_from_isin(isin: str) -> str | None:
    """
    Fetches the Yahoo Finance Ticker symbol for a given ISIN.
    Standalone version for scripts.
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
            return data["quotes"][0]["symbol"]
        else:
            return None
    except Exception as e:
        print(f"Error looking up ISIN {isin}: {e}")
        return None


def ensure_hourly_table(conn):
    """Ensure prices_hourly table exists based on config."""
    cursor = conn.cursor()

    # Get table config
    try:
        table_name = config.get_table_name("prices_hourly")
        cols = config.get_columns("prices_hourly")
    except KeyError:
        print("Error: 'prices_hourly' not configured in config.yaml")
        return None

    # explicit column names from config
    ticker_col = cols["ticker"]
    date_col = cols["date"]
    open_col = cols["open"]
    high_col = cols["high"]
    low_col = cols["low"]
    close_col = cols["close"]
    volume_col = cols["volume"]

    create_query = f'''
        CREATE TABLE IF NOT EXISTS "{table_name}" (
            "{ticker_col}" TEXT,
            "{date_col}" TEXT,
            "{open_col}" REAL,
            "{high_col}" REAL,
            "{low_col}" REAL,
            "{close_col}" REAL,
            "{volume_col}" INTEGER,
            PRIMARY KEY ("{ticker_col}", "{date_col}")
        )
    '''
    cursor.execute(create_query)

    # Add impact columns to articles if they don't exist
    articles_table = config.get_table_name("articles")
    try:
        cursor.execute(f'ALTER TABLE "{articles_table}" ADD COLUMN impact_score REAL')
    except sqlite3.OperationalError:
        pass  # Column exists

    try:
        cursor.execute(f'ALTER TABLE "{articles_table}" ADD COLUMN impact_label TEXT')
    except sqlite3.OperationalError:
        pass  # Column exists

    conn.commit()
    return table_name


def fetch_hourly_data_with_fallback(conn, ticker, force_refresh=False):
    """
    Fetch 730 days of 1h data for ticker and cache it.
    INCLUDES FALLBACK: if data is missing, resolve ticker from ISIN and fetch prices,
    but keep data keyed by the original alert ticker.
    """
    table_name = config.get_table_name("prices_hourly")
    cols = config.get_columns("prices_hourly")
    ticker_col = cols["ticker"]
    date_col_db = cols["date"]

    # 1. Check Cache
    if not force_refresh:
        cursor = conn.cursor()
        cursor.execute(
            f'SELECT COUNT(*) FROM "{table_name}" WHERE "{ticker_col}" = ?', (ticker,)
        )
        count = cursor.fetchone()[0]

        if count > 100:
            print(f"  -> Found {count} cached hourly candles for {ticker}")
            return ticker  # Return the working ticker

    print(f"  -> Fetching ONE HOUR data for {ticker} (Last 730 days)...")

    requested_ticker = ticker

    # 2. Try Fetch
    try:
        df = yf.Ticker(ticker).history(period="730d", interval="1h")

        # 3. Fallback Logic if Empty
        if df.empty:
            print(f"  !! No 1h data found for {ticker}")

            # Try ISIN lookup, but do not mutate alerts.ticker.
            alerts_table = config.get_table_name("alerts")
            t_ticker = config.get_column("alerts", "ticker")
            t_isin = config.get_column("alerts", "isin")

            cursor = conn.cursor()
            cursor.execute(
                f'SELECT "{t_isin}" FROM "{alerts_table}" WHERE "{t_ticker}" = ? LIMIT 1',
                (ticker,),
            )
            row = cursor.fetchone()

            if row:
                isin = row[0]
                print(f"  -> Attempting fallback lookup for ISIN: {isin}")
                new_ticker = get_ticker_from_isin(isin)

                if new_ticker and new_ticker != ticker:
                    print(f"  -> FOUND NEW TICKER: {ticker} -> {new_ticker}")
                    df = yf.Ticker(new_ticker).history(period="730d", interval="1h")
                    if df.empty:
                        print(f"  !! No 1h data found for fallback ticker {new_ticker}")
                        return None
                    # Keep original alert ticker stable; cache fetched data under it.
                    ticker = requested_ticker
                else:
                    return None
            else:
                return None

        # 4. Process Data if found
        df = df.reset_index()

        source_date_col = None
        for col in ["Datetime", "Date"]:
            if col in df.columns:
                source_date_col = col
                break

        if not source_date_col:
            print(
                f"  !! Error: Could not find Date/Datetime column. Columns: {df.columns.tolist()}"
            )
            return None

        # Convert to string
        if hasattr(df[source_date_col].dt, "strftime"):
            df["DateStr"] = df[source_date_col].dt.strftime("%Y-%m-%d %H:%M:%S")
        else:
            df["DateStr"] = pd.to_datetime(df[source_date_col]).dt.strftime(
                "%Y-%m-%d %H:%M:%S"
            )

        data_to_insert = []
        for _, row in df.iterrows():
            data_to_insert.append(
                (
                    ticker,
                    row["DateStr"],
                    row["Open"],
                    row["High"],
                    row["Low"],
                    row["Close"],
                    int(row["Volume"]),
                )
            )

        # Clear old if refresh
        if force_refresh:
            cursor = conn.cursor()
            cursor.execute(
                f'DELETE FROM "{table_name}" WHERE "{ticker_col}" = ?', (ticker,)
            )
            conn.commit()

        cursor = conn.cursor()
        cursor.executemany(
            f'''
            INSERT OR IGNORE INTO "{table_name}" 
            ("{ticker_col}", "{date_col_db}", "{cols["open"]}", "{cols["high"]}", "{cols["low"]}", "{cols["close"]}", "{cols["volume"]}")
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''',
            data_to_insert,
        )
        conn.commit()
        print(f"  -> Cached {len(data_to_insert)} candles for {ticker}.")

        # Always return requested/original ticker used by downstream queries.
        return requested_ticker

    except Exception as e:
        print(f"  !! Error fetching {ticker}: {e}")
        return None

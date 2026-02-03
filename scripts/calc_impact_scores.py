import os
import sys
import sqlite3
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path

# Add backend directory to path to import config
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


def get_db_connection():
    db_path = config.get_database_path()
    return sqlite3.connect(db_path)


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


def fetch_hourly_data(conn, ticker, force_refresh=False):
    """Fetch 730 days of 1h data for ticker and cache it."""
    table_name = config.get_table_name("prices_hourly")
    cols = config.get_columns("prices_hourly")
    ticker_col = cols["ticker"]
    date_col_db = cols["date"]

    # Check if we have data
    if not force_refresh:
        cursor = conn.cursor()
        cursor.execute(
            f'SELECT COUNT(*) FROM "{table_name}" WHERE "{ticker_col}" = ?', (ticker,)
        )
        count = cursor.fetchone()[0]

        if count > 100:
            print(f"  -> Found {count} cached hourly candles for {ticker}")
            return

    print(f"  -> Fetching ONE HOUR data for {ticker} (Last 730 days)...")
    try:
        # yfinance allows max 730 days for 1h interval
        df = yf.Ticker(ticker).history(period="730d", interval="1h")

        if df.empty:
            print(f"  !! No 1h data found for {ticker}")
            return

        df = df.reset_index()

        # Check available columns to avoid KeyError
        source_date_col = None
        for col in ["Datetime", "Date"]:
            if col in df.columns:
                source_date_col = col
                break

        if not source_date_col:
            print(
                f"  !! Error: Could not find Date/Datetime column. Columns: {df.columns.tolist()}"
            )
            return

        # Convert timezone-aware to naive string (UTC-like)
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

        # Delete existing if forcing refresh
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
        print(f"  -> Cached {len(data_to_insert)} candles.")

    except Exception as e:
        print(f"  !! Error fetching {ticker}: {e}")


def calculate_z_score(conn, ticker, article_date_str):
    """
    Calculate Z-Score for the article.
    Window: 10 days BEFORE article date.
    Event: Candle immediately AFTER article date.
    """
    table_name = config.get_table_name("prices_hourly")
    cols = config.get_columns("prices_hourly")

    # Parse article date
    # Handle varying formats if necessary, assuming ISO or near-ISO
    try:
        art_dt = pd.to_datetime(article_date_str)
    except:
        return None, None

    # Define Window
    start_window = (art_dt - timedelta(days=10)).strftime("%Y-%m-%d %H:%M:%S")
    end_window = art_dt.strftime("%Y-%m-%d %H:%M:%S")

    # Query Data
    query = f'''
        SELECT "{cols["date"]}", "{cols["close"]}", "{cols["open"]}"
        FROM "{table_name}"
        WHERE "{cols["ticker"]}" = ? 
        AND "{cols["date"]}" >= ? 
        AND "{cols["date"]}" <= ?
        ORDER BY "{cols["date"]}" ASC
    '''
    df_window = pd.read_sql_query(
        query, conn, params=(ticker, start_window, end_window)
    )

    if len(df_window) < 10:
        return None, "Insufficient Data"

    # Calculate Hourly Returns: (Close - Open) / Open
    # Or (Close_t - Close_t-1) / Close_t-1 ??
    # User specified: "Magnitude of the candle" -> associated with specific time.
    # Let's use (Close - Open) / Open for purely intraday hourly moves,
    # OR (Close - PrevClose) / PrevClose.
    # Given the prompt "Time of the news to the Magnitude of the candle",
    # (Close - Open) / Open is the specific move OF that hour.

    df_window["return"] = (
        df_window[cols["close"]] - df_window[cols["open"]]
    ) / df_window[cols["open"]]

    # Baseline Volatility (Std Dev of returns)
    volatility = df_window["return"].std()

    if volatility == 0 or np.isnan(volatility):
        return 0, "Flatline"

    # Get Event Candle (The one that contains or is immediately after the news)
    # We look for the first candle where date >= article_date
    query_event = f'''
        SELECT "{cols["date"]}", "{cols["close"]}", "{cols["open"]}"
        FROM "{table_name}"
        WHERE "{cols["ticker"]}" = ? 
        AND "{cols["date"]}" >= ? 
        ORDER BY "{cols["date"]}" ASC
        LIMIT 1
    '''
    cursor = conn.cursor()
    cursor.execute(query_event, (ticker, article_date_str))
    event_row = cursor.fetchone()

    if not event_row:
        return None, "No Price Data"

    event_open = event_row[2]
    event_close = event_row[1]

    event_return = (event_close - event_open) / event_open

    # Z-Score
    z_score = abs(event_return) / volatility

    # Labeling
    if z_score < 2.0:
        label = "Noise"
    elif z_score < 4.0:
        label = "Significant"
    else:
        label = "Extreme"

    return round(z_score, 2), label


import argparse


def main():
    parser = argparse.ArgumentParser(
        description="Calculate post-publication market impact scores."
    )
    parser.add_argument(
        "--force-refresh_prices",
        action="store_true",
        help="Force re-download of hourly price data",
    )
    parser.add_argument(
        "--calc-all",
        action="store_true",
        help="Recalculate impacts even for articles that already have scores",
    )
    args = parser.parse_args()

    print("Starting Post-Publication Impact Analysis...")
    conn = get_db_connection()
    ensure_hourly_table(conn)

    # 1. Get all Alerts (to link ISIN -> Ticker)
    alerts_table = config.get_table_name("alerts")
    # need columns config

    # Since config.get_column returns the DB column name
    # We need to map UI key -> DB key from config
    # Easier to just select all and look up by mapped name?
    # Or just select explicit known keys from config

    t_isin = config.get_column("alerts", "isin")
    t_ticker = config.get_column("alerts", "ticker")

    df_alerts = pd.read_sql_query(
        f'SELECT "{t_isin}" as isin, "{t_ticker}" as ticker FROM "{alerts_table}"', conn
    )

    # Map ISIN -> Ticker
    isin_map = dict(zip(df_alerts["isin"], df_alerts["ticker"]))
    print(f"Loaded {len(isin_map)} alerts.")

    # 2. Get all Articles
    articles_table = config.get_table_name("articles")
    c_id = config.get_column("articles", "id")
    c_isin = config.get_column("articles", "isin")
    c_date = config.get_column("articles", "created_date")
    c_impact = "impact_score"

    print("Fetching articles...")
    if args.calc_all:
        query_arts = f'SELECT "{c_id}" as id, "{c_isin}" as isin, "{c_date}" as date FROM "{articles_table}"'
    else:
        query_arts = f'SELECT "{c_id}" as id, "{c_isin}" as isin, "{c_date}" as date FROM "{articles_table}" WHERE impact_score IS NULL'

    try:
        df_articles = pd.read_sql_query(query_arts, conn)
    except Exception as e:
        print(f"Error reading articles (maybe column missing?): {e}")
        return

    print(f"Found {len(df_articles)} articles needing analysis.")

    # 3. Process
    # Cache for tickers we've already checked in this run
    checked_tickers = set()

    updates = []

    for index, row in df_articles.iterrows():
        isin = row["isin"]
        ticker = isin_map.get(isin)

        if not ticker:
            continue

        # Ensure Data (Once per ticker)
        if ticker not in checked_tickers:
            fetch_hourly_data(conn, ticker, force_refresh=args.force_refresh_prices)
            checked_tickers.add(ticker)

        # Calculate
        z, label = calculate_z_score(conn, ticker, row["date"])

        if z is not None:
            updates.append((z, label, row["id"]))
            if index % 10 == 0:
                print(
                    f"  Processed {index + 1}/{len(df_articles)}: {ticker} Z={z} ({label})"
                )

    # 4. Bulk Update
    if updates:
        print(f"Updating {len(updates)} articles in database...")
        cursor = conn.cursor()
        cursor.executemany(
            f'UPDATE "{articles_table}" SET impact_score = ?, impact_label = ? WHERE "{c_id}" = ?',
            updates,
        )
        conn.commit()

    print("Done!")
    conn.close()


if __name__ == "__main__":
    main()

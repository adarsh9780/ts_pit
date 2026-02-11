import sys
import sqlite3
import pandas as pd
import numpy as np
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
    conn = sqlite3.connect(db_path)
    # OPTIMIZATION: Use WAL mode
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


from market_data import ensure_hourly_table, fetch_hourly_data_with_fallback

# ensure_hourly_table and fetch_hourly_data moved to market_data.py


def _load_hourly_prices(conn, ticker):
    """Load hourly candles for one ticker, sorted by timestamp."""
    table_name = config.get_table_name("prices_hourly")
    cols = config.get_columns("prices_hourly")
    query = f'''
        SELECT "{cols["date"]}" AS dt, "{cols["open"]}" AS open_px, "{cols["close"]}" AS close_px
        FROM "{table_name}"
        WHERE "{cols["ticker"]}" = ?
        ORDER BY "{cols["date"]}" ASC
    '''
    return pd.read_sql_query(query, conn, params=(ticker,))


def _vectorized_impacts_for_ticker(df_prices, df_articles, baseline_days=10, min_baseline_points=10):
    """
    Vectorized impact calculation for one ticker.
    Returns DataFrame with columns: id, impact_score, impact_label
    """
    if df_prices.empty or df_articles.empty:
        return pd.DataFrame(columns=["id", "impact_score", "impact_label"])

    prices = (
        df_prices.assign(
            dt=pd.to_datetime(df_prices["dt"], utc=True, errors="coerce"),
            open_px=pd.to_numeric(df_prices["open_px"], errors="coerce"),
            close_px=pd.to_numeric(df_prices["close_px"], errors="coerce"),
        )
        .dropna(subset=["dt", "open_px", "close_px"])
        .query("open_px != 0")
        .sort_values("dt")
        .assign(ret=lambda d: (d["close_px"] - d["open_px"]) / d["open_px"])
        .reset_index(drop=True)
    )
    if prices.empty:
        return pd.DataFrame(columns=["id", "impact_score", "impact_label"])

    articles = (
        df_articles.assign(article_dt=pd.to_datetime(df_articles["date"], utc=True, errors="coerce"))
        .dropna(subset=["article_dt"])
        .sort_values("article_dt")
        .reset_index(drop=True)
    )
    if articles.empty:
        return pd.DataFrame(columns=["id", "impact_score", "impact_label"])

    ts = prices["dt"].values.astype("datetime64[ns]")
    open_px = prices["open_px"].to_numpy(dtype=float)
    close_px = prices["close_px"].to_numpy(dtype=float)
    returns = prices["ret"].to_numpy(dtype=float)

    # Prefix sums allow O(1) window moments per article after O(n) preprocessing.
    csum = np.concatenate(([0.0], np.cumsum(returns)))
    csum2 = np.concatenate(([0.0], np.cumsum(returns * returns)))

    art_ts = articles["article_dt"].values.astype("datetime64[ns]")
    baseline_delta = np.timedelta64(int(baseline_days), "D")
    left = np.searchsorted(ts, art_ts - baseline_delta, side="left")
    right = np.searchsorted(ts, art_ts, side="right")  # inclusive of candle <= article_dt
    count = right - left

    baseline_ok = count >= min_baseline_points
    sum_r = csum[right] - csum[left]
    sum_r2 = csum2[right] - csum2[left]
    count_f = count.astype(float)
    with np.errstate(divide="ignore", invalid="ignore"):
        mean = sum_r / count_f
        var = (sum_r2 - (sum_r * sum_r) / count_f) / (count_f - 1.0)  # sample std (ddof=1)
    sigma = np.sqrt(var)

    event_idx = np.searchsorted(ts, art_ts, side="left")  # first candle >= article_dt
    has_event = event_idx < len(ts)

    event_return = np.full(len(articles), np.nan, dtype=float)
    valid_event_idx = event_idx[has_event]
    event_return[has_event] = (close_px[valid_event_idx] - open_px[valid_event_idx]) / open_px[
        valid_event_idx
    ]

    with np.errstate(divide="ignore", invalid="ignore"):
        z_score = np.abs(event_return) / sigma

    flatline = baseline_ok & has_event & ((sigma == 0) | np.isnan(sigma))
    z_score[flatline] = 0.0

    valid = baseline_ok & has_event
    labels = np.full(len(articles), "", dtype=object)
    labels[flatline] = "Flatline"
    non_flat = valid & ~flatline
    labels[non_flat & (z_score < 2.0)] = "Low"
    labels[non_flat & (z_score >= 2.0) & (z_score < 4.0)] = "Medium"
    labels[non_flat & (z_score >= 4.0)] = "High"

    out = articles.loc[valid, ["id"]].copy()
    out["impact_score"] = np.round(z_score[valid], 2)
    out["impact_label"] = labels[valid]
    return out


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

    print("🚀 Starting Impact Score Calculation...")

    # SAFETY: Create backup
    db_path = config.get_database_path()
    backup_path = f"{db_path}.bak_impact"
    try:
        import shutil

        print(f"📦 Creating backup at '{backup_path}'...")
        shutil.copy2(db_path, backup_path)
    except Exception as e:
        print(f"⚠️  Warning: Failed to create backup: {e}")

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

    # 3. Process in vectorized ticker batches
    df_articles = (
        df_articles.assign(ticker=df_articles["isin"].map(isin_map))
        .dropna(subset=["ticker", "date", "id"])
        .copy()
    )
    print(f"Eligible articles after ticker/date filtering: {len(df_articles)}")

    updates_df_list = []
    unique_tickers = sorted(df_articles["ticker"].dropna().unique().tolist())
    print(f"Tickers to process: {len(unique_tickers)}")

    for idx, ticker in enumerate(unique_tickers, start=1):
        resolved_ticker = fetch_hourly_data_with_fallback(
            conn, ticker, force_refresh=args.force_refresh_prices
        )
        if not resolved_ticker:
            continue

        df_prices = _load_hourly_prices(conn, resolved_ticker)
        df_ticker_articles = df_articles.query("ticker == @ticker")[["id", "date"]].copy()
        ticker_updates = _vectorized_impacts_for_ticker(df_prices, df_ticker_articles)
        if not ticker_updates.empty:
            updates_df_list.append(ticker_updates)
        if idx % 10 == 0 or idx == len(unique_tickers):
            print(f"  Processed tickers: {idx}/{len(unique_tickers)}")

    # 4. Bulk Update (Batched)
    updates = []
    if updates_df_list:
        updates_df = pd.concat(updates_df_list, ignore_index=True)
        updates = list(
            updates_df[["impact_score", "impact_label", "id"]].itertuples(index=False, name=None)
        )

    if updates:
        print(f"Updating {len(updates)} articles in database...")
        cursor = conn.cursor()

        batch_size = 1000
        total = len(updates)

        for i in range(0, total, batch_size):
            batch = updates[i : i + batch_size]
            cursor.executemany(
                f'UPDATE "{articles_table}" SET impact_score = ?, impact_label = ? WHERE "{c_id}" = ?',
                batch,
            )
            conn.commit()
            print(
                f"  -> Committed batch {i + 1}-{min(i + batch_size, total)} of {total}"
            )

    print("Done!")
    conn.close()


if __name__ == "__main__":
    main()

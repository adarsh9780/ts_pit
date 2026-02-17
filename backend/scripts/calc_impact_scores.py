import sys
import sqlite3
import os
import pandas as pd
import numpy as np
from pathlib import Path
import argparse
import time
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

# Add backend directory to path to import config
current_dir = Path(__file__).resolve().parent
backend_dir = current_dir.parent / "backend"
sys.path.append(str(backend_dir))

try:
    from ts_pit.config import get_config
except ImportError:
    # If running as script without package installed (dev mode fallback)
    import sys

    sys.path.append(str(backend_dir / "src"))
    from ts_pit.config import get_config

config = get_config()


def get_db_connection():
    db_path = config.get_database_path()
    conn = sqlite3.connect(db_path)
    # OPTIMIZATION: Use WAL mode
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
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


def _vectorized_impacts_for_ticker(
    df_prices, df_articles, baseline_days=10, min_baseline_points=10
):
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
        df_articles.assign(
            article_dt=pd.to_datetime(df_articles["date"], utc=True, errors="coerce")
        )
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
    right = np.searchsorted(
        ts, art_ts, side="right"
    )  # inclusive of candle <= article_dt
    count = right - left

    baseline_ok = count >= min_baseline_points
    sum_r = csum[right] - csum[left]
    sum_r2 = csum2[right] - csum2[left]
    count_f = count.astype(float)
    with np.errstate(divide="ignore", invalid="ignore"):
        mean = sum_r / count_f
        var = (sum_r2 - (sum_r * sum_r) / count_f) / (
            count_f - 1.0
        )  # sample std (ddof=1)
    sigma = np.sqrt(var)

    event_idx = np.searchsorted(ts, art_ts, side="left")  # first candle >= article_dt
    has_event = event_idx < len(ts)

    event_return = np.full(len(articles), np.nan, dtype=float)
    valid_event_idx = event_idx[has_event]
    event_return[has_event] = (
        close_px[valid_event_idx] - open_px[valid_event_idx]
    ) / open_px[valid_event_idx]

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


def _compute_updates_for_ticker(ticker, df_ticker_articles):
    conn = get_db_connection()
    try:
        df_prices = _load_hourly_prices(conn, ticker)
    finally:
        conn.close()
    return _vectorized_impacts_for_ticker(df_prices, df_ticker_articles)


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
    parser.add_argument(
        "--workers",
        type=int,
        default=max(1, min(8, (os.cpu_count() or 4))),
        help="Parallel workers for per-ticker compute stage",
    )
    args = parser.parse_args()

    print("🚀 Starting Impact Score Calculation...")
    t_total = time.time()

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
    t_read = time.time()
    if args.calc_all:
        query_arts = f'SELECT "{c_id}" as id, "{c_isin}" as isin, "{c_date}" as date FROM "{articles_table}"'
    else:
        query_arts = f'SELECT "{c_id}" as id, "{c_isin}" as isin, "{c_date}" as date FROM "{articles_table}" WHERE impact_score IS NULL'

    try:
        df_articles = pd.read_sql_query(query_arts, conn)
    except Exception as e:
        print(f"Error reading articles (maybe column missing?): {e}")
        return

    print(
        f"Found {len(df_articles)} articles needing analysis. (read in {time.time() - t_read:.2f}s)"
    )

    # 3. Process in vectorized ticker batches
    t_prepare = time.time()
    df_articles = (
        df_articles.assign(
            ticker=df_articles["isin"].map(isin_map),
            article_dt=pd.to_datetime(df_articles["date"], utc=True, errors="coerce"),
        )
        .dropna(subset=["ticker", "date", "id", "article_dt"])
        .copy()
    )
    print(
        f"Eligible articles after ticker/date filtering: {len(df_articles)} "
        f"(prepared in {time.time() - t_prepare:.2f}s)"
    )
    if df_articles.empty:
        print(f"Done! Total runtime: {time.time() - t_total:.2f}s")
        conn.close()
        return

    # 3a. Ensure hourly data for each ticker in required bounded range
    t_fetch = time.time()
    by_ticker = (
        df_articles.groupby("ticker", as_index=False)
        .agg(min_dt=("article_dt", "min"), max_dt=("article_dt", "max"))
        .reset_index(drop=True)
    )
    print(f"Tickers to process: {len(by_ticker)}")
    ready_tickers = []
    for idx, row in by_ticker.iterrows():
        ticker = row["ticker"]
        start_date = (row["min_dt"] - timedelta(days=10)).strftime("%Y-%m-%d %H:%M:%S")
        end_date = (row["max_dt"] + timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
        resolved_ticker = fetch_hourly_data_with_fallback(
            conn,
            ticker,
            force_refresh=args.force_refresh_prices,
            start_date=start_date,
            end_date=end_date,
        )
        if not resolved_ticker:
            continue
        ready_tickers.append(resolved_ticker)
        if (idx + 1) % 10 == 0 or (idx + 1) == len(by_ticker):
            print(f"  -> Hourly data ready: {idx + 1}/{len(by_ticker)} tickers")
    print(f"Hourly data phase done in {time.time() - t_fetch:.2f}s")
    if not ready_tickers:
        print(f"Done! Total runtime: {time.time() - t_total:.2f}s")
        conn.close()
        return

    # 3b. Parallel compute per ticker
    t_compute = time.time()
    updates_df_list = []
    workers = max(1, min(int(args.workers), len(ready_tickers)))
    print(f"Compute phase: using {workers} worker(s)")
    ticker_article_frames = {
        t: df_articles.query("ticker == @t")[["id", "date"]].copy()
        for t in ready_tickers
    }
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                _compute_updates_for_ticker, ticker, ticker_article_frames[ticker]
            ): ticker
            for ticker in ready_tickers
        }
        completed = 0
        for fut in as_completed(futures):
            ticker = futures[fut]
            try:
                ticker_updates = fut.result()
                if not ticker_updates.empty:
                    updates_df_list.append(ticker_updates)
            except Exception as e:
                print(f"  !! Compute failed for {ticker}: {e}")
            completed += 1
            if completed % 10 == 0 or completed == len(futures):
                print(f"  -> Computed {completed}/{len(futures)} tickers")
    print(f"Compute phase done in {time.time() - t_compute:.2f}s")

    # 4. Bulk Update (Batched)
    updates = []
    if updates_df_list:
        updates_df = pd.concat(updates_df_list, ignore_index=True)
        updates = list(
            updates_df[["impact_score", "impact_label", "id"]].itertuples(
                index=False, name=None
            )
        )

    if updates:
        print(f"Updating {len(updates)} articles in database...")
        cursor = conn.cursor()
        total = len(updates)
        load_batch_size = 2000
        write_t0 = time.time()

        cursor.execute("DROP TABLE IF EXISTS _tmp_impact_updates")
        cursor.execute(
            """
            CREATE TEMP TABLE _tmp_impact_updates (
                id TEXT PRIMARY KEY,
                impact_score REAL,
                impact_label TEXT
            )
            """
        )

        for i in range(0, total, load_batch_size):
            batch = updates[i : i + load_batch_size]
            cursor.executemany(
                "INSERT OR REPLACE INTO _tmp_impact_updates (impact_score, impact_label, id) VALUES (?, ?, ?)",
                batch,
            )
            print(
                f"  -> Staged {min(i + load_batch_size, total)}/{total} updates...",
                flush=True,
            )

        cursor.execute(
            f'''
            UPDATE "{articles_table}"
            SET impact_score = (
                    SELECT u.impact_score
                    FROM _tmp_impact_updates u
                    WHERE u.id = CAST("{articles_table}"."{c_id}" AS TEXT)
                ),
                impact_label = (
                    SELECT u.impact_label
                    FROM _tmp_impact_updates u
                    WHERE u.id = CAST("{articles_table}"."{c_id}" AS TEXT)
                )
            WHERE CAST("{articles_table}"."{c_id}" AS TEXT) IN (SELECT id FROM _tmp_impact_updates)
              AND (
                    IFNULL(impact_score, -1e308) != IFNULL(
                        (SELECT u.impact_score FROM _tmp_impact_updates u WHERE u.id = CAST("{articles_table}"."{c_id}" AS TEXT)),
                        -1e308
                    )
                 OR IFNULL(impact_label, '') != IFNULL(
                        (SELECT u.impact_label FROM _tmp_impact_updates u WHERE u.id = CAST("{articles_table}"."{c_id}" AS TEXT)),
                        ''
                    )
              )
            '''
        )
        changed_rows = cursor.rowcount
        conn.commit()
        cursor.execute("DROP TABLE IF EXISTS _tmp_impact_updates")
        print(
            f"  -> Applied {changed_rows} changed rows in {time.time() - write_t0:.2f}s",
            flush=True,
        )

    print(f"Done! Total runtime: {time.time() - t_total:.2f}s")
    conn.close()


if __name__ == "__main__":
    main()

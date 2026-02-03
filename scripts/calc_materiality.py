import os
import sys
import sqlite3
import pandas as pd
import numpy as np
import re
import argparse
from datetime import datetime
from pathlib import Path

# Add backend directory to path to import config
current_dir = Path(__file__).resolve().parent
backend_dir = current_dir.parent / "backend"
sys.path.append(str(backend_dir))

try:
    from config import get_config
except ImportError:
    sys.path.append(str(current_dir.parent))
    from backend.config import get_config

config = get_config()


def get_db_connection():
    db_path = config.get_database_path()
    return sqlite3.connect(db_path)


def process_chunk(df, alerts_table):
    """
    Vectorized calculation of P1, P2, P3 for a chunk of articles.
    """
    if df.empty:
        return []

    # ==========================================================================
    # 2. Temporal Proximity (P2) - VECTORIZED
    # ==========================================================================
    # Convert all dates to datetime and normalize to timezone-naive to avoid subtraction errors
    df["dt_art"] = pd.to_datetime(
        df["art_created_date"], errors="coerce"
    ).dt.tz_localize(None)
    df["dt_start"] = pd.to_datetime(df["start_date"], errors="coerce").dt.tz_localize(
        None
    )
    df["dt_end"] = pd.to_datetime(df["end_date"], errors="coerce").dt.tz_localize(None)

    # Calculate total duration and elapsed time in seconds
    df["duration"] = (df["dt_end"] - df["dt_start"]).dt.total_seconds()
    df["elapsed"] = (df["dt_art"] - df["dt_start"]).dt.total_seconds()

    # Handle cases where art_date is on or after alert end
    df["ratio"] = np.where(
        df["dt_art"] >= df["dt_end"], 1.0, df["elapsed"] / df["duration"]
    )
    df["ratio"] = df["ratio"].fillna(0)  # Fallback for unparseable dates

    # Map to H/M/L
    df["p2"] = "L"
    df.loc[df["ratio"] >= 0.66, "p2"] = "H"
    df.loc[(df["ratio"] < 0.66) & (df["ratio"] >= 0.33), "p2"] = "M"

    # ==========================================================================
    # 3. Thematic Priority (P3) - VECTORIZED
    # ==========================================================================
    # Prefer AI theme, fallback to original theme
    df["final_theme"] = (
        df["ai_theme"].fillna(df["orig_theme"]).fillna("UNCATEGORIZED").str.upper()
    )

    high_themes_regex = "|".join(
        [
            "EARNINGS_ANNOUNCEMENT",
            "M_AND_A",
            "DIVIDEND_CORP_ACTION",
            "PRODUCT_TECH_LAUNCH",
            "COMMERCIAL_CONTRACTS",
        ]
    )
    med_themes_regex = "|".join(
        [
            "LEGAL_REGULATORY",
            "EXECUTIVE_CHANGE",
            "OPERATIONAL_CRISIS",
            "CAPITAL_STRUCTURE",
        ]
    )

    df["p3"] = "L"
    df.loc[df["final_theme"].str.contains(med_themes_regex, na=False), "p3"] = "M"
    df.loc[df["final_theme"].str.contains(high_themes_regex, na=False), "p3"] = "H"

    # ==========================================================================
    # 1. Entity Prominence (P1) - MIXED (Requires regex loop per row but faster than manual iterrows)
    # ==========================================================================
    # P1 is the hardest to vectorize because each row has a different ticker/name pattern.
    # However, we can group by Ticker/Name to optimize if needed. For 20k, a simple map is fine.

    def get_p1(row):
        ticker = str(row.get("ticker") or "").strip().lower()
        name = str(row.get("instrument_name") or "").strip().lower()
        title = str(row.get("art_title") or "").lower()
        body = str(row.get("art_body") or "").lower()

        patterns = []
        if ticker:
            patterns.append(rf"\b{re.escape(ticker)}\b")
        if name:
            patterns.append(re.escape(name))

        if not patterns:
            return "L"

        regex = re.compile("|".join(patterns), re.IGNORECASE)
        if regex.search(title):
            return "H"

        lead = body.split("\n\n")[0] if "\n\n" in body else body[:500]
        if regex.search(lead):
            return "M"

        return "L"

    df["p1"] = df.apply(get_p1, axis=1)

    # Combine into Triplet
    df["materiality"] = df["p1"] + df["p2"] + df["p3"]

    return list(zip(df["materiality"], df["art_id"]))


def ensure_materiality_column(conn, table_name):
    """Adds materiality column if it doesn't exist."""
    cursor = conn.cursor()
    cursor.execute(f"PRAGMA table_info('{table_name}')")
    columns = [row[1] for row in cursor.fetchall()]
    if "materiality" not in columns:
        print(f"Adding 'materiality' column to '{table_name}'...")
        cursor.execute(f'ALTER TABLE "{table_name}" ADD COLUMN "materiality" TEXT')
        conn.commit()


def main():
    parser = argparse.ArgumentParser(description="Optimized Materiality Calculation")
    parser.add_argument("--force", action="store_true", help="Recalculate all articles")
    parser.add_argument(
        "--chunk-size", type=int, default=5000, help="Number of rows per chunk"
    )
    args = parser.parse_args()

    print(
        f"🚀 Starting Optimized Materiality Analysis (Force={args.force}, Chunk={args.chunk_size})..."
    )
    conn = get_db_connection()

    # Get column and table names from config
    alerts_table = config.get_table_name("alerts")
    isin_col = config.get_column("alerts", "isin")
    ticker_col = config.get_column("alerts", "ticker")
    name_col = config.get_column("alerts", "instrument_name")
    start_col = config.get_column("alerts", "start_date")
    end_col = config.get_column("alerts", "end_date")

    articles_table = config.get_table_name("articles")
    art_id_col = config.get_column("articles", "id")
    art_isin_col = config.get_column("articles", "isin")
    art_date_col = config.get_column("articles", "created_date")
    art_title_col = config.get_column("articles", "title")
    art_body_col = config.get_column("articles", "body")
    art_theme_col = config.get_column("articles", "theme")

    # Ensure table structure
    ensure_materiality_column(conn, articles_table)

    themes_table = config.get_table_name("article_themes")
    theme_art_id_col = config.get_column("article_themes", "art_id")
    theme_val_col = config.get_column("article_themes", "theme")

    # PREPARE JOIN QUERY
    # We join articles with alerts (for ticker/name/window) and themes (for AI theme)
    join_query = f'''
        SELECT 
            a."{art_id_col}" as art_id,
            a."{art_isin_col}" as isin,
            a."{art_date_col}" as art_created_date,
            a."{art_title_col}" as art_title,
            a."{art_body_col}" as art_body,
            a."{art_theme_col}" as orig_theme,
            al."{ticker_col}" as ticker,
            al."{name_col}" as instrument_name,
            al."{start_col}" as start_date,
            al."{end_col}" as end_date,
            t."{theme_val_col}" as ai_theme
        FROM "{articles_table}" a
        JOIN "{alerts_table}" al ON a."{art_isin_col}" = al."{isin_col}"
        LEFT JOIN "{themes_table}" t ON a."{art_id_col}" = t."{theme_art_id_col}"
    '''

    if not args.force:
        join_query += ' WHERE a."materiality" IS NULL'

    # PROCESSING IN CHUNKS
    total_processed = 0
    updates_to_save = []

    print("Fetching and processing data chunks...")
    for chunk in pd.read_sql(join_query, conn, chunksize=args.chunk_size):
        chunk_results = process_chunk(chunk, alerts_table)
        updates_to_save.extend(chunk_results)
        total_processed += len(chunk)
        print(f"  -> Processed {total_processed} articles...")

    # BULK UPDATE
    if updates_to_save:
        print(f"Applying {len(updates_to_save)} updates to database in batches...")
        cursor = conn.cursor()
        batch_size = 1000
        for i in range(0, len(updates_to_save), batch_size):
            batch = updates_to_save[i : i + batch_size]
            cursor.executemany(
                f'UPDATE "{articles_table}" SET "materiality" = ? WHERE "{art_id_col}" = ?',
                batch,
            )
            conn.commit()
            print(
                f"    Committed batch {i // batch_size + 1}/{len(updates_to_save) // batch_size + 1}"
            )
    else:
        print("No new articles to process.")

    print("✅ Optimized Materiality Analysis Complete!")
    conn.close()


if __name__ == "__main__":
    main()

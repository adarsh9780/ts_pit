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
    Vectorized calculation of P1 (Entity Prominence) ONLY.
    P2 (Time) and P3 (Theme) are now dynamic in backend.
    """
    if df.empty:
        return []

    # ==========================================================================
    # P1: Entity Prominence - MIXED (Requires regex loop per row but faster than manual iterrows)
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

    # Return only P1 along with ID
    return list(zip(df["p1"], df["art_id"]))


def ensure_columns(conn, table_name):
    """Adds p1_prominence column if it doesn't exist."""
    cursor = conn.cursor()
    cursor.execute(f"PRAGMA table_info('{table_name}')")
    columns = [row[1] for row in cursor.fetchall()]

    if "p1_prominence" not in columns:
        print(f"Adding 'p1_prominence' column to '{table_name}'...")
        cursor.execute(f'ALTER TABLE "{table_name}" ADD COLUMN "p1_prominence" TEXT')

    conn.commit()


def main():
    parser = argparse.ArgumentParser(description="Static Prominence Feature Extraction")
    parser.add_argument("--force", action="store_true", help="Recalculate all articles")
    parser.add_argument(
        "--chunk-size", type=int, default=5000, help="Number of rows per chunk"
    )
    args = parser.parse_args()

    print(
        f"🚀 Starting Static Prominence Analysis (Force={args.force}, Chunk={args.chunk_size})..."
    )
    conn = get_db_connection()

    # Get column and table names from config
    alerts_table = config.get_table_name("alerts")
    isin_col = config.get_column("alerts", "isin")
    ticker_col = config.get_column("alerts", "ticker")
    name_col = config.get_column("alerts", "instrument_name")

    articles_table = config.get_table_name("articles")
    art_id_col = config.get_column("articles", "id")
    art_isin_col = config.get_column("articles", "isin")
    art_title_col = config.get_column("articles", "title")
    art_body_col = config.get_column("articles", "body")
    art_theme_col = config.get_column("articles", "theme")

    # Ensure table structure
    ensure_columns(conn, articles_table)

    # PREPARE JOIN QUERY
    # We join articles with alerts loop up ticker/name for regex matching
    join_query = f'''
        SELECT 
            a."{art_id_col}" as art_id,
            a."{art_isin_col}" as isin,
            a."{art_title_col}" as art_title,
            a."{art_body_col}" as art_body,
            al."{ticker_col}" as ticker,
            al."{name_col}" as instrument_name
        FROM "{articles_table}" a
        JOIN "{alerts_table}" al ON a."{art_isin_col}" = al."{isin_col}"
    '''

    if not args.force:
        join_query += ' WHERE a."p1_prominence" IS NULL'

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
                f'UPDATE "{articles_table}" SET "p1_prominence" = ? WHERE "{art_id_col}" = ?',
                batch,
            )
            conn.commit()
            print(
                f"    Committed batch {i // batch_size + 1}/{len(updates_to_save) // batch_size + 1}"
            )
    else:
        print("No new articles to process.")

    print("✅ Static Prominence Analysis Complete!")
    conn.close()


if __name__ == "__main__":
    main()

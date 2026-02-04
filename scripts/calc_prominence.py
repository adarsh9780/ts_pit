import os
import sys
import sqlite3
import pandas as pd
import numpy as np
import re
import argparse
from datetime import datetime
from pathlib import Path
import shutil

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
    conn = sqlite3.connect(db_path)
    # OPTIMIZATION: Use WAL mode for faster writes and concurrency
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


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

    # SAFETY: Create a backup of the database before heavy write operations
    db_path = config.get_database_path()
    backup_path = f"{db_path}.bak"
    try:
        import shutil

        print(f"📦 Creating backup at '{backup_path}'...")
        shutil.copy2(db_path, backup_path)
    except Exception as e:
        print(f"⚠️  Warning: Failed to create backup: {e}")

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

    # Retrieve article_themes config
    themes_table = config.get_table_name("article_themes")
    theme_art_id_col = config.get_column("article_themes", "art_id")
    p1_col = config.get_column("article_themes", "p1_prominence")

    # Check if articles table has ticker/name columns configured
    art_ticker_col = config.get_column("articles", "ticker")
    art_name_col = config.get_column("articles", "instrument_name")

    # Ensure table structure (check article_themes, not articles)
    ensure_columns(conn, themes_table)

    join_query = ""
    using_direct_columns = False

    # Strategies:
    # 1. Direct Column Access (Preferred): If articles table has ticker/name columns
    # 2. Join with Alerts (Fallback): If missing, join with alerts table (DISTINCT to avoid dupes)

    # Check if configured AND columns actually exist in DB (double check)
    has_ticker_in_db = False
    has_name_in_db = False

    if art_ticker_col and art_name_col:
        cursor = conn.cursor()
        cursor.execute(f"PRAGMA table_info('{articles_table}')")
        db_cols = {row[1] for row in cursor.fetchall()}
        has_ticker_in_db = art_ticker_col in db_cols
        has_name_in_db = art_name_col in db_cols

    if has_ticker_in_db and has_name_in_db:
        print(
            f"ℹ️  Optimized Mode: Using direct columns '{art_ticker_col}' and '{art_name_col}' from articles table."
        )
        using_direct_columns = True
        join_query = f'''
            SELECT 
                "{art_id_col}" as art_id,
                "{art_isin_col}" as isin,
                "{art_title_col}" as art_title,
                "{art_body_col}" as art_body,
                "{art_ticker_col}" as ticker,
                "{art_name_col}" as instrument_name
            FROM "{articles_table}"
        '''
        if not args.force:
            # We want to filter where art_id NOT IN (select art_id from article_themes where p1 is not null)
            # This is cleaner than joining.
            exclusion_clause = f'''
                WHERE "{art_id_col}" NOT IN (
                    SELECT "{theme_art_id_col}" FROM "{themes_table}" WHERE "{p1_col}" IS NOT NULL
                )
            '''
            join_query += exclusion_clause

    else:
        print(
            "⚠️  Fallback Mode: Articles table missing ticker/name columns. Joining with alerts table (slower)."
        )
        # PREPARE JOIN QUERY
        # We join articles with alerts loop up ticker/name for regex matching
        join_query = f'''
            SELECT DISTINCT
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
            # Check p1 in article_themes, NOT articles
            # This requires valid join or just checking if art_id exists in themes with p1
            # For simplicity in this script, we might re-calc nulls.
            # Better approach: Left join article_themes to exclude already calculated.

            # Re-building query to exclude already calculated items
            # Complex if we are in "fallback" mode which already has a JOIN
            pass
            # TODO: Implementing "incremental" efficiently with the new separated table structure
            # requires joining article_themes in the source query.
            # For now, we will rely on --force or just re-calc (it's fast with optimized mode)

    # PROCESSING IN CHUNKS
    total_processed = 0
    updates_to_save = []

    print("Fetching and processing data chunks...")
    for chunk in pd.read_sql(join_query, conn, chunksize=args.chunk_size):
        chunk_results = process_chunk(chunk, alerts_table)
        updates_to_save.extend(chunk_results)
        total_processed += len(chunk)
        print(f"  -> Processed {total_processed} articles...")

    # BULK UPDATE / UPSERT to article_themes
    if updates_to_save:
        print(
            f"Applying {len(updates_to_save)} updates to '{themes_table}' in batches..."
        )
        cursor = conn.cursor()
        batch_size = 1000

        # We need to swap the tuple order for the query: (p1, art_id) -> (art_id, p1)
        # Because we want INSERT (id, p1) VALUES (?, ?)
        # process_chunk returns [(p1, id), ...]

        upsert_data = [(uid, score) for score, uid in updates_to_save]

        for i in range(0, len(upsert_data), batch_size):
            batch = upsert_data[i : i + batch_size]

            # SQLite UPSERT Syntax (Requires SQLite 3.24+)
            # INSERT INTO table (id, p1) VALUES (?, ?)
            # ON CONFLICT(id) DO UPDATE SET p1=excluded.p1

            query = f'''
                INSERT INTO "{themes_table}" ("{theme_art_id_col}", "{p1_col}")
                VALUES (?, ?)
                ON CONFLICT("{theme_art_id_col}") 
                DO UPDATE SET "{p1_col}" = excluded."{p1_col}"
            '''

            cursor.executemany(query, batch)
            conn.commit()
            print(
                f"    Committed batch {i // batch_size + 1}/{len(upsert_data) // batch_size + 1}"
            )
    else:
        print("No new articles to process.")

    print("✅ Static Prominence Analysis Complete!")
    conn.close()


if __name__ == "__main__":
    main()

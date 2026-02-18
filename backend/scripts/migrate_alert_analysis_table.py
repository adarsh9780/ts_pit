import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

try:
    from ts_pit.config import get_config
except ImportError:
    PROJECT_ROOT = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(PROJECT_ROOT / "src"))
    from ts_pit.config import get_config

config = get_config()

LEGACY_COLUMNS = [
    "narrative_theme",
    "narrative_summary",
    "summary_generated_at",
    "bullish_events",
    "bearish_events",
    "neutral_events",
    "recommendation",
    "recommendation_reason",
]


def quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(config.get_database_path())
    conn.row_factory = sqlite3.Row
    return conn


def ensure_alert_analysis_table(cursor: sqlite3.Cursor) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS "alert_analysis" (
            "id" INTEGER PRIMARY KEY AUTOINCREMENT,
            "alert_id" TEXT NOT NULL,
            "generated_at" TEXT NOT NULL,
            "source" TEXT NOT NULL DEFAULT 'legacy_backfill',
            "narrative_theme" TEXT,
            "narrative_summary" TEXT,
            "bullish_events" TEXT,
            "bearish_events" TEXT,
            "neutral_events" TEXT,
            "recommendation" TEXT,
            "recommendation_reason" TEXT
        )
        """
    )
    cursor.execute(
        'CREATE INDEX IF NOT EXISTS "idx_alert_analysis_alert_id_generated_at" '
        'ON "alert_analysis" ("alert_id", "generated_at" DESC)'
    )


def column_exists(cursor: sqlite3.Cursor, table_name: str, column_name: str) -> bool:
    cursor.execute(f"PRAGMA table_info({quote_ident(table_name)})")
    cols = [row["name"] for row in cursor.fetchall()]
    return column_name in cols


def main():
    parser = argparse.ArgumentParser(
        description="Create alert_analysis table and backfill from legacy alerts columns."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply changes. Without this flag, script runs in dry-run mode.",
    )
    args = parser.parse_args()

    alerts_table = config.get_table_name("alerts")
    alert_id_col = config.get_column("alerts", "id")

    conn = get_db_connection()
    cursor = conn.cursor()

    missing_legacy = [
        col for col in LEGACY_COLUMNS if not column_exists(cursor, alerts_table, col)
    ]
    if missing_legacy:
        print(
            "Legacy backfill columns missing in alerts table; they may have already been removed:"
        )
        print(", ".join(missing_legacy))

    if not args.apply:
        print("Dry-run:")
        print("- Would ensure table: alert_analysis")
        print(
            f"- Would backfill rows from {alerts_table} where any legacy analysis column has value"
        )
        conn.close()
        return

    ensure_alert_analysis_table(cursor)

    existing_cols = [
        col for col in LEGACY_COLUMNS if column_exists(cursor, alerts_table, col)
    ]
    if not existing_cols:
        print(
            "No legacy analysis columns found. Table created/verified; nothing to backfill."
        )
        conn.commit()
        conn.close()
        return

    select_cols = ", ".join(
        [quote_ident(alert_id_col)] + [quote_ident(c) for c in existing_cols]
    )
    cursor.execute(f"SELECT {select_cols} FROM {quote_ident(alerts_table)}")
    rows = cursor.fetchall()

    inserted = 0
    skipped = 0
    for row in rows:
        payload = dict(row)
        alert_id = str(payload.get(alert_id_col))
        if not alert_id:
            skipped += 1
            continue

        theme = payload.get("narrative_theme")
        summary = payload.get("narrative_summary")
        bullish = payload.get("bullish_events")
        bearish = payload.get("bearish_events")
        neutral = payload.get("neutral_events")
        recommendation = payload.get("recommendation")
        reason = payload.get("recommendation_reason")
        generated_at = (
            payload.get("summary_generated_at") or datetime.utcnow().isoformat()
        )

        has_any = any(
            value is not None and str(value).strip() != ""
            for value in [
                theme,
                summary,
                bullish,
                bearish,
                neutral,
                recommendation,
                reason,
            ]
        )
        if not has_any:
            skipped += 1
            continue

        cursor.execute(
            """
            INSERT INTO "alert_analysis" (
                "alert_id",
                "generated_at",
                "source",
                "narrative_theme",
                "narrative_summary",
                "bullish_events",
                "bearish_events",
                "neutral_events",
                "recommendation",
                "recommendation_reason"
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                alert_id,
                generated_at,
                "legacy_backfill",
                theme,
                summary,
                bullish,
                bearish,
                neutral,
                recommendation,
                reason,
            ),
        )
        inserted += 1

    conn.commit()
    conn.close()
    print(f"Backfill complete. Inserted={inserted}, skipped={skipped}")


if __name__ == "__main__":
    main()

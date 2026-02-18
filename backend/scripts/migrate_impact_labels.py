import argparse
import shutil
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

LEGACY_TO_CANONICAL = {
    "NOISE": "Low",
    "SIGNIFICANT": "Medium",
    "EXTREME": "High",
}


def get_db_connection() -> sqlite3.Connection:
    db_path = config.get_database_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


def get_distribution(cursor: sqlite3.Cursor, table_name: str, impact_col: str):
    cursor.execute(
        f'''
        SELECT "{impact_col}" AS impact_label, COUNT(*) AS count
        FROM "{table_name}"
        GROUP BY "{impact_col}"
        ORDER BY count DESC
        '''
    )
    return [dict(row) for row in cursor.fetchall()]


def main():
    parser = argparse.ArgumentParser(
        description="Normalize legacy impact_label values to canonical Low/Medium/High."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply updates. Without this flag, script runs in dry-run mode.",
    )
    args = parser.parse_args()

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"Running impact-label migration in {mode} mode")

    conn = get_db_connection()
    cursor = conn.cursor()

    articles_table = config.get_table_name("articles")
    impact_col = config.get_column("articles", "impact_label")

    print("\nCurrent impact_label distribution:")
    before = get_distribution(cursor, articles_table, impact_col)
    for row in before:
        print(f"  - {row['impact_label']!r}: {row['count']}")

    # Preview counts that would be updated.
    planned_updates = []
    for legacy, canonical in LEGACY_TO_CANONICAL.items():
        cursor.execute(
            f'''
            SELECT COUNT(*) AS cnt
            FROM "{articles_table}"
            WHERE UPPER(TRIM(COALESCE("{impact_col}", ''))) = ?
            ''',
            (legacy,),
        )
        count = cursor.fetchone()["cnt"]
        if count:
            planned_updates.append((legacy, canonical, count))

    print("\nPlanned updates:")
    if not planned_updates:
        print("  - No legacy labels found. Nothing to change.")
    else:
        for legacy, canonical, count in planned_updates:
            print(f"  - {legacy} -> {canonical}: {count} rows")

    if not args.apply:
        conn.close()
        print("\nDry-run complete. Re-run with --apply to execute updates.")
        return

    db_path = Path(config.get_database_path())
    backup_path = db_path.with_suffix(
        db_path.suffix
        + f".bak_impact_labels_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    )
    shutil.copy2(db_path, backup_path)
    print(f"\nBackup created: {backup_path}")

    total_updated = 0
    for legacy, canonical, _ in planned_updates:
        cursor.execute(
            f'''
            UPDATE "{articles_table}"
            SET "{impact_col}" = ?
            WHERE UPPER(TRIM(COALESCE("{impact_col}", ''))) = ?
            ''',
            (canonical, legacy),
        )
        total_updated += cursor.rowcount

    conn.commit()
    print(f"\nApplied updates: {total_updated} rows")

    print("\nUpdated impact_label distribution:")
    after = get_distribution(cursor, articles_table, impact_col)
    for row in after:
        print(f"  - {row['impact_label']!r}: {row['count']}")

    conn.close()
    print("\nMigration complete.")


if __name__ == "__main__":
    main()

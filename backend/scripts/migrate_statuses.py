import sqlite3
import sys
from pathlib import Path
import argparse

# Add backend directory to path to import config
current_dir = Path(__file__).resolve().parent
backend_dir = current_dir.parent / "backend"
sys.path.append(str(backend_dir))

try:
    from config import get_config
except ImportError:
    sys.path.append(str(current_dir.parent))
    from backend.config import get_config


def main():
    parser = argparse.ArgumentParser(
        description="Normalize alert status values using config status aliases."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show planned changes without writing to the database.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail if any status cannot be normalized to a valid status.",
    )
    args = parser.parse_args()

    config = get_config()
    db_path = config.get_database_path()
    alerts_table = config.get_table_name("alerts")
    status_col = config.get_column("alerts", "status")
    valid_statuses = set(config.get_valid_statuses())

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute(
        f'SELECT "{status_col}", COUNT(*) FROM "{alerts_table}" GROUP BY "{status_col}"'
    )
    distinct_statuses = cursor.fetchall()

    if not distinct_statuses:
        print("No status values found.")
        conn.close()
        return

    invalid = []
    updates = []

    print("Current status distribution:")
    for raw_status, count in distinct_statuses:
        normalized = config.normalize_status(raw_status)
        valid = normalized in valid_statuses
        marker = "OK" if valid else "INVALID"
        print(f"  - {raw_status} -> {normalized} ({count}) [{marker}]")

        if raw_status != normalized and valid:
            updates.append((normalized, raw_status))
        elif not valid:
            invalid.append((raw_status, normalized, count))

    if invalid:
        print("\nInvalid statuses detected:")
        for raw, norm, count in invalid:
            print(f"  - raw='{raw}', normalized='{norm}', count={count}")
        if args.strict:
            conn.close()
            raise SystemExit("Aborting due to invalid statuses in strict mode.")

    if not updates:
        print("\nNo status normalization updates required.")
        conn.close()
        return

    print("\nPlanned updates:")
    for normalized, raw_status in updates:
        print(f"  - {raw_status} -> {normalized}")

    if args.dry_run:
        print("\nDry run complete. No changes written.")
        conn.close()
        return

    for normalized, raw_status in updates:
        cursor.execute(
            f'UPDATE "{alerts_table}" SET "{status_col}" = ? WHERE "{status_col}" = ?',
            (normalized, raw_status),
        )

    conn.commit()
    conn.close()
    print("\nStatus migration complete.")


if __name__ == "__main__":
    main()

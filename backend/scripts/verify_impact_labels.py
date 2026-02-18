import sqlite3
import sys
from pathlib import Path

try:
    from ts_pit.config import get_config
except ImportError:
    PROJECT_ROOT = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(PROJECT_ROOT / "src"))
    from ts_pit.config import get_config

config = get_config()

CANONICAL = {"Low", "Medium", "High"}


def get_db_connection() -> sqlite3.Connection:
    db_path = config.get_database_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def main():
    conn = get_db_connection()
    cursor = conn.cursor()

    table_name = config.get_table_name("articles")
    impact_col = config.get_column("articles", "impact_label")

    cursor.execute(f'SELECT COUNT(*) AS total FROM "{table_name}"')
    total_rows = cursor.fetchone()["total"]

    cursor.execute(
        f'''
        SELECT "{impact_col}" AS impact_label, COUNT(*) AS count
        FROM "{table_name}"
        GROUP BY "{impact_col}"
        ORDER BY count DESC
        '''
    )
    rows = cursor.fetchall()

    print("Impact Label Verification")
    print("=========================")
    print(f"Table: {table_name}")
    print(f"Column: {impact_col}")
    print(f"Total rows: {total_rows}")
    print("\nDistribution:")

    unknown = []
    canonical_count = 0

    for row in rows:
        label = row["impact_label"]
        count = row["count"]
        label_str = "" if label is None else str(label).strip()
        is_canonical = label_str in CANONICAL
        status = "OK" if is_canonical else "UNKNOWN"
        print(f"  - {label!r}: {count} [{status}]")
        if is_canonical:
            canonical_count += count
        else:
            unknown.append((label, count))

    print("\nSummary:")
    print(f"  - Canonical rows (Low/Medium/High): {canonical_count}")
    print(f"  - Non-canonical rows: {total_rows - canonical_count}")

    if unknown:
        print("\nUnknown labels detected:")
        for label, count in unknown:
            print(f"  - {label!r}: {count}")
        print("\nResult: FAIL (non-canonical labels present)")
        conn.close()
        sys.exit(1)

    print("\nResult: PASS (all labels are canonical)")
    conn.close()


if __name__ == "__main__":
    main()

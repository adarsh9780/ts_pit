import argparse
import shutil
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

TARGET_COLUMNS = [
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
    db_path = config.get_database_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


def get_columns(cursor: sqlite3.Cursor, table_name: str) -> list[dict]:
    cursor.execute(f"PRAGMA table_info({quote_ident(table_name)})")
    return [dict(row) for row in cursor.fetchall()]


def column_exists(cursor: sqlite3.Cursor, table_name: str, column_name: str) -> bool:
    cols = get_columns(cursor, table_name)
    return any(c["name"].lower() == column_name.lower() for c in cols)


def drop_column_with_rebuild(
    conn: sqlite3.Connection, table_name: str, column_name: str
) -> bool:
    cursor = conn.cursor()
    cols = get_columns(cursor, table_name)
    keep_cols = [c for c in cols if c["name"].lower() != column_name.lower()]
    if len(keep_cols) == len(cols):
        return False

    temp_table = f"{table_name}__old_drop_{column_name}"
    keep_names = [c["name"] for c in keep_cols]

    col_defs = []
    pk_cols = []
    for col in keep_cols:
        name = quote_ident(col["name"])
        col_type = col["type"] or "TEXT"
        not_null = " NOT NULL" if col["notnull"] else ""
        default = (
            f" DEFAULT {col['dflt_value']}" if col["dflt_value"] is not None else ""
        )
        col_defs.append(f"{name} {col_type}{not_null}{default}")
        if col["pk"]:
            pk_cols.append((col["pk"], col["name"]))

    pk_sql = ""
    if pk_cols:
        pk_cols.sort(key=lambda x: x[0])
        pk_sql = ", PRIMARY KEY (" + ", ".join(quote_ident(c[1]) for c in pk_cols) + ")"

    create_sql = (
        f"CREATE TABLE {quote_ident(table_name)} ({', '.join(col_defs)}{pk_sql})"
    )
    keep_cols_sql = ", ".join(quote_ident(c) for c in keep_names)

    cursor.execute("BEGIN")
    cursor.execute(
        f"ALTER TABLE {quote_ident(table_name)} RENAME TO {quote_ident(temp_table)}"
    )
    cursor.execute(create_sql)
    cursor.execute(
        f"INSERT INTO {quote_ident(table_name)} ({keep_cols_sql}) "
        f"SELECT {keep_cols_sql} FROM {quote_ident(temp_table)}"
    )
    cursor.execute(f"DROP TABLE {quote_ident(temp_table)}")
    conn.commit()
    return True


def remove_column(conn: sqlite3.Connection, table_name: str, column_name: str) -> bool:
    cursor = conn.cursor()
    if not column_exists(cursor, table_name, column_name):
        return False

    # Try direct DROP COLUMN first (supported in modern SQLite).
    try:
        cursor.execute(
            f"ALTER TABLE {quote_ident(table_name)} DROP COLUMN {quote_ident(column_name)}"
        )
        conn.commit()
        return True
    except sqlite3.OperationalError:
        return drop_column_with_rebuild(conn, table_name, column_name)


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Remove legacy analysis columns from alerts table after migration to "
            "a dedicated alert_analysis table."
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply changes. Without this flag, script runs in dry-run mode.",
    )
    args = parser.parse_args()

    table_name = config.get_table_name("alerts")
    conn = get_db_connection()
    cursor = conn.cursor()

    existing_to_remove = [
        col for col in TARGET_COLUMNS if column_exists(cursor, table_name, col)
    ]
    if not existing_to_remove:
        print(f"No-op: none of target columns exist in {table_name}.")
        conn.close()
        return

    print(f"Found removable columns in {table_name}: {', '.join(existing_to_remove)}")
    if not args.apply:
        print("Dry-run complete. Re-run with --apply to remove them.")
        conn.close()
        return

    db_path = Path(config.get_database_path())
    backup_path = db_path.with_suffix(db_path.suffix + ".bak_drop_alert_analysis_cols")
    shutil.copy2(db_path, backup_path)
    print(f"Backup created: {backup_path}")

    removed = []
    failed = []
    for col in existing_to_remove:
        try:
            did_remove = remove_column(conn, table_name, col)
            if did_remove:
                removed.append(col)
            else:
                failed.append(col)
        except Exception as e:
            print(f"Failed to remove {table_name}.{col}: {e}")
            failed.append(col)

    post_cursor = conn.cursor()
    still_present = [
        col for col in TARGET_COLUMNS if column_exists(post_cursor, table_name, col)
    ]

    print(f"Removed: {', '.join(removed) if removed else '(none)'}")
    print(f"Failed: {', '.join(failed) if failed else '(none)'}")
    print(
        f"Still present after run: {', '.join(still_present) if still_present else '(none)'}"
    )

    conn.close()


if __name__ == "__main__":
    main()

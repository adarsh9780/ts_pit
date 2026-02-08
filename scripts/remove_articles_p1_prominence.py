import argparse
import shutil
import sqlite3
import sys
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

TARGET_COLUMN = "p1_prominence"


def quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def get_db_connection() -> sqlite3.Connection:
    db_path = config.get_database_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


def column_exists(cursor: sqlite3.Cursor, table_name: str, column_name: str) -> bool:
    cursor.execute(f"PRAGMA table_info({quote_ident(table_name)})")
    columns = [row["name"] for row in cursor.fetchall()]
    return any(col.lower() == column_name.lower() for col in columns)


def get_columns(cursor: sqlite3.Cursor, table_name: str):
    cursor.execute(f"PRAGMA table_info({quote_ident(table_name)})")
    return [dict(row) for row in cursor.fetchall()]


def drop_column_with_rebuild(conn: sqlite3.Connection, table_name: str, column_name: str):
    cursor = conn.cursor()
    cols = get_columns(cursor, table_name)
    keep_cols = [c for c in cols if c["name"].lower() != column_name.lower()]
    if len(keep_cols) == len(cols):
        return False

    temp_table = f"{table_name}__old_p1_drop"
    keep_names = [c["name"] for c in keep_cols]

    col_defs = []
    pk_cols = []
    for col in keep_cols:
        name = quote_ident(col["name"])
        col_type = col["type"] or "TEXT"
        not_null = " NOT NULL" if col["notnull"] else ""
        default = f" DEFAULT {col['dflt_value']}" if col["dflt_value"] is not None else ""
        col_defs.append(f"{name} {col_type}{not_null}{default}")
        if col["pk"]:
            pk_cols.append((col["pk"], col["name"]))

    pk_sql = ""
    if pk_cols:
        pk_cols.sort(key=lambda x: x[0])
        pk_sql = ", PRIMARY KEY (" + ", ".join(quote_ident(c[1]) for c in pk_cols) + ")"

    create_sql = f"CREATE TABLE {quote_ident(table_name)} ({', '.join(col_defs)}{pk_sql})"
    keep_cols_sql = ", ".join(quote_ident(c) for c in keep_names)

    cursor.execute("BEGIN")
    cursor.execute(f"ALTER TABLE {quote_ident(table_name)} RENAME TO {quote_ident(temp_table)}")
    cursor.execute(create_sql)
    cursor.execute(
        f"INSERT INTO {quote_ident(table_name)} ({keep_cols_sql}) "
        f"SELECT {keep_cols_sql} FROM {quote_ident(temp_table)}"
    )
    cursor.execute(f"DROP TABLE {quote_ident(temp_table)}")
    conn.commit()
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Remove articles.p1_prominence column if it exists."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply changes. Without this flag, script runs in dry-run mode.",
    )
    args = parser.parse_args()

    table_name = config.get_table_name("articles")
    conn = get_db_connection()
    cursor = conn.cursor()

    exists = column_exists(cursor, table_name, TARGET_COLUMN)
    if not exists:
        print(f"No-op: Column {table_name}.{TARGET_COLUMN} does not exist.")
        conn.close()
        return

    print(f"Found column {table_name}.{TARGET_COLUMN}.")
    if not args.apply:
        print("Dry-run complete. Re-run with --apply to remove it.")
        conn.close()
        return

    db_path = Path(config.get_database_path())
    backup_path = db_path.with_suffix(db_path.suffix + ".bak_drop_articles_p1")
    shutil.copy2(db_path, backup_path)
    print(f"Backup created: {backup_path}")

    # Try direct DROP COLUMN first (supported in modern SQLite).
    removed = False
    try:
        cursor.execute(
            f"ALTER TABLE {quote_ident(table_name)} DROP COLUMN {quote_ident(TARGET_COLUMN)}"
        )
        conn.commit()
        removed = True
        print(f"Removed column via ALTER TABLE DROP COLUMN: {TARGET_COLUMN}")
    except sqlite3.OperationalError as e:
        print(f"Direct DROP COLUMN not available ({e}). Falling back to table rebuild...")
        removed = drop_column_with_rebuild(conn, table_name, TARGET_COLUMN)

    if removed and not column_exists(conn.cursor(), table_name, TARGET_COLUMN):
        print(f"Success: {table_name}.{TARGET_COLUMN} removed.")
    else:
        print(f"Warning: Could not confirm removal of {table_name}.{TARGET_COLUMN}.")

    conn.close()


if __name__ == "__main__":
    main()

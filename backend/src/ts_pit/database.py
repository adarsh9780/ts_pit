import sqlite3
from .config import get_config


def get_db_connection():
    """Get a connection to the SQLite database."""
    config = get_config()
    db_path = config.get_database_path()
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def remap_row(row, table_key: str):
    """
    Remaps a database row (dict-like) to UI keys based on config.

    Args:
        row: Database row as dict-like object
        table_key: Table key (alerts, articles, prices)

    Returns:
        Dict with UI-friendly keys
    """
    config = get_config()
    columns = config.get_columns(table_key)
    result = {}

    # Map DB columns to UI keys
    for ui_key, db_col in columns.items():
        if db_col and db_col in row.keys():
            result[ui_key] = row[db_col]

    # Keep extra fields that aren't in the mapping
    mapped_db_cols = set(col for col in columns.values() if col)
    for k in row.keys():
        if k not in mapped_db_cols:
            result[k] = row[k]

    return result

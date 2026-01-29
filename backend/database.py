import sqlite3
from .config import get_config


def get_db_connection():
    """Get a connection to the SQLite database."""
    config = get_config()
    db_path = config.get_database_path()
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

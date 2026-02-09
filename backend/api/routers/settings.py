from __future__ import annotations

from fastapi import APIRouter

from ...config import get_config
from ...database import get_db_connection


router = APIRouter(tags=["settings"])
config = get_config()


def _db_column_exists(table_name: str, column_name: str) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(f'PRAGMA table_info("{table_name}")')
        columns = {row["name"] for row in cursor.fetchall()}
        return column_name in columns
    finally:
        conn.close()


def _has_materiality_support() -> bool:
    required_mappings = [
        ("articles", "created_date"),
        ("articles", "theme"),
        ("article_themes", "art_id"),
        ("article_themes", "p1_prominence"),
    ]
    for table_key, col_key in required_mappings:
        if not config.has_column(table_key, col_key):
            return False

    required_db_columns = [
        (config.get_table_name("articles"), config.get_column("articles", "created_date")),
        (config.get_table_name("articles"), config.get_column("articles", "theme")),
        (config.get_table_name("article_themes"), config.get_column("article_themes", "art_id")),
        (
            config.get_table_name("article_themes"),
            config.get_column("article_themes", "p1_prominence"),
        ),
    ]
    return all(_db_column_exists(table, col) for table, col in required_db_columns)


@router.get("/config")
def get_config_endpoint():
    payload = config.get_mappings_for_api()
    payload["has_materiality"] = _has_materiality_support()
    return payload

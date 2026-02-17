from __future__ import annotations

from typing import Any

from sqlalchemy import MetaData, Text, Table, cast, inspect, select

from ..config import get_config
from ..db.engine import get_engine


config = get_config()
_metadata = MetaData()
_table_cache: dict[str, Table] = {}


def get_table(table_name: str) -> Table:
    cached = _table_cache.get(table_name)
    if cached is not None:
        return cached
    table = Table(table_name, _metadata, autoload_with=get_engine())
    _table_cache[table_name] = table
    return table


def get_alert_id_candidates(table_name: str) -> list[str]:
    inspector = inspect(get_engine())
    available_cols = {col["name"] for col in inspector.get_columns(table_name)}
    preferred = [
        config.get_column("alerts", "id"),
        "alert_id",
        "Alert ID",
        "id",
    ]
    return [col for col in dict.fromkeys(preferred) if col in available_cols]


def probe_alert_id_values(alert_id: str | int) -> list[Any]:
    probe_values: list[Any] = [alert_id]
    if not isinstance(alert_id, str):
        probe_values.append(str(alert_id))
    elif alert_id.isdigit():
        probe_values.append(int(alert_id))
    return probe_values


def resolve_alert_row(table_name: str, alert_id: str | int):
    table = get_table(table_name)
    id_cols = get_alert_id_candidates(table_name)
    probe_values = probe_alert_id_values(alert_id)
    select_columns = [cast(col, Text).label(col.name) for col in table.columns]

    with get_engine().connect() as conn:
        for value in probe_values:
            for id_col in id_cols:
                row = conn.execute(
                    select(*select_columns).where(table.c[id_col] == value).limit(1)
                ).mappings().first()
                if row:
                    return dict(row), id_col, value

    return None, None, None

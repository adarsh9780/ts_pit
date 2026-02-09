from __future__ import annotations

from ..config import get_config


config = get_config()


def get_alert_id_candidates(cursor, table_name: str) -> list[str]:
    cursor.execute(f'PRAGMA table_info("{table_name}")')
    available_cols = {row["name"] for row in cursor.fetchall()}
    preferred = [
        config.get_column("alerts", "id"),
        "alert_id",
        "Alert ID",
        "id",
    ]
    return [c for c in dict.fromkeys(preferred) if c in available_cols]


def resolve_alert_row(cursor, table_name: str, alert_id: str | int):
    id_cols = get_alert_id_candidates(cursor, table_name)
    probe_values = [alert_id]
    if not isinstance(alert_id, str):
        probe_values.append(str(alert_id))
    elif alert_id.isdigit():
        probe_values.append(int(alert_id))

    for value in probe_values:
        for id_col in id_cols:
            cursor.execute(
                f'SELECT * FROM "{table_name}" WHERE "{id_col}" = ? LIMIT 1', (value,)
            )
            row = cursor.fetchone()
            if row:
                return row, id_col, value

    return None, None, None


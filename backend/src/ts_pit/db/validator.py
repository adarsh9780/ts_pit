from __future__ import annotations

from sqlalchemy import inspect

from .engine import get_engine
from .schema import build_metadata


def validate_required_schema(config=None) -> list[str]:
    """
    Validate database has all tables/columns required by the app contract.
    Returns a list of missing entries in table.column format.
    """
    engine = get_engine()
    inspector = inspect(engine)
    metadata = build_metadata(config=config)
    missing: list[str] = []

    for table_name, table in metadata.tables.items():
        if not inspector.has_table(table_name):
            missing.append(f"{table_name} (table)")
            continue

        existing_cols = {col["name"] for col in inspector.get_columns(table_name)}
        for col in table.columns:
            if col.name not in existing_cols:
                missing.append(f"{table_name}.{col.name}")

    return missing


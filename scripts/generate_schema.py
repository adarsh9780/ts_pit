#!/usr/bin/env python3
"""
Schema Generator for AI Agent
==============================
Generates a YAML schema description from the SQLite database.
Includes all physical DB columns and preserves config.yaml logical mappings when available.

Features:
- Includes all columns found in the physical database
- Uses config.yaml logical names when mapped
- Preserves human-edited descriptions when re-run
- Colored warnings for missing descriptions
- Includes sample values for context

Usage:
    python scripts/generate_schema.py
    python scripts/generate_schema.py --db-path /path/to/db.sqlite
    python scripts/generate_schema.py --output /custom/output/schema.yaml

Output: backend/agent/db_schema.yaml (default)
"""

import argparse
import sqlite3
import yaml
import sys
from pathlib import Path
from typing import Any

# Add backend to path for imports
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.config import get_config

try:
    from colorama import init, Fore, Style

    init(autoreset=True)
except ImportError:
    # Fallback if colorama not installed
    class Fore:
        RED = YELLOW = GREEN = CYAN = MAGENTA = ""

    class Style:
        BRIGHT = RESET_ALL = ""

    print("Note: Install colorama for colored output (pip install colorama)")


def get_tables(cursor: sqlite3.Cursor) -> list[str]:
    """Get all table names from the database."""
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    return [row[0] for row in cursor.fetchall() if not row[0].startswith("sqlite_")]


def get_db_columns(cursor: sqlite3.Cursor, table: str) -> list[dict]:
    """Get column info for a table from the actual database."""
    cursor.execute(f'PRAGMA table_info("{table}")')
    columns = []
    for row in cursor.fetchall():
        columns.append(
            {
                "name": row[1],
                "type": row[2] or "TEXT",
                "nullable": not row[3],
                "primary_key": bool(row[5]),
            }
        )
    return columns


def get_sample_value(cursor: sqlite3.Cursor, table: str, column: str) -> Any:
    """Get a sample value for a column (first non-null value)."""
    try:
        cursor.execute(
            f'SELECT "{column}" FROM "{table}" WHERE "{column}" IS NOT NULL LIMIT 1'
        )
        row = cursor.fetchone()
        if row:
            value = row[0]
            # Truncate long strings
            if isinstance(value, str) and len(value) > 100:
                return value[:100] + "..."
            return value
    except Exception:
        pass
    return None


def get_row_count(cursor: sqlite3.Cursor, table: str) -> int:
    """Get the number of rows in a table."""
    cursor.execute(f'SELECT COUNT(*) FROM "{table}"')
    return cursor.fetchone()[0]


def load_existing_schema(output_path: Path) -> dict:
    """Load existing schema to preserve human-edited descriptions."""
    if output_path.exists():
        with open(output_path, "r") as f:
            return yaml.safe_load(f) or {}
    return {}


def get_config_column_mapping(config, table_key: str) -> dict:
    """
    Get the config column mapping for a table.
    Returns dict of {ui_key: db_column_name}
    """
    try:
        return config.get_columns(table_key)
    except KeyError:
        return {}


def generate_schema(
    db_path: Path, output_path: Path
) -> tuple[dict, list[str], list[str], list[str]]:
    """
    Generate schema from database, including all physical DB columns.

    Args:
        db_path: Path to the SQLite database
        output_path: Path to the output YAML file (for loading existing descriptions)

    Returns:
        tuple: (schema_dict, preserved_warnings, missing_warnings, new_column_warnings)
    """
    config = get_config()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    existing_schema = load_existing_schema(output_path)
    existing_tables = existing_schema.get("tables", {})

    preserved_warnings = []
    missing_warnings = []
    new_column_warnings = []

    schema = {
        "_meta": {
            "generated_by": "scripts/generate_schema.py",
            "database": str(db_path.name),
            "instructions": (
                "This schema includes all physical DB columns. "
                "Mapped columns use logical keys from config.yaml; unmapped columns "
                "use their physical DB column name as the key. "
                "Add descriptions to help the AI agent understand column semantics."
            ),
        },
        "tables": {},
    }

    # Table key mapping from config.yaml
    table_keys = ["alerts", "articles", "prices", "prices_hourly", "article_themes"]

    for table_key in table_keys:
        try:
            table_name = config.get_table_name(table_key)
        except KeyError:
            continue

        # Check if table exists in DB
        if table_name not in get_tables(cursor):
            continue

        db_columns = get_db_columns(cursor, table_name)
        row_count = get_row_count(cursor, table_name)
        config_columns = get_config_column_mapping(config, table_key)

        # Reverse mapping: db_col_name -> ui_key
        db_to_ui = {v: k for k, v in config_columns.items() if v}

        # Track which DB columns are in config
        mapped_db_cols = set(db_to_ui.keys())

        table_info = {
            "description": "",
            "row_count": row_count,
            "columns": {},
        }

        # Preserve table description if exists
        if table_key in existing_tables:
            existing_desc = existing_tables[table_key].get("description", "")
            if existing_desc:
                table_info["description"] = existing_desc
                preserved_warnings.append(f"Table '{table_key}' description preserved")

        if not table_info["description"]:
            missing_warnings.append(f"Table '{table_key}' is missing a description")

        existing_cols = existing_tables.get(table_key, {}).get("columns", {})

        # Process all DB columns.
        for db_col_info in db_columns:
            db_col_name = db_col_info["name"]
            ui_key = db_to_ui.get(db_col_name, db_col_name)
            sample = get_sample_value(cursor, table_name, db_col_name)

            col_info = {
                "type": db_col_info["type"],
                "description": "",
                "db_column": db_col_name,  # Always keep physical DB column name
            }

            if db_col_name in db_to_ui:
                col_info["mapped_from_config"] = True
            else:
                col_info["mapped_from_config"] = False
                new_column_warnings.append(
                    f"  └─ Column '{table_name}.{db_col_name}' is unmapped in config.yaml (included as '{ui_key}')"
                )

            if db_col_info["primary_key"]:
                col_info["primary_key"] = True

            if sample is not None:
                col_info["example"] = sample

            # Preserve existing description if present on same key.
            if ui_key in existing_cols:
                existing_desc = existing_cols[ui_key].get("description", "")
                if existing_desc:
                    col_info["description"] = existing_desc
                    preserved_warnings.append(
                        f"  └─ Column '{table_key}.{ui_key}' description preserved"
                    )

            if not col_info["description"]:
                missing_warnings.append(
                    f"  └─ Column '{table_key}.{ui_key}' is missing a description"
                )

            table_info["columns"][ui_key] = col_info

        schema["tables"][table_key] = table_info

    conn.close()
    return schema, preserved_warnings, missing_warnings, new_column_warnings


def parse_args():
    """Parse command line arguments."""
    default_db = Path(get_config().get_database_path())
    default_output = PROJECT_ROOT / "backend" / "agent" / "db_schema.yaml"

    parser = argparse.ArgumentParser(
        description="Generate YAML schema from SQLite database for AI agent.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/generate_schema.py
  python scripts/generate_schema.py --db-path /path/to/alerts.db
  python scripts/generate_schema.py --output ./my_schema.yaml
        """,
    )
    parser.add_argument(
        "--db-path",
        "-d",
        type=Path,
        default=default_db,
        help=f"Path to SQLite database (default: {default_db})",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=default_output,
        help=f"Output YAML file path (default: {default_output})",
    )
    return parser.parse_args()


def main():
    """Main entry point."""
    args = parse_args()
    db_path = args.db_path
    output_path = args.output

    print(f"{Style.BRIGHT}🔍 Introspecting database schema...{Style.RESET_ALL}")
    print(f"   Database: {db_path}")

    # Ensure output directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Generate schema
    schema, preserved, missing, new_cols = generate_schema(db_path, output_path)

    # Write output
    with open(output_path, "w") as f:
        yaml.dump(
            schema, f, default_flow_style=False, sort_keys=False, allow_unicode=True
        )

    print(f"{Fore.GREEN}✅ Schema written to: {output_path}{Style.RESET_ALL}")

    # Show preserved descriptions (cyan)
    if preserved:
        print(
            f"\n{Fore.CYAN}📎 Preserved existing descriptions ({len(preserved)} items):{Style.RESET_ALL}"
        )
        for w in preserved[:10]:  # Limit output
            print(f"{Fore.CYAN}{w}{Style.RESET_ALL}")
        if len(preserved) > 10:
            print(f"{Fore.CYAN}   ... and {len(preserved) - 10} more{Style.RESET_ALL}")

    # Show missing descriptions (yellow)
    if missing:
        print(
            f"\n{Fore.YELLOW}⚠️  Missing descriptions ({len(missing)} items):{Style.RESET_ALL}"
        )
        for w in missing:
            print(f"{Fore.YELLOW}{w}{Style.RESET_ALL}")

    # Show new/unmapped columns (magenta)
    if new_cols:
        print(
            f"\n{Fore.MAGENTA}🆕 Unmapped DB columns included ({len(new_cols)} items):{Style.RESET_ALL}"
        )
        for w in new_cols:
            print(f"{Fore.MAGENTA}{w}{Style.RESET_ALL}")

    # Summary
    tables = schema.get("tables", {})
    total_cols = sum(len(t.get("columns", {})) for t in tables.values())

    if not missing:
        print(f"\n{Fore.GREEN}✨ All descriptions are filled in!{Style.RESET_ALL}")

    print(
        f"\n{Style.BRIGHT}📊 Summary: {len(tables)} tables, {total_cols} columns{Style.RESET_ALL}"
    )


if __name__ == "__main__":
    main()

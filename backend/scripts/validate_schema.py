import sqlite3
import sys
from pathlib import Path
from colorama import init, Fore, Style

# Add backend directory to path to import config
current_dir = Path(__file__).resolve().parent
sys.path.append(str(current_dir.parent))
from backend.config import get_config

init(autoreset=True)


def validate_schema():
    print(f"{Fore.CYAN}🔍 Starting Schema Validation...{Style.RESET_ALL}")

    try:
        config = get_config()
        db_path = config.get_database_path()

        if not os.path.exists(db_path):
            print(f"{Fore.RED}❌ Database not found at: {db_path}{Style.RESET_ALL}")
            return

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Access the raw config dictionary (private attribute)
        # This is necessary since the Config class doesn't expose a getter for the full structure
        tables = config._config.get("tables", {})
        all_valid = True

        for table_key, table_conf in tables.items():
            table_name = table_conf.get("name")
            print(
                f"\nChecking table: {Fore.BLUE}{table_name}{Style.RESET_ALL} (Config Key: {table_key})"
            )

            # Check if table exists
            cursor.execute(
                f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}';"
            )
            if not cursor.fetchone():
                print(
                    f"  {Fore.RED}❌ Table '{table_name}' does not exist in database!{Style.RESET_ALL}"
                )
                all_valid = False
                continue

            # Get actual columns
            cursor.execute(f"PRAGMA table_info('{table_name}')")
            actual_columns = {row[1] for row in cursor.fetchall()}

            # Check required columns
            columns_conf = table_conf.get("columns", {})
            missing_cols = []

            for config_col_key, db_col_name in columns_conf.items():
                if not db_col_name:  # Skip empty optional mappings
                    continue

                if db_col_name not in actual_columns:
                    missing_cols.append(
                        f"{db_col_name} (Mapped from: {config_col_key})"
                    )

            if missing_cols:
                print(f"  {Fore.YELLOW}⚠️  Missing Columns:{Style.RESET_ALL}")
                for col in missing_cols:
                    print(f"    - {col}")
                all_valid = False
            else:
                print(
                    f"  {Fore.GREEN}✅ All configured columns present.{Style.RESET_ALL}"
                )

        conn.close()

        print("\n" + "=" * 50)
        if all_valid:
            print(
                f"{Fore.GREEN}✅ SCHEMA VALIDATION PASSED. Database matches config.{Style.RESET_ALL}"
            )
        else:
            print(
                f"{Fore.RED}❌ SCHEMA VALIDATION FAILED. See errors above.{Style.RESET_ALL}"
            )
            print(
                f"{Fore.RED}Required Action: Update your database schema or adjust config.yaml if columns are optional.{Style.RESET_ALL}"
            )

    except Exception as e:
        print(f"{Fore.RED}❌ Error running validation: {e}{Style.RESET_ALL}")


import os

if __name__ == "__main__":
    validate_schema()

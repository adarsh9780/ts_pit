from __future__ import annotations

import argparse
import sys

from _script_runner import run_legacy_script
from data_ops import DATA_OPERATIONS
from db_ops import DB_OPERATIONS
from dev_checks import DEV_CHECK_OPERATIONS
from schema_ops import SCHEMA_OPERATIONS
from scoring_ops import SCORING_OPERATIONS

CATEGORY_OPERATIONS = {
    "db": DB_OPERATIONS,
    "scoring": SCORING_OPERATIONS,
    "schema": SCHEMA_OPERATIONS,
    "dev": DEV_CHECK_OPERATIONS,
    "data": DATA_OPERATIONS,
}


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)

    parser = argparse.ArgumentParser(
        description="Unified scripts entrypoint grouped by task category.",
        usage="%(prog)s <category> <operation> [args...]",
    )
    parser.add_argument("category", nargs="?", help="Task category to run.")
    parser.add_argument("operation", nargs="?", help="Operation name within category.")

    if len(args) < 2 or args[0] in {"-h", "--help"}:
        parser.print_help()
        print(
            "\nAvailable categories: " + ", ".join(sorted(CATEGORY_OPERATIONS.keys()))
        )
        return 0

    category = args[0]
    operation = args[1]
    passthrough = args[2:]

    if category not in CATEGORY_OPERATIONS:
        valid = ", ".join(sorted(CATEGORY_OPERATIONS.keys()))
        print(
            f"Unknown category '{category}'. Valid categories: {valid}",
            file=sys.stderr,
        )
        return 2

    category_map = CATEGORY_OPERATIONS[category]
    if operation not in category_map:
        valid = ", ".join(sorted(category_map.keys()))
        print(
            f"Unknown operation '{operation}' for '{category}'. "
            f"Valid operations: {valid}",
            file=sys.stderr,
        )
        return 2

    return run_legacy_script(category_map[operation], passthrough)


if __name__ == "__main__":
    raise SystemExit(main())

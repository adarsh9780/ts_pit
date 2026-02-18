from __future__ import annotations

from _script_runner import run_operation

SCHEMA_OPERATIONS = {
    "export-openapi": "export_openapi.py",
    "generate-schema": "generate_schema.py",
    "validate-schema": "validate_schema.py",
}


def main() -> int:
    return run_operation(
        SCHEMA_OPERATIONS,
        "Schema generation, validation, and API contract export operations.",
    )


if __name__ == "__main__":
    raise SystemExit(main())

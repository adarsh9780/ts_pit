#!/usr/bin/env python3
"""Export the FastAPI OpenAPI schema to a file."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

# Ensure project root is importable when script is executed directly.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ts_pit.main import app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export FastAPI OpenAPI schema to JSON or YAML."
    )
    parser.add_argument(
        "--output",
        "-o",
        default="openapi.json",
        help="Output file path (default: openapi.json)",
    )
    parser.add_argument(
        "--format",
        choices=("json", "yaml"),
        default=None,
        help="Output format. If omitted, inferred from file extension.",
    )
    return parser.parse_args()


def infer_format(output_path: Path, explicit_format: str | None) -> str:
    if explicit_format:
        return explicit_format

    suffix = output_path.suffix.lower()
    if suffix in {".yaml", ".yml"}:
        return "yaml"
    return "json"


def main() -> None:
    args = parse_args()
    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    schema = app.openapi()
    output_format = infer_format(output_path, args.format)

    if output_format == "yaml":
        output_path.write_text(
            yaml.safe_dump(schema, sort_keys=False, allow_unicode=False),
            encoding="utf-8",
        )
    else:
        output_path.write_text(
            json.dumps(schema, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )

    print(f"OpenAPI schema exported to {output_path}")


if __name__ == "__main__":
    main()

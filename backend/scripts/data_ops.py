from __future__ import annotations

from _script_runner import run_operation

DATA_OPERATIONS = {
    "fetch-price": "fetch_price.py",
    "generate-dummy-data": "generate_dummy_data.py",
    "update-summaries": "update_summaries.py",
}


def main() -> int:
    return run_operation(
        DATA_OPERATIONS,
        "Data population, refresh, and fetch helper operations.",
    )


if __name__ == "__main__":
    raise SystemExit(main())

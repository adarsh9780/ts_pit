from __future__ import annotations

from _script_runner import run_operation

DB_OPERATIONS = {
    "migrate-alert-analysis-table": "migrate_alert_analysis_table.py",
    "migrate-impact-labels": "migrate_impact_labels.py",
    "migrate-materiality": "migrate_materiality.py",
    "migrate-statuses": "migrate_statuses.py",
    "remove-alert-analysis-columns": "remove_alert_analysis_columns.py",
    "remove-articles-p1-prominence": "remove_articles_p1_prominence.py",
}


def main() -> int:
    return run_operation(
        DB_OPERATIONS,
        "Database maintenance operations for migrations and table cleanups.",
    )


if __name__ == "__main__":
    raise SystemExit(main())

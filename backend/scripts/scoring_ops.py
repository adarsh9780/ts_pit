from __future__ import annotations

from _script_runner import run_operation

SCORING_OPERATIONS = {
    "calc-impact-scores": "calc_impact_scores.py",
    "calc-prominence": "calc_prominence.py",
    "verify-impact-labels": "verify_impact_labels.py",
}


def main() -> int:
    return run_operation(
        SCORING_OPERATIONS,
        "Scoring and label verification operations.",
    )


if __name__ == "__main__":
    raise SystemExit(main())

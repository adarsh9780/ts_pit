"""
Regression checks for P3 thematic tier mapping.

This is a lightweight script (no pytest dependency) to prevent drift between:
- backend/scoring.py (calculate_p3)
- artifacts/TECHNICAL_IMPLEMENTATION.md policy table
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT))

from backend.scoring import calculate_p3


def assert_equal(actual, expected, case_name):
    if actual != expected:
        raise AssertionError(
            f"{case_name} failed: expected {expected!r}, got {actual!r}"
        )


def run():
    # High tier expectations
    assert_equal(calculate_p3("EARNINGS_ANNOUNCEMENT"), "H", "High/Earnings")
    assert_equal(calculate_p3("M_AND_A"), "H", "High/M&A")
    assert_equal(calculate_p3("DIVIDEND_CORP_ACTION"), "H", "High/Dividend")
    assert_equal(calculate_p3("PRODUCT_TECH_LAUNCH"), "H", "High/Product")
    assert_equal(calculate_p3("COMMERCIAL_CONTRACTS"), "H", "High/Contracts")

    # Medium tier expectations
    assert_equal(calculate_p3("LEGAL_REGULATORY"), "M", "Medium/Legal")
    assert_equal(calculate_p3("EXECUTIVE_CHANGE"), "M", "Medium/Executive")
    assert_equal(calculate_p3("OPERATIONAL_CRISIS"), "M", "Medium/Operational")
    assert_equal(calculate_p3("CAPITAL_STRUCTURE"), "M", "Medium/Capital")
    assert_equal(calculate_p3("MACRO_SECTOR"), "M", "Medium/Macro")
    assert_equal(calculate_p3("ANALYST_OPINION"), "M", "Medium/Analyst")

    # Case-insensitive and substring matching behavior
    assert_equal(calculate_p3("macro_sector_update"), "M", "Medium/Substring")
    assert_equal(calculate_p3("earnings_announcement_q4"), "H", "High/Substring")

    # Low tier expectations
    assert_equal(calculate_p3("UNCATEGORIZED"), "L", "Low/Uncategorized")
    assert_equal(calculate_p3("RANDOM_THEME"), "L", "Low/Unknown")
    assert_equal(calculate_p3(""), "L", "Low/EmptyString")
    assert_equal(calculate_p3(None), "L", "Low/None")

    print("P3 mapping regression checks passed.")


if __name__ == "__main__":
    run()

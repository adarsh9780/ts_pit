import unittest
from datetime import datetime

from backend.services.alert_analysis_policy import (
    parse_datetime,
    is_high_impact,
    is_material_news,
    run_deterministic_summary_gates,
    enforce_dismiss_evidence_requirements,
    enrich_needs_review_reason,
)


class _FakeConfig:
    def get_column(self, table, key):
        if table == "alerts" and key == "execution_date":
            return "execution_date"
        return key


class AlertAnalysisPolicyTests(unittest.TestCase):
    def setUp(self):
        self.config = _FakeConfig()

    def test_parse_datetime_normalizes_zulu_to_naive_utc(self):
        dt = parse_datetime("2026-02-10T15:30:00Z")
        self.assertEqual(dt, datetime(2026, 2, 10, 15, 30, 0))

    def test_parse_datetime_parses_date_only(self):
        dt = parse_datetime("2026-02-10")
        self.assertEqual(dt, datetime(2026, 2, 10, 0, 0, 0))

    def test_high_impact_threshold(self):
        self.assertTrue(is_high_impact(4.0))
        self.assertTrue(is_high_impact(-4.2))
        self.assertFalse(is_high_impact(3.99))

    def test_material_news_uses_p1_or_p3(self):
        self.assertTrue(is_material_news({"materiality": "HML"}))
        self.assertTrue(is_material_news({"materiality": "LLH"}))
        self.assertFalse(is_material_news({"materiality": "LML"}))

    def test_deterministic_gate_missing_fields_returns_needs_review(self):
        result, used = run_deterministic_summary_gates(
            config=self.config,
            alert={},
            articles=[],
            start_date=None,
            end_date=None,
            trade_type=None,
        )
        self.assertEqual(result["recommendation"], "NEEDS_REVIEW")
        self.assertEqual(result["narrative_theme"], "NEEDS_REVIEW_DATA_GAP")
        self.assertEqual(used, [])

    def test_deterministic_gate_no_pretrade_high_impact_escalates(self):
        alert = {"execution_date": "2026-02-10T10:00:00"}
        articles = [
            {
                "created_date": "2026-02-10T11:00:00",
                "impact_score": 5.1,
                "materiality": "LML",
            }
        ]
        result, used = run_deterministic_summary_gates(
            config=self.config,
            alert=alert,
            articles=articles,
            start_date="2026-02-01",
            end_date="2026-02-10",
            trade_type="BUY",
        )
        self.assertEqual(result["recommendation"], "ESCALATE_L2")
        self.assertEqual(result["narrative_theme"], "ESCALATE_NO_PRETRADE_NEWS")
        self.assertEqual(used, [])

    def test_deterministic_gate_allows_llm_when_pretrade_material_exists(self):
        alert = {"execution_date": "2026-02-10T10:00:00"}
        articles = [
            {
                "created_date": "2026-02-10T09:00:00",
                "impact_score": 1.2,
                "materiality": "HML",
            }
        ]
        result, used = run_deterministic_summary_gates(
            config=self.config,
            alert=alert,
            articles=articles,
            start_date="2026-02-01",
            end_date="2026-02-10",
            trade_type="BUY",
        )
        self.assertIsNone(result)
        self.assertEqual(len(used), 1)

    def test_enforce_dismiss_downgrades_when_evidence_weak(self):
        result = {
            "recommendation": "DISMISS",
            "bullish_events": [],
            "bearish_events": [],
        }
        used_articles = [{"materiality": "LML", "impact_score": 0.4}]

        downgraded = enforce_dismiss_evidence_requirements(
            result=result,
            used_articles=used_articles,
            trade_type="BUY",
        )

        self.assertEqual(downgraded["recommendation"], "NEEDS_REVIEW")
        self.assertIn("insufficient", downgraded["narrative_theme"].lower())

    def test_enrich_needs_review_adds_dual_rationale(self):
        result = {
            "recommendation": "NEEDS_REVIEW",
            "recommendation_reason": "Base reason",
            "bullish_events": [],
            "bearish_events": [],
        }
        enriched = enrich_needs_review_reason(
            result=result,
            used_articles=[{"materiality": "LML", "impact_score": 0.5}],
            trade_type="BUY",
        )

        reason = enriched["recommendation_reason"]
        self.assertIn("Why this is NOT DISMISS", reason)
        self.assertIn("Why this is NOT ESCALATE_L2", reason)


if __name__ == "__main__":
    unittest.main()

import unittest
from unittest.mock import patch

from ts_pit.alert_analysis import analyze_alert_non_persisting


class _FakeConfig:
    def get_table_name(self, key):
        return {"alerts": "alerts"}[key]

    def get_column(self, table, key):
        if table == "alerts":
            mapping = {
                "id": "id",
                "start_date": "start_date",
                "end_date": "end_date",
                "trade_type": "trade_type",
            }
            return mapping[key]
        raise KeyError(key)


class AlertAnalysisEnrichmentTests(unittest.TestCase):
    def test_analysis_response_includes_linked_alert_fields(self):
        cfg = _FakeConfig()
        alert_row = {
            "id": "101",
            "start_date": "2026-02-01",
            "end_date": "2026-02-10",
            "trade_type": "BUY",
        }

        with patch("ts_pit.alert_analysis.resolve_alert_row", return_value=(alert_row, "id", "101")), patch(
            "ts_pit.alert_analysis.build_price_history", return_value=[]
        ), patch(
            "ts_pit.alert_analysis.build_alert_articles",
            return_value=[{"article_id": "1", "created_date": "2026-02-05", "title": "t"}],
        ), patch(
            "ts_pit.alert_analysis.find_related_alert_ids",
            return_value={
                "primary_alert_id": "101",
                "related_alert_ids": ["101", "102"],
                "related_alert_count": 2,
            },
        ), patch(
            "ts_pit.alert_analysis.run_deterministic_summary_gates",
            return_value=(
                {
                    "recommendation": "NEEDS_REVIEW",
                    "narrative_theme": "X",
                    "narrative_summary": "Y",
                    "recommendation_reason": "R",
                },
                [{"article_id": "1", "created_date": "2026-02-05", "title": "t"}],
            ),
        ):
            out = analyze_alert_non_persisting(conn=None, config=cfg, alert_id="101", llm=None)

        self.assertTrue(out["ok"])
        self.assertEqual(out["primary_alert_id"], "101")
        self.assertEqual(out["related_alert_ids"], ["101", "102"])
        self.assertEqual(out["related_alert_count"], 2)
        self.assertIn("Multiple alerts share the same ticker", out["linked_alerts_notice"])


if __name__ == "__main__":
    unittest.main()

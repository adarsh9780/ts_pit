import unittest

from ts_pit import llm


class _StructuredStub:
    def invoke(self, _messages):
        return {
            "narrative_theme": "Phase I Trial Success",
            "narrative_summary": "Public trial progress headlines are positive.",
            "bullish_events": ["Strong enrollment update"],
            "bearish_events": [],
            "neutral_events": [],
            "recommendation": "NEEDS_REVIEW",
            "recommendation_reason": [
                "Completion of first cohort was announced.",
                "Market reaction remained mixed.",
            ],
        }


class _LlmStub:
    def with_structured_output(self, _schema):
        return _StructuredStub()


class ClusterSummaryReasonCoercionTests(unittest.TestCase):
    def test_recommendation_reason_list_is_coerced_to_string(self):
        out = llm.generate_cluster_summary(
            articles=[
                {
                    "title": "Trial update",
                    "summary": "Company shared trial milestone.",
                    "materiality": "HHM",
                    "impact_score": 2.2,
                }
            ],
            llm=_LlmStub(),
        )
        self.assertIsInstance(out.get("recommendation_reason"), str)
        self.assertIn("Completion of first cohort", out.get("recommendation_reason", ""))
        self.assertIn("Market reaction remained mixed", out.get("recommendation_reason", ""))


if __name__ == "__main__":
    unittest.main()

import unittest
from unittest.mock import patch

from langchain_core.messages import HumanMessage

from ts_pit.agent_v3.graph import clarify_node, intent_guard, intent_router
from ts_pit.agent_v3.state import AgentV3State, CurrentAlertContext


class ClarificationRoutingTests(unittest.TestCase):
    def test_high_risk_target_mismatch_triggers_clarification(self):
        state = AgentV3State(
            messages=[HumanMessage(content="[USER QUESTION]\nPlease analyze alert 999.")],
            current_alert=CurrentAlertContext(alert_id=123, ticker="TSLA"),
        )
        out = intent_guard(state, config={})
        self.assertEqual(out["intent_class"], "needs_clarification")
        self.assertTrue(out["needs_clarification"])
        self.assertEqual(out["assumption_risk"], "high")
        self.assertEqual(intent_router(state.model_copy(update=out)), "clarify")

    def test_budget_exhaustion_falls_back_to_current_alert(self):
        state = AgentV3State(
            messages=[HumanMessage(content="[USER QUESTION]\nPlease analyze alert 999.")],
            current_alert=CurrentAlertContext(alert_id=123, ticker="TSLA"),
            clarification_signature="target_mismatch_current_vs_requested",
            clarification_asked_turns=1,
            max_clarification_turns=1,
        )
        out = intent_guard(state, config={})
        self.assertEqual(out["intent_class"], "analyze_current_alert")
        self.assertFalse(out["needs_clarification"])
        self.assertIn("defaulted to current alert", str(out.get("clarification_reason", "")).lower())
        self.assertEqual(out["intent_target_alert_id"], 123)

    def test_price_method_ambiguity_triggers_clarification(self):
        state = AgentV3State(
            messages=[HumanMessage(content="[USER QUESTION]\nCan you analyze price data for this alert?")],
            current_alert=CurrentAlertContext(alert_id=123, ticker="TSLA"),
        )
        out = intent_guard(state, config={})
        self.assertEqual(out["intent_class"], "needs_clarification")
        self.assertTrue(out["needs_clarification"])

    def test_clarify_node_contains_explainable_sections_and_max_three_options(self):
        state = AgentV3State(
            messages=[HumanMessage(content="[USER QUESTION]\nCan you analyze price data for this alert?")],
            current_alert=CurrentAlertContext(alert_id=123, ticker="TSLA"),
            needs_clarification=True,
            clarification_reason="Price analysis request does not specify method.",
            clarification_signature="price_method_ambiguous",
            clarification_asked_turns=0,
            max_clarification_turns=1,
        )
        out = clarify_node(state, config={})
        self.assertIn("messages", out)
        content = str(out["messages"][0].content)
        self.assertIn("Why I'm asking", content)
        self.assertIn("What I can do", content)
        self.assertIn("What I need from you", content)
        option_lines = [line for line in content.splitlines() if line.strip().startswith("- 1.") or line.strip().startswith("- 2.") or line.strip().startswith("- 3.")]
        self.assertLessEqual(len(option_lines), 3)

    def test_plain_language_framework_request_is_not_blocked_by_llm_false_positive(self):
        state = AgentV3State(
            messages=[
                HumanMessage(
                    content=(
                        "[USER QUESTION]\ncreate a framework for me which would allow me "
                        "to choose the most important alert which requires my attention"
                    )
                )
            ],
            current_alert=CurrentAlertContext(alert_id=123, ticker="TSLA"),
        )
        with patch(
            "ts_pit.agent_v3.graph._llm_guard_intent",
            return_value={
                "intent_class": "blocked_user_code",
                "target_scope": "none",
                "target_alert_id": None,
                "confidence": 0.9,
                "assumption_risk": "low",
                "ambiguities": [],
                "reason": "false positive",
            },
        ):
            out = intent_guard(state, config={})

        self.assertNotEqual(out["intent_class"], "blocked_user_code")
        self.assertIsNone(out.get("guardrail_response"))


if __name__ == "__main__":
    unittest.main()

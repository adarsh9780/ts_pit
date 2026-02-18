import unittest
from unittest.mock import patch

from langchain_core.messages import HumanMessage

from ts_pit.agent_v3.state import AgentV3State, CurrentAlertContext, StepState
from ts_pit.agent_v3 import planning


class _PromptStub:
    def invoke(self, _kwargs):
        return []


class _ModelStub:
    def with_structured_output(self, _schema):
        return self

    def invoke(self, _messages):
        return {
            "plan_action": "append",
            "requires_execution": True,
            "requires_execution_reason": "Need tools",
            "steps": [
                {
                    "instruction": "Fetch supporting records for the alert.",
                    "goal": "Gather rows for answer.",
                    "success_criteria": "Rows are available.",
                    "constraints": [],
                }
            ],
        }


class _SqlModelStub:
    def with_structured_output(self, _schema):
        return self

    def invoke(self, _messages):
        return {
            "plan_action": "append",
            "requires_execution": True,
            "requires_execution_reason": "Need SQL drill-down",
            "steps": [
                {
                    "instruction": "Run SQL query on alerts and trades for this case.",
                    "goal": "Get supporting rows.",
                    "success_criteria": "Rows are available.",
                    "constraints": [],
                }
            ],
        }


class _ReuseNoStepsModelStub:
    def with_structured_output(self, _schema):
        return self

    def invoke(self, _messages):
        return {
            "plan_action": "reuse",
            "requires_execution": True,
            "requires_execution_reason": "Need web search",
            "steps": [],
        }


class PlanningDeterministicTests(unittest.TestCase):
    def test_planner_skips_execution_while_waiting_for_clarification(self):
        state = AgentV3State(
            messages=[HumanMessage(content="[USER QUESTION]\nanalyze price data")],
            current_alert=CurrentAlertContext(alert_id=123, ticker="NVDA"),
            needs_clarification=True,
            clarification_resolved=False,
        )
        out = planning.planner(state, config={})
        self.assertFalse(out["plan_requires_execution"])
        self.assertIn("clarification", str(out["plan_requires_execution_reason"]).lower())

    def test_injects_analysis_first_for_alert_investigation_query(self):
        state = AgentV3State(
            messages=[HumanMessage(content="[USER QUESTION]\nPlease investigate this alert.")],
            current_alert=CurrentAlertContext(alert_id=123, ticker="NVDA"),
        )

        with patch.object(planning, "load_chat_prompt", return_value=_PromptStub()), patch.object(
            planning, "get_llm_model", return_value=_ModelStub()
        ):
            out = planning.planner(state, config={})

        pending_steps = [s for s in out["steps"] if s.status in {"pending", "running"}]
        self.assertGreaterEqual(len(pending_steps), 1)
        joined = "\n".join(step.instruction for step in pending_steps)
        self.assertIn("Run deterministic analysis for the current alert", joined)

    def test_does_not_inject_when_analysis_already_done_for_current_alert(self):
        state = AgentV3State(
            messages=[HumanMessage(content="[USER QUESTION]\nExplain why this alert was flagged.")],
            current_alert=CurrentAlertContext(alert_id=123, ticker="NVDA"),
            steps=[
                StepState(
                    id="v1_s1",
                    instruction="Prior deterministic analysis",
                    selected_tool="analyze_current_alert",
                    tool_args={"alert_id": 123},
                    status="done",
                )
            ],
        )

        with patch.object(planning, "load_chat_prompt", return_value=_PromptStub()), patch.object(
            planning, "get_llm_model", return_value=_ModelStub()
        ):
            out = planning.planner(state, config={})

        pending_steps = [s for s in out["steps"] if s.status in {"pending", "running"}]
        self.assertGreaterEqual(len(pending_steps), 1)
        self.assertNotIn(
            "Run deterministic analysis for the current alert",
            pending_steps[0].instruction,
        )

    def test_forced_analysis_stays_before_schema_grounding(self):
        state = AgentV3State(
            messages=[HumanMessage(content="[USER QUESTION]\nInvestigate this alert and run SQL details.")],
            current_alert=CurrentAlertContext(alert_id=123, ticker="NVDA"),
            intent_class="analyze_current_alert",
        )

        with patch.object(planning, "load_chat_prompt", return_value=_PromptStub()), patch.object(
            planning, "get_llm_model", return_value=_SqlModelStub()
        ):
            out = planning.planner(state, config={})

        pending_steps = [s for s in out["steps"] if s.status in {"pending", "running"}]
        self.assertGreaterEqual(len(pending_steps), 3)
        self.assertTrue(
            pending_steps[0].instruction.startswith(
                planning.FORCED_ANALYSIS_STEP_INSTRUCTION
            )
        )
        self.assertIn("DB_SCHEMA_REFERENCE.yaml", pending_steps[1].instruction)

    def test_instructions_include_tool_hint_nudge(self):
        state = AgentV3State(
            messages=[HumanMessage(content="[USER QUESTION]\nInvestigate this alert and run SQL details.")],
            current_alert=CurrentAlertContext(alert_id=123, ticker="NVDA"),
            intent_class="analyze_current_alert",
        )

        with patch.object(planning, "load_chat_prompt", return_value=_PromptStub()), patch.object(
            planning, "get_llm_model", return_value=_SqlModelStub()
        ):
            out = planning.planner(state, config={})

        pending_steps = [s for s in out["steps"] if s.status in {"pending", "running"}]
        self.assertTrue(any("Tool hint:" in s.instruction for s in pending_steps))

    def test_fallback_step_added_when_execution_required_but_no_pending(self):
        state = AgentV3State(
            messages=[HumanMessage(content="[USER QUESTION]\nlook for news from the web")],
            current_alert=CurrentAlertContext(alert_id=123, ticker="NVDA"),
        )

        with patch.object(planning, "load_chat_prompt", return_value=_PromptStub()), patch.object(
            planning, "get_llm_model", return_value=_ReuseNoStepsModelStub()
        ):
            out = planning.planner(state, config={})

        pending_steps = [s for s in out["steps"] if s.status in {"pending", "running"}]
        self.assertGreaterEqual(len(pending_steps), 1)
        joined = "\n".join(step.instruction for step in pending_steps)
        self.assertIn("Tool hint: search_web", joined)
        self.assertTrue(out["plan_requires_execution"])


if __name__ == "__main__":
    unittest.main()

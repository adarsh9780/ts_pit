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


class PlanningDeterministicTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()

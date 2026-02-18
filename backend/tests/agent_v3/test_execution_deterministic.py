import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from langchain_core.messages import HumanMessage

from ts_pit.agent_v3 import execution
from ts_pit.agent_v3.state import AgentV3State, CurrentAlertContext, StepState


class ExecutionDeterministicTests(unittest.TestCase):
    def test_forces_analyze_current_alert_before_drilldown(self):
        state = AgentV3State(
            messages=[HumanMessage(content="[USER QUESTION]\nInvestigate this alert.")],
            current_alert=CurrentAlertContext(alert_id=321, ticker="NVDA"),
            steps=[
                StepState(
                    id="v1_s1",
                    instruction="Fetch SQL rows",
                    goal="Need details",
                    success_criteria="Rows fetched",
                )
            ],
        )

        invoke_mock = AsyncMock(
            return_value={"ok": True, "data": {"analysis": {"recommendation": "NEEDS_REVIEW"}}}
        )
        with patch.object(execution, "_invoke_tool", invoke_mock), patch.object(
            execution, "_propose_execution", side_effect=AssertionError("should not propose first")
        ):
            out = asyncio.run(execution.executioner(state, config={}))

        self.assertEqual(out["steps"][0].selected_tool, "analyze_current_alert")
        self.assertEqual(out["steps"][0].tool_args, {"alert_id": "321"})
        self.assertEqual(out["steps"][0].status, "done")

    def test_reuses_completed_analysis_and_skips_duplicate_tool_call(self):
        existing_result = {
            "ok": True,
            "data": {
                "analysis": {"recommendation": "NEEDS_REVIEW"},
                "related_alert_ids": ["321", "322"],
            },
        }
        state = AgentV3State(
            messages=[HumanMessage(content="[USER QUESTION]\nExplain this alert.")],
            current_alert=CurrentAlertContext(alert_id=321, ticker="NVDA"),
            steps=[
                StepState(
                    id="v1_s1",
                    instruction="Baseline analysis",
                    selected_tool="analyze_current_alert",
                    tool_args={"alert_id": 321},
                    status="done",
                    result_payload=existing_result,
                ),
                StepState(
                    id="v1_s2",
                    instruction="Run deterministic analysis for the current alert before any drill-down.",
                ),
            ],
        )

        invoke_mock = AsyncMock(side_effect=AssertionError("duplicate tool call should be skipped"))
        with patch.object(execution, "_invoke_tool", invoke_mock), patch.object(
            execution,
            "_propose_execution",
            return_value={
                "tool_name": "analyze_current_alert",
                "tool_args_json": '{"alert_id":"321"}',
                "reason": "duplicate test",
            },
        ):
            out = asyncio.run(execution.executioner(state, config={}))

        updated = out["steps"][1]
        self.assertEqual(updated.selected_tool, "analyze_current_alert")
        self.assertEqual(updated.status, "done")
        self.assertEqual(updated.result_payload, existing_result)
        self.assertIn("reused_result", str(updated.result_summary))


if __name__ == "__main__":
    unittest.main()

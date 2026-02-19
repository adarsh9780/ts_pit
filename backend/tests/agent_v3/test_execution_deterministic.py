import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from langchain_core.messages import HumanMessage

from ts_pit.agent_v3 import execution
from ts_pit.agent_v3.state import AgentV3State, CurrentAlertContext, StepState


class ExecutionDeterministicTests(unittest.TestCase):
    def test_execution_is_blocked_when_clarification_pending(self):
        state = AgentV3State(
            messages=[HumanMessage(content="[USER QUESTION]\nanalyze price data")],
            current_alert=CurrentAlertContext(alert_id=321, ticker="NVDA"),
            steps=[StepState(id="v1_s1", instruction="Pending step")],
            needs_clarification=True,
            clarification_resolved=False,
        )
        out = asyncio.run(execution.executioner(state, config={}))
        self.assertIn("clarification", str(out.get("terminal_error", "")).lower())

    def test_forces_analyze_current_alert_before_drilldown_when_intent_is_explicit_analysis(self):
        state = AgentV3State(
            messages=[HumanMessage(content="[USER QUESTION]\nAnalyze this alert.")],
            current_alert=CurrentAlertContext(alert_id=321, ticker="NVDA"),
            intent_class="analyze_current_alert",
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

    def test_search_web_empty_result_retries_once_then_skips_and_advances(self):
        state = AgentV3State(
            messages=[HumanMessage(content="[USER QUESTION]\nFind web news for this ticker.")],
            current_alert=CurrentAlertContext(alert_id=321, ticker="HEMO.L"),
            steps=[
                StepState(
                    id="v1_s1",
                    instruction="Search for web/news coverage.",
                    selected_tool="search_web",
                    tool_args={
                        "query": "HEMO.L investigation news",
                        "max_results": 5,
                        "start_date": "2025-08-15",
                        "end_date": "2025-08-29",
                    },
                ),
                StepState(id="v1_s2", instruction="Generate report"),
            ],
        )

        invoke_mock = AsyncMock(
            side_effect=[
                {"ok": True, "data": {"combined": [], "web": [], "news": []}},
                {"ok": True, "data": {"combined": [], "web": [], "news": []}},
            ]
        )
        with patch.object(execution, "_invoke_tool", invoke_mock), patch.object(
            execution,
            "_propose_execution",
            return_value={
                "tool_name": "search_web",
                "tool_args_json": '{"query":"HEMO.L investigation news","max_results":5,"start_date":"2025-08-15","end_date":"2025-08-29"}',
                "reason": "web lookup",
            },
        ):
            out = asyncio.run(execution.executioner(state, config={}))

        updated = out["steps"][0]
        self.assertEqual(updated.status, "skipped")
        self.assertEqual(out["current_step_index"], 1)
        self.assertIn("continuing with remaining plan steps", str(updated.result_summary))
        self.assertEqual(invoke_mock.await_count, 2)

    def test_search_web_error_retries_once_then_skips(self):
        state = AgentV3State(
            messages=[HumanMessage(content="[USER QUESTION]\nSearch recent web context.")],
            current_alert=CurrentAlertContext(alert_id=321, ticker="HEMO.L"),
            steps=[
                StepState(
                    id="v1_s1",
                    instruction="Search web.",
                    selected_tool="search_web",
                    tool_args={"query": "HEMO.L news", "max_results": 5},
                ),
                StepState(id="v1_s2", instruction="Generate report"),
            ],
        )

        invoke_mock = AsyncMock(
            side_effect=[
                {
                    "ok": False,
                    "error": {"code": "WEB_SEARCH_ERROR", "message": "No results found."},
                },
                {
                    "ok": False,
                    "error": {"code": "WEB_SEARCH_ERROR", "message": "Provider timeout."},
                },
            ]
        )
        with patch.object(execution, "_invoke_tool", invoke_mock), patch.object(
            execution,
            "_propose_execution",
            return_value={
                "tool_name": "search_web",
                "tool_args_json": '{"query":"HEMO.L news","max_results":5}',
                "reason": "web lookup",
            },
        ):
            out = asyncio.run(execution.executioner(state, config={}))

        updated = out["steps"][0]
        self.assertEqual(updated.status, "skipped")
        self.assertEqual(out["current_step_index"], 1)
        self.assertIn("deterministically skipped", str(updated.result_summary))

    def test_uses_planner_provided_tool_and_args_without_proposal_call(self):
        state = AgentV3State(
            messages=[HumanMessage(content="[USER QUESTION]\nFetch latest related rows.")],
            current_alert=CurrentAlertContext(alert_id=321, ticker="NVDA"),
            steps=[
                StepState(
                    id="v1_s1",
                    instruction="Fetch rows",
                    selected_tool="search_web",
                    tool_args={"query": "NVDA company news", "max_results": 5},
                )
            ],
        )

        invoke_mock = AsyncMock(
            return_value={"ok": True, "data": {"combined": [{"url": "u1"}], "web": [], "news": []}}
        )
        with patch.object(execution, "_invoke_tool", invoke_mock), patch.object(
            execution, "_propose_execution", side_effect=AssertionError("should not propose")
        ):
            out = asyncio.run(execution.executioner(state, config={}))

        updated = out["steps"][0]
        self.assertEqual(updated.status, "done")
        self.assertEqual(updated.selected_tool, "search_web")
        self.assertEqual(invoke_mock.await_count, 1)

    def test_sql_preflight_reads_schema_before_execute_sql(self):
        state = AgentV3State(
            messages=[HumanMessage(content="[USER QUESTION]\nRun SQL for alerts table.")],
            current_alert=CurrentAlertContext(alert_id=321, ticker="NVDA"),
            steps=[
                StepState(
                    id="v1_s1",
                    instruction="Query alerts",
                    selected_tool="execute_sql",
                    tool_args={"query": "SELECT id FROM alerts LIMIT 5"},
                )
            ],
        )

        invoke_mock = AsyncMock(
            side_effect=[
                {"ok": True, "data": {"content": "schema text"}},
                {"ok": True, "data": [{"id": "1"}], "meta": {"row_count": 1}},
            ]
        )
        with patch.object(execution, "_invoke_tool", invoke_mock), patch.object(
            execution, "_propose_execution", side_effect=AssertionError("should not propose")
        ):
            out = asyncio.run(execution.executioner(state, config={}))

        self.assertEqual(invoke_mock.await_count, 2)
        first_call = invoke_mock.await_args_list[0]
        second_call = invoke_mock.await_args_list[1]
        self.assertEqual(first_call.args[0], "read_file")
        self.assertEqual(second_call.args[0], "execute_sql")
        self.assertEqual(out["steps"][0].status, "done")


if __name__ == "__main__":
    unittest.main()

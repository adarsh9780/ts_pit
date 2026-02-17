import importlib
import unittest
from unittest.mock import patch

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage


class ToolErrorRetryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import ts_pit.agent_v2.graph as graph_module
        except ImportError:
            import sys
            from pathlib import Path

            sys.path.append(str(Path(__file__).parent.parent.parent / "src"))
            import ts_pit.agent_v2.graph as graph_module

        cls.graph = importlib.reload(graph_module)

    def test_should_continue_retries_after_tool_error_within_cap(self):
        state = {
            "messages": [
                HumanMessage(content="please verify"),
                AIMessage(
                    content="",
                    tool_calls=[{"id": "c1", "name": "execute_python", "args": {}}],
                ),
                ToolMessage(
                    content='{"ok": false, "error": {"code": "INVALID_INPUT", "message": "bad input"}}',
                    tool_call_id="c1",
                ),
                AIMessage(content="There was an error and I cannot proceed."),
            ]
        }

        cfg = type(
            "Cfg",
            (),
            {"get_agent_retry_config": lambda self: {"max_tool_error_retries": 2}},
        )()
        with patch.object(self.graph, "get_config", return_value=cfg):
            decision = self.graph.should_continue(state)
        self.assertEqual(decision, "diagnose_empty_result")

    def test_should_continue_ends_when_retry_cap_exhausted(self):
        state = {
            "messages": [
                HumanMessage(content="please verify"),
                AIMessage(
                    content="",
                    tool_calls=[{"id": "c1", "name": "execute_python", "args": {}}],
                ),
                ToolMessage(
                    content='{"ok": false, "error": {"code": "INVALID_INPUT", "message": "bad input"}}',
                    tool_call_id="c1",
                ),
                SystemMessage(content="retry 1", id="agent-v2-tool-error-retry-1"),
                AIMessage(content="Still failing."),
            ]
        }

        cfg = type(
            "Cfg",
            (),
            {"get_agent_retry_config": lambda self: {"max_tool_error_retries": 1}},
        )()
        with patch.object(self.graph, "get_config", return_value=cfg):
            decision = self.graph.should_continue(state)
        self.assertEqual(decision, "__end__")

    def test_diagnose_empty_result_node_adds_guidance_only(self):
        state = {
            "messages": [
                HumanMessage(content="please verify"),
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "c1",
                            "name": "execute_sql",
                            "args": {"query": "SELECT 1"},
                        }
                    ],
                ),
                ToolMessage(
                    content='{"ok": false, "error": {"code": "DB_ERROR", "message": "bad sql"}}',
                    tool_call_id="c1",
                ),
            ]
        }
        out = self.graph.diagnose_empty_result_node(state, config={})
        msgs = out.get("messages", [])
        self.assertEqual(len(msgs), 1)
        self.assertIsInstance(msgs[0], SystemMessage)

    def test_should_continue_blocks_identical_retry_call_for_correctable_error(self):
        state = {
            "messages": [
                HumanMessage(content="please verify"),
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "c1",
                            "name": "execute_sql",
                            "args": {"query": "PRAGMA table_info(alerts)"},
                        }
                    ],
                ),
                ToolMessage(
                    content='{"ok": false, "error": {"code": "READ_ONLY_ENFORCED", "message": "Only SELECT statements are allowed."}}',
                    tool_call_id="c1",
                ),
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "c2",
                            "name": "execute_sql",
                            "args": {"query": "PRAGMA table_info(alerts)"},
                        }
                    ],
                ),
            ]
        }

        cfg = type(
            "Cfg",
            (),
            {"get_agent_retry_config": lambda self: {"max_tool_error_retries": 3}},
        )()
        with patch.object(self.graph, "get_config", return_value=cfg):
            decision = self.graph.should_continue(state)
        self.assertEqual(decision, "diagnose_empty_result")

    def test_should_continue_allows_changed_retry_call(self):
        state = {
            "messages": [
                HumanMessage(content="please verify"),
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "c1",
                            "name": "execute_sql",
                            "args": {"query": "PRAGMA table_info(alerts)"},
                        }
                    ],
                ),
                ToolMessage(
                    content='{"ok": false, "error": {"code": "READ_ONLY_ENFORCED", "message": "Only SELECT statements are allowed."}}',
                    tool_call_id="c1",
                ),
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "c2",
                            "name": "read_file",
                            "args": {"path": "artifacts/DB_SCHEMA_REFERENCE.yaml"},
                        }
                    ],
                ),
            ]
        }

        cfg = type(
            "Cfg",
            (),
            {"get_agent_retry_config": lambda self: {"max_tool_error_retries": 3}},
        )()
        with patch.object(self.graph, "get_config", return_value=cfg):
            decision = self.graph.should_continue(state)
        self.assertEqual(decision, "tools")

    def test_schema_preflight_injects_schema_read_for_db_turn(self):
        state = {
            "needs_db": True,
            "messages": [HumanMessage(content="count alerts by ticker")],
        }
        out = self.graph.schema_preflight_node(state, config={})
        self.assertTrue(out.get("needs_schema_preflight"))
        msgs = out.get("messages", [])
        self.assertEqual(len(msgs), 1)
        self.assertIsInstance(msgs[0], AIMessage)
        calls = getattr(msgs[0], "tool_calls", None) or []
        self.assertEqual(calls[0]["name"], "read_file")
        self.assertEqual(calls[0]["args"]["path"], "artifacts/DB_SCHEMA_REFERENCE.yaml")
        self.assertTrue(str(calls[0]["id"]).startswith("call_"))
        self.assertLessEqual(len(str(calls[0]["id"])), 40)

    def test_validate_answer_requests_methodology_sections_after_sql(self):
        state = {
            "messages": [
                HumanMessage(content="show grouped totals"),
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "c1",
                            "name": "execute_sql",
                            "args": {"query": "SELECT 1"},
                        }
                    ],
                ),
                ToolMessage(
                    content='{"ok": true, "data": [{"n": 1}]}', tool_call_id="c1"
                ),
                AIMessage(content="Here is the output table."),
            ]
        }
        out = self.graph.validate_answer_node(state, config={})
        self.assertTrue(out.get("needs_answer_rewrite"))
        msgs = out.get("messages", [])
        self.assertEqual(len(msgs), 1)
        self.assertIsInstance(msgs[0], SystemMessage)

    def test_should_continue_routes_text_only_to_diagnose_after_empty_sql(self):
        """Text-only LLM response after empty SQL should go to diagnose."""
        state = {
            "messages": [
                HumanMessage(content="summarize alerts for date"),
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "c1",
                            "name": "execute_sql",
                            "args": {
                                "query": "SELECT * FROM alerts WHERE alert_date='2025-09-01'"
                            },
                        }
                    ],
                ),
                ToolMessage(
                    content='{"ok": true, "data": [], "meta": {"row_count": 0}}',
                    tool_call_id="c1",
                ),
                AIMessage(content="No alerts found."),
            ]
        }

        cfg = type(
            "Cfg",
            (),
            {"get_agent_retry_config": lambda self: {"max_tool_error_retries": 2}},
        )()
        with patch.object(self.graph, "get_config", return_value=cfg):
            decision = self.graph.should_continue(state)
        self.assertEqual(decision, "diagnose_empty_result")

    def test_should_continue_blocks_identical_sql_retry_after_empty_result(self):
        query = "SELECT * FROM alerts WHERE alert_date='2025-09-01'"
        state = {
            "messages": [
                HumanMessage(content="summarize alerts for date"),
                AIMessage(
                    content="",
                    tool_calls=[
                        {"id": "c1", "name": "execute_sql", "args": {"query": query}}
                    ],
                ),
                ToolMessage(
                    content='{"ok": true, "data": [], "meta": {"row_count": 0}}',
                    tool_call_id="c1",
                ),
                AIMessage(
                    content="",
                    tool_calls=[
                        {"id": "c2", "name": "execute_sql", "args": {"query": query}}
                    ],
                ),
            ]
        }

        cfg = type(
            "Cfg",
            (),
            {"get_agent_retry_config": lambda self: {"max_tool_error_retries": 3}},
        )()
        with patch.object(self.graph, "get_config", return_value=cfg):
            decision = self.graph.should_continue(state)
        self.assertEqual(decision, "diagnose_empty_result")

    def test_should_continue_allows_changed_sql_retry_after_empty_result(self):
        state = {
            "messages": [
                HumanMessage(content="summarize alerts for date"),
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "c1",
                            "name": "execute_sql",
                            "args": {
                                "query": "SELECT * FROM alerts WHERE alert_date='2025-09-01'"
                            },
                        }
                    ],
                ),
                ToolMessage(
                    content='{"ok": true, "data": [], "meta": {"row_count": 0}}',
                    tool_call_id="c1",
                ),
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "c2",
                            "name": "execute_sql",
                            "args": {
                                "query": "SELECT * FROM alerts WHERE DATE(alert_date)='2025-09-01'"
                            },
                        }
                    ],
                ),
            ]
        }

        cfg = type(
            "Cfg",
            (),
            {"get_agent_retry_config": lambda self: {"max_tool_error_retries": 3}},
        )()
        with patch.object(self.graph, "get_config", return_value=cfg):
            decision = self.graph.should_continue(state)
        self.assertEqual(decision, "tools")

    def test_should_continue_routes_text_only_to_diagnose_after_empty_non_sql(self):
        """Text-only LLM response after empty non-SQL tool should go to diagnose."""
        state = {
            "messages": [
                HumanMessage(content="find related coverage"),
                AIMessage(
                    content="",
                    tool_calls=[
                        {"id": "c1", "name": "search_web", "args": {"query": "foo"}}
                    ],
                ),
                ToolMessage(
                    content='{"ok": true, "data": {"combined": [], "web": [], "news": []}, "meta": {"combined_count": 0, "web_count": 0, "news_count": 0}}',
                    tool_call_id="c1",
                ),
                AIMessage(content="No web results found."),
            ]
        }
        cfg = type(
            "Cfg",
            (),
            {"get_agent_retry_config": lambda self: {"max_tool_error_retries": 2}},
        )()
        with patch.object(self.graph, "get_config", return_value=cfg):
            decision = self.graph.should_continue(state)
        self.assertEqual(decision, "diagnose_empty_result")

    def test_should_continue_routes_text_only_to_diagnose_after_zero_aggregate(self):
        """Text-only LLM response after zero-aggregate SQL should go to diagnose."""
        state = {
            "messages": [
                HumanMessage(content="count alerts on date"),
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "c1",
                            "name": "execute_sql",
                            "args": {
                                "query": "SELECT COUNT(*) AS total_alerts FROM alerts WHERE alert_date='2025-09-01'"
                            },
                        }
                    ],
                ),
                ToolMessage(
                    content='{"ok": true, "data": [{"total_alerts": 0}], "meta": {"row_count": 1, "executed_query": "SELECT COUNT(*) AS total_alerts FROM alerts WHERE alert_date=\'2025-09-01\'"}}',
                    tool_call_id="c1",
                ),
                AIMessage(content="No alerts found."),
            ]
        }
        cfg = type(
            "Cfg",
            (),
            {"get_agent_retry_config": lambda self: {"max_tool_error_retries": 2}},
        )()
        with patch.object(self.graph, "get_config", return_value=cfg):
            decision = self.graph.should_continue(state)
        self.assertEqual(decision, "diagnose_empty_result")

    def test_messages_for_model_drops_dangling_assistant_tool_calls(self):
        state = {
            "messages": [
                SystemMessage(content="base", id="agent-v2-system-prompt"),
                HumanMessage(content="question"),
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "c1",
                            "name": "execute_sql",
                            "args": {"query": "SELECT 1"},
                        }
                    ],
                ),
                HumanMessage(content="follow-up"),
                AIMessage(content="answer"),
            ]
        }
        msgs = self.graph._messages_for_model(state)
        tool_call_msgs = [
            m
            for m in msgs
            if getattr(m, "type", "") == "ai" and getattr(m, "tool_calls", None)
        ]
        self.assertEqual(len(tool_call_msgs), 0)

    def test_messages_for_model_includes_retry_control_system_messages(self):
        state = {
            "messages": [
                SystemMessage(content="base", id="agent-v2-system-prompt"),
                HumanMessage(content="count alerts"),
                SystemMessage(
                    content="retry with revised sql",
                    id="agent-v2-tool-error-retry-1",
                ),
                SystemMessage(
                    content="rewrite the answer format",
                    id="agent-v2-answer-format-rewrite-1",
                ),
            ]
        }
        msgs = self.graph._messages_for_model(state)
        ids = [
            str(getattr(m, "id", "") or "")
            for m in msgs
            if getattr(m, "type", "") == "system"
        ]
        self.assertIn("agent-v2-tool-error-retry-1", ids)
        self.assertIn("agent-v2-answer-format-rewrite-1", ids)

    def test_validate_answer_skips_rewrite_when_last_tool_returned_empty(self):
        """validate_answer should skip rewrite when last tool returned empty data."""
        state = {
            "messages": [
                HumanMessage(content="summarize alerts for date"),
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "c1",
                            "name": "execute_sql",
                            "args": {
                                "query": "SELECT * FROM alerts WHERE alert_date='2025-09-01'"
                            },
                        }
                    ],
                ),
                ToolMessage(
                    content='{"ok": true, "data": [], "meta": {"row_count": 0}}',
                    tool_call_id="c1",
                ),
                AIMessage(content="No alerts found for the requested date."),
            ]
        }
        out = self.graph.validate_answer_node(state, config={})
        self.assertFalse(out.get("needs_answer_rewrite"))

    def test_should_continue_intercepts_identical_tool_call_after_empty(self):
        """When LLM issues an identical tool_call after empty result, route to retry."""
        query = "SELECT * FROM alerts WHERE alert_date='2025-09-01'"
        state = {
            "messages": [
                HumanMessage(content="summarize alerts for date"),
                AIMessage(
                    content="",
                    tool_calls=[
                        {"id": "c1", "name": "execute_sql", "args": {"query": query}}
                    ],
                ),
                ToolMessage(
                    content='{"ok": true, "data": [], "meta": {"row_count": 0}}',
                    tool_call_id="c1",
                ),
                AIMessage(
                    content="",
                    tool_calls=[
                        {"id": "c2", "name": "execute_sql", "args": {"query": query}}
                    ],
                ),
            ]
        }
        cfg = type(
            "Cfg",
            (),
            {"get_agent_retry_config": lambda self: {"max_tool_error_retries": 3}},
        )()
        with patch.object(self.graph, "get_config", return_value=cfg):
            decision = self.graph.should_continue(state)
        self.assertEqual(decision, "diagnose_empty_result")

    def test_should_continue_allows_different_tool_call_after_empty(self):
        """When LLM issues a different tool_call after empty result, route to tools."""
        state = {
            "messages": [
                HumanMessage(content="summarize alerts for date"),
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "c1",
                            "name": "execute_sql",
                            "args": {
                                "query": "SELECT * FROM alerts WHERE alert_date='2025-09-01'"
                            },
                        }
                    ],
                ),
                ToolMessage(
                    content='{"ok": true, "data": [], "meta": {"row_count": 0}}',
                    tool_call_id="c1",
                ),
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "c2",
                            "name": "execute_sql",
                            "args": {"query": "SELECT * FROM alerts LIMIT 5"},
                        }
                    ],
                ),
            ]
        }
        cfg = type(
            "Cfg",
            (),
            {"get_agent_retry_config": lambda self: {"max_tool_error_retries": 3}},
        )()
        with patch.object(self.graph, "get_config", return_value=cfg):
            decision = self.graph.should_continue(state)
        self.assertEqual(decision, "tools")

    def test_extract_sql_filters_parses_where_clause(self):
        """_extract_sql_filters should extract table, column, and value from WHERE."""
        filters = self.graph._extract_sql_filters(
            "SELECT * FROM alerts WHERE alert_date = '2025-09-01'"
        )
        self.assertEqual(len(filters), 1)
        self.assertEqual(filters[0]["table"], "alerts")
        self.assertEqual(filters[0]["column"], "alert_date")
        self.assertEqual(filters[0]["value"], "2025-09-01")

    def test_diagnose_empty_sql_includes_must_issue_tool_call(self):
        """SQL diagnostic message must instruct the LLM to issue a tool call."""
        call_info = {
            "name": "execute_sql",
            "args": {"query": "SELECT * FROM alerts WHERE alert_date='2025-09-01'"},
        }
        content = self.graph._diagnose_empty_sql(call_info)
        self.assertIn("MUST issue", content)
        self.assertIn("execute_sql", content)

    def test_diagnose_tool_error_includes_python_hint_for_keyerror(self):
        """Python KeyError diagnostic should mention checking keys."""
        call_info = {
            "name": "execute_python",
            "error_code": "PYTHON_EXEC_ERROR",
            "error_message": "KeyError: 'nonexistent_column'",
        }
        content = self.graph._diagnose_tool_error(call_info)
        self.assertIn("KeyError", content)
        self.assertIn("key/column", content)

    def test_diagnose_empty_result_node_sql_produces_actionable_guidance(self):
        """diagnose_empty_result_node should produce SQL-specific guidance."""
        state = {
            "messages": [
                HumanMessage(content="summarize alerts"),
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "c1",
                            "name": "execute_sql",
                            "args": {
                                "query": "SELECT * FROM alerts WHERE alert_date='2025-09-01'"
                            },
                        }
                    ],
                ),
                ToolMessage(
                    content='{"ok": true, "data": [], "meta": {"row_count": 0}}',
                    tool_call_id="c1",
                ),
            ]
        }
        out = self.graph.diagnose_empty_result_node(state, config={})
        msgs = out.get("messages", [])
        self.assertEqual(len(msgs), 1)
        self.assertIsInstance(msgs[0], SystemMessage)
        self.assertIn("MUST issue", msgs[0].content)

    # ---------------------------------------------------------------
    #  SQL filter parsing – edge cases
    # ---------------------------------------------------------------

    def test_extract_sql_filters_multiple_conditions(self):
        """Parser should extract all AND conditions from WHERE clause."""
        filters = self.graph._extract_sql_filters(
            "SELECT * FROM alerts WHERE ticker = 'AAPL' AND alert_date = '2025-09-01'"
        )
        self.assertEqual(len(filters), 2)
        columns = {f["column"] for f in filters}
        self.assertIn("ticker", columns)
        self.assertIn("alert_date", columns)

    def test_extract_sql_filters_quoted_column_names(self):
        """Parser should handle quoted column names like \"Alert date\"."""
        filters = self.graph._extract_sql_filters(
            """SELECT * FROM alerts WHERE "Alert date" = '2025-09-01' """
        )
        self.assertEqual(len(filters), 1)
        self.assertEqual(filters[0]["column"], "Alert date")
        self.assertEqual(filters[0]["value"], "2025-09-01")

    def test_extract_sql_filters_like_operator(self):
        """Parser should extract LIKE conditions."""
        filters = self.graph._extract_sql_filters(
            "SELECT * FROM alerts WHERE alert_date LIKE '2025-09%'"
        )
        self.assertEqual(len(filters), 1)
        self.assertEqual(filters[0]["column"], "alert_date")
        self.assertEqual(filters[0]["value"], "2025-09%")

    def test_extract_sql_filters_no_where_clause(self):
        """Parser should return empty list when no WHERE clause present."""
        filters = self.graph._extract_sql_filters(
            "SELECT * FROM alerts ORDER BY alert_date LIMIT 10"
        )
        self.assertEqual(len(filters), 0)

    def test_extract_sql_filters_with_group_by(self):
        """Parser should stop at GROUP BY and not leak into it."""
        filters = self.graph._extract_sql_filters(
            "SELECT ticker, COUNT(*) FROM alerts WHERE alert_date = '2025-09-01' "
            "GROUP BY ticker ORDER BY ticker"
        )
        self.assertEqual(len(filters), 1)
        self.assertEqual(filters[0]["column"], "alert_date")

    # ---------------------------------------------------------------
    #  SQL diagnostic with mocked sample data
    # ---------------------------------------------------------------

    def test_diagnose_empty_sql_includes_sample_values_when_available(self):
        """When _run_sample_query returns data, the hint must contain those values."""
        call_info = {
            "name": "execute_sql",
            "args": {"query": "SELECT * FROM alerts WHERE alert_date='2025-09-01'"},
        }
        sample_values = [
            "2025-09-01 00:00:00",
            "2025-08-31 00:00:00",
            "2025-08-30 00:00:00",
        ]
        with patch.object(self.graph, "_run_sample_query", return_value=sample_values):
            with patch.object(
                self.graph, "_resolve_physical_column", return_value="Alert date"
            ):
                content = self.graph._diagnose_empty_sql(call_info)
        # The diagnostic should include the actual sample values
        self.assertIn("2025-09-01 00:00:00", content)
        self.assertIn("Alert date", content)
        self.assertIn("MUST issue", content)

    def test_diagnose_empty_sql_no_samples_still_gives_guidance(self):
        """Even without sample data, diagnostic should give actionable guidance."""
        call_info = {
            "name": "execute_sql",
            "args": {"query": "SELECT * FROM alerts WHERE ticker='UNKNOWN'"},
        }
        with patch.object(self.graph, "_run_sample_query", return_value=[]):
            content = self.graph._diagnose_empty_sql(call_info)
        self.assertIn("MUST issue", content)
        self.assertIn("execute_sql", content)

    def test_diagnose_empty_sql_no_query_in_args(self):
        """Missing query in args should still produce guidance."""
        call_info = {"name": "execute_sql", "args": {}}
        content = self.graph._diagnose_empty_sql(call_info)
        self.assertIn("MUST issue", content)

    # ---------------------------------------------------------------
    #  Python error diagnostics – all error categories
    # ---------------------------------------------------------------

    def test_diagnose_tool_error_python_typeerror(self):
        """TypeError diagnostic should suggest type conversions."""
        call_info = {
            "name": "execute_python",
            "error_code": "PYTHON_EXEC_ERROR",
            "error_message": "TypeError: unsupported operand type(s) for +: 'int' and 'str'",
        }
        content = self.graph._diagnose_tool_error(call_info)
        self.assertIn("TypeError", content)
        self.assertIn("type conversion", content.lower())

    def test_diagnose_tool_error_python_import_error(self):
        """ImportError diagnostic should mention checking capabilities."""
        call_info = {
            "name": "execute_python",
            "error_code": "PYTHON_EXEC_ERROR",
            "error_message": "ModuleNotFoundError: No module named 'requests'",
        }
        content = self.graph._diagnose_tool_error(call_info)
        self.assertIn("import failed", content.lower())
        self.assertIn("get_python_capabilities", content)

    def test_diagnose_tool_error_python_nameerror(self):
        """NameError diagnostic should mention variable assignment."""
        call_info = {
            "name": "execute_python",
            "error_code": "PYTHON_EXEC_ERROR",
            "error_message": "NameError: name 'df' is not defined",
        }
        content = self.graph._diagnose_tool_error(call_info)
        self.assertIn("not defined", content.lower())
        self.assertIn("input_data", content)

    def test_diagnose_tool_error_sql_preserves_error_message(self):
        """SQL error diagnostic should include the original error message."""
        call_info = {
            "name": "execute_sql",
            "error_code": "DB_ERROR",
            "error_message": "no such column: foo_bar",
        }
        content = self.graph._diagnose_tool_error(call_info)
        self.assertIn("no such column: foo_bar", content)
        self.assertIn("execute_sql", content)

    # ---------------------------------------------------------------
    #  Python empty result diagnostic
    # ---------------------------------------------------------------

    def test_diagnose_empty_python_mentions_result_variable(self):
        """Empty Python diagnostic should mention checking result assignment."""
        call_info = {
            "name": "execute_python",
            "args": {"code": "data = input_data.get('rows', [])\nresult = None"},
        }
        content = self.graph._diagnose_empty_python(call_info, messages=[])
        self.assertIn("result", content)
        self.assertIn("MUST issue", content)

    def test_diagnose_empty_python_truncates_long_code(self):
        """Long code should be truncated in the diagnostic preview."""
        long_code = "x = 1\n" * 200  # very long code
        call_info = {
            "name": "execute_python",
            "args": {"code": long_code},
        }
        content = self.graph._diagnose_empty_python(call_info, messages=[])
        self.assertIn("...", content)
        self.assertTrue(len(content) < len(long_code) + 500)

    # ---------------------------------------------------------------
    #  Generic tool diagnostic
    # ---------------------------------------------------------------

    def test_diagnose_empty_generic_includes_tool_name(self):
        """Generic diagnostic should include the tool name."""
        call_info = {"name": "search_web_news"}
        content = self.graph._diagnose_empty_generic(call_info)
        self.assertIn("search_web_news", content)
        self.assertIn("MUST issue", content)

    # ---------------------------------------------------------------
    #  Full retry flow simulation – multi-iteration
    # ---------------------------------------------------------------

    def test_retry_cap_enforced_after_multiple_diagnostic_cycles(self):
        """After max_tool_error_retries diagnostic cycles, should_continue must end."""
        state = {
            "messages": [
                HumanMessage(content="show alerts for September"),
                # Iteration 0: SQL empty
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "c1",
                            "name": "execute_sql",
                            "args": {
                                "query": "SELECT * FROM alerts WHERE alert_date='2025-09-01'"
                            },
                        }
                    ],
                ),
                ToolMessage(
                    content='{"ok": true, "data": [], "meta": {"row_count": 0}}',
                    tool_call_id="c1",
                ),
                # Diagnostic 1 injected
                SystemMessage(
                    content="Diagnostic: try DATE()", id="agent-v2-tool-error-retry-1"
                ),
                # Iteration 1: LLM retried but still empty
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "c2",
                            "name": "execute_sql",
                            "args": {
                                "query": "SELECT * FROM alerts WHERE DATE(alert_date)='2025-09-01'"
                            },
                        }
                    ],
                ),
                ToolMessage(
                    content='{"ok": true, "data": [], "meta": {"row_count": 0}}',
                    tool_call_id="c2",
                ),
                # Diagnostic 2 injected
                SystemMessage(
                    content="Diagnostic: try LIKE", id="agent-v2-tool-error-retry-2"
                ),
                # Iteration 2: LLM gave up, responded with text
                AIMessage(content="I could not find any data for this date."),
            ]
        }
        # With max_retries=2, we've exhausted our budget (2 retry messages exist)
        cfg = type(
            "Cfg",
            (),
            {"get_agent_retry_config": lambda self: {"max_tool_error_retries": 2}},
        )()
        with patch.object(self.graph, "get_config", return_value=cfg):
            decision = self.graph.should_continue(state)
        self.assertEqual(decision, "validate_answer")

    def test_first_diagnostic_cycle_routes_to_diagnose(self):
        """On first empty result with 0 prior retries, should route to diagnose."""
        state = {
            "messages": [
                HumanMessage(content="show alerts for September"),
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "c1",
                            "name": "execute_sql",
                            "args": {
                                "query": "SELECT * FROM alerts WHERE alert_date='2025-09-01'"
                            },
                        }
                    ],
                ),
                ToolMessage(
                    content='{"ok": true, "data": [], "meta": {"row_count": 0}}',
                    tool_call_id="c1",
                ),
                # LLM responded with text (no tool call) on first attempt
                AIMessage(content="No data found."),
            ]
        }
        cfg = type(
            "Cfg",
            (),
            {"get_agent_retry_config": lambda self: {"max_tool_error_retries": 3}},
        )()
        with patch.object(self.graph, "get_config", return_value=cfg):
            decision = self.graph.should_continue(state)
        self.assertEqual(decision, "diagnose_empty_result")

    def test_diagnostic_node_increments_attempt_counter(self):
        """Each call to diagnose_empty_result_node should increment the attempt ID."""
        # No prior retry messages → next_attempt = 1
        state_0 = {
            "messages": [
                HumanMessage(content="show alerts"),
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "c1",
                            "name": "execute_sql",
                            "args": {"query": "SELECT * FROM alerts WHERE x='1'"},
                        }
                    ],
                ),
                ToolMessage(
                    content='{"ok": true, "data": [], "meta": {"row_count": 0}}',
                    tool_call_id="c1",
                ),
            ]
        }
        out_0 = self.graph.diagnose_empty_result_node(state_0, config={})
        msg_0 = out_0["messages"][0]
        self.assertEqual(msg_0.id, "agent-v2-tool-error-retry-1")

        # One prior retry message → next_attempt = 2
        state_1 = {
            "messages": [
                HumanMessage(content="show alerts"),
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "c1",
                            "name": "execute_sql",
                            "args": {"query": "SELECT * FROM alerts WHERE x='1'"},
                        }
                    ],
                ),
                ToolMessage(
                    content='{"ok": true, "data": [], "meta": {"row_count": 0}}',
                    tool_call_id="c1",
                ),
                SystemMessage(content="retry 1", id="agent-v2-tool-error-retry-1"),
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "c2",
                            "name": "execute_sql",
                            "args": {"query": "SELECT * FROM alerts WHERE x='2'"},
                        }
                    ],
                ),
                ToolMessage(
                    content='{"ok": true, "data": [], "meta": {"row_count": 0}}',
                    tool_call_id="c2",
                ),
            ]
        }
        out_1 = self.graph.diagnose_empty_result_node(state_1, config={})
        msg_1 = out_1["messages"][0]
        self.assertEqual(msg_1.id, "agent-v2-tool-error-retry-2")

    def test_diagnostic_node_returns_empty_when_no_issue(self):
        """When there's no failed or empty call, node should return empty dict."""
        state = {
            "messages": [
                HumanMessage(content="hello"),
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "c1",
                            "name": "execute_sql",
                            "args": {"query": "SELECT 1"},
                        }
                    ],
                ),
                ToolMessage(
                    content='{"ok": true, "data": [{"n": 1}], "meta": {"row_count": 1}}',
                    tool_call_id="c1",
                ),
            ]
        }
        out = self.graph.diagnose_empty_result_node(state, config={})
        self.assertEqual(out, {})

    def test_diagnostic_dispatches_sql_vs_python_vs_generic(self):
        """Node should produce different content for SQL, Python, and other tools."""

        def make_state(tool_name):
            return {
                "messages": [
                    HumanMessage(content="test"),
                    AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "id": "c1",
                                "name": tool_name,
                                "args": {"query": "x"}
                                if "sql" in tool_name
                                else {"code": "x"}
                                if "python" in tool_name
                                else {"q": "x"},
                            }
                        ],
                    ),
                    ToolMessage(
                        content='{"ok": true, "data": [], "meta": {"row_count": 0}}',
                        tool_call_id="c1",
                    ),
                ]
            }

        out_sql = self.graph.diagnose_empty_result_node(
            make_state("execute_sql"), config={}
        )
        out_py = self.graph.diagnose_empty_result_node(
            make_state("execute_python"), config={}
        )
        out_web = self.graph.diagnose_empty_result_node(
            make_state("search_web"), config={}
        )

        # Each should produce a SystemMessage but with different content
        sql_content = out_sql["messages"][0].content
        py_content = out_py["messages"][0].content
        web_content = out_web["messages"][0].content

        self.assertIn("execute_sql", sql_content)
        self.assertIn("execute_python", py_content)
        self.assertIn("search_web", web_content)

        # All should demand a tool call
        for content in [sql_content, py_content, web_content]:
            self.assertIn("MUST issue", content)

    def test_validate_answer_still_skips_when_diagnostic_exhausted(self):
        """After retries exhausted and empty result, validate_answer should skip rewrite."""
        state = {
            "messages": [
                HumanMessage(content="show alerts"),
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "c1",
                            "name": "execute_sql",
                            "args": {"query": "SELECT * FROM alerts WHERE x='1'"},
                        }
                    ],
                ),
                ToolMessage(
                    content='{"ok": true, "data": [], "meta": {"row_count": 0}}',
                    tool_call_id="c1",
                ),
                SystemMessage(content="diagnostic 1", id="agent-v2-tool-error-retry-1"),
                SystemMessage(content="diagnostic 2", id="agent-v2-tool-error-retry-2"),
                AIMessage(content="No data available for this query."),
            ]
        }
        out = self.graph.validate_answer_node(state, config={})
        self.assertFalse(out.get("needs_answer_rewrite"))

    # ---------------------------------------------------------------
    #  Bug fix: text→diagnose→text loop prevention
    # ---------------------------------------------------------------

    def test_text_only_after_diagnostic_goes_to_validate_not_loop(self):
        """THE BUG: text-only response after a diagnostic was already given
        must NOT loop back to diagnose. It should go to validate_answer."""
        state = {
            "messages": [
                HumanMessage(content="summarize alerts for September"),
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "c1",
                            "name": "execute_sql",
                            "args": {
                                "query": "SELECT * FROM alerts WHERE alert_date='2025-09-01'"
                            },
                        }
                    ],
                ),
                ToolMessage(
                    content='{"ok": true, "data": [], "meta": {"row_count": 0}}',
                    tool_call_id="c1",
                ),
                # Diagnostic was injected on first attempt
                SystemMessage(
                    content="Diagnostic: use DATE()", id="agent-v2-tool-error-retry-1"
                ),
                # LLM ignored diagnostic and responded with text
                AIMessage(content="There are no alerts for 1st September."),
            ]
        }
        cfg = type(
            "Cfg",
            (),
            {"get_agent_retry_config": lambda self: {"max_tool_error_retries": 3}},
        )()
        with patch.object(self.graph, "get_config", return_value=cfg):
            decision = self.graph.should_continue(state)
        # MUST go to validate_answer, NOT back to diagnose_empty_result
        self.assertEqual(decision, "validate_answer")

    def test_diagnostic_exists_since_last_tool_returns_true(self):
        """Helper should detect a diagnostic after the last ToolMessage."""
        messages = [
            HumanMessage(content="test"),
            AIMessage(
                content="", tool_calls=[{"id": "c1", "name": "execute_sql", "args": {}}]
            ),
            ToolMessage(content='{"ok": true, "data": []}', tool_call_id="c1"),
            SystemMessage(content="retry guidance", id="agent-v2-tool-error-retry-1"),
            AIMessage(content="No data."),
        ]
        self.assertTrue(self.graph._diagnostic_exists_since_last_tool(messages))

    def test_diagnostic_exists_since_last_tool_returns_false(self):
        """Helper should return False when no diagnostic exists after last tool."""
        messages = [
            HumanMessage(content="test"),
            AIMessage(
                content="", tool_calls=[{"id": "c1", "name": "execute_sql", "args": {}}]
            ),
            ToolMessage(content='{"ok": true, "data": []}', tool_call_id="c1"),
            AIMessage(content="No data."),
        ]
        self.assertFalse(self.graph._diagnostic_exists_since_last_tool(messages))

    def test_tool_calls_branch_still_retries_even_after_diagnostic(self):
        """When LLM issues a tool call (identical) after diagnostic, the tool_calls
        branch should still intercept and route to diagnose (up to the cap)."""
        query = "SELECT * FROM alerts WHERE alert_date='2025-09-01'"
        state = {
            "messages": [
                HumanMessage(content="show alerts"),
                AIMessage(
                    content="",
                    tool_calls=[
                        {"id": "c1", "name": "execute_sql", "args": {"query": query}}
                    ],
                ),
                ToolMessage(
                    content='{"ok": true, "data": [], "meta": {"row_count": 0}}',
                    tool_call_id="c1",
                ),
                SystemMessage(
                    content="Diagnostic: try DATE()", id="agent-v2-tool-error-retry-1"
                ),
                # LLM retried with tool_calls but same query
                AIMessage(
                    content="",
                    tool_calls=[
                        {"id": "c2", "name": "execute_sql", "args": {"query": query}}
                    ],
                ),
            ]
        }
        cfg = type(
            "Cfg",
            (),
            {"get_agent_retry_config": lambda self: {"max_tool_error_retries": 3}},
        )()
        with patch.object(self.graph, "get_config", return_value=cfg):
            decision = self.graph.should_continue(state)
        # The tool_calls branch should still intercept identical retries
        self.assertEqual(decision, "diagnose_empty_result")

    # ---------------------------------------------------------------
    #  Phase 3: route_after_tools tests
    # ---------------------------------------------------------------

    def test_route_after_tools_intercepts_empty_result(self):
        """route_after_tools should intercept empty result and route to diagnose."""
        state = {
            "messages": [
                HumanMessage(content="run sql"),
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "c1",
                            "name": "execute_sql",
                            "args": {"query": "SELECT 1"},
                        }
                    ],
                ),
                ToolMessage(
                    content='{"ok": true, "data": [], "meta": {"row_count": 0}}',
                    tool_call_id="c1",
                ),
            ]
        }
        decision = self.graph.route_after_tools(state)
        self.assertEqual(decision, "diagnose_empty_result")

    def test_route_after_tools_intercepts_failed_result(self):
        """route_after_tools should intercept failed result and route to diagnose."""
        state = {
            "messages": [
                HumanMessage(content="run sql"),
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "c1",
                            "name": "execute_sql",
                            "args": {"query": "SELECT 1"},
                        }
                    ],
                ),
                ToolMessage(
                    content='{"ok": false, "error": {"code": "DB_ERROR", "message": "fail"}}',
                    tool_call_id="c1",
                ),
            ]
        }
        decision = self.graph.route_after_tools(state)
        self.assertEqual(decision, "diagnose_empty_result")

    def test_route_after_tools_passes_success_to_agent(self):
        """route_after_tools should pass successful result to agent."""
        state = {
            "messages": [
                HumanMessage(content="run sql"),
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "c1",
                            "name": "execute_sql",
                            "args": {"query": "SELECT 1"},
                        }
                    ],
                ),
                ToolMessage(
                    content='{"ok": true, "data": [{"x": 1}], "meta": {"row_count": 1}}',
                    tool_call_id="c1",
                ),
            ]
        }
        decision = self.graph.route_after_tools(state)
        self.assertEqual(decision, "agent")

    def test_route_after_tools_respects_retry_cap(self):
        """route_after_tools should default to agent if retry cap hit."""
        # mock max retries = 0
        cfg = type(
            "Cfg",
            (),
            {"get_agent_retry_config": lambda self: {"max_tool_error_retries": 0}},
        )()
        with patch.object(self.graph, "get_config", return_value=cfg):
            state = {
                "messages": [
                    HumanMessage(content="run sql"),
                    AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "id": "c1",
                                "name": "execute_sql",
                                "args": {"query": "SELECT 1"},
                            }
                        ],
                    ),
                    ToolMessage(
                        content='{"ok": true, "data": [], "meta": {"row_count": 0}}',
                        tool_call_id="c1",
                    ),
                ]
            }
            decision = self.graph.route_after_tools(state)
            self.assertEqual(decision, "agent")


if __name__ == "__main__":
    unittest.main()

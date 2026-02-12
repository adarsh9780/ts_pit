import importlib
import unittest
from unittest.mock import patch

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage


class ToolErrorRetryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import backend.agent_v2.graph as graph_module

        cls.graph = importlib.reload(graph_module)

    def test_should_continue_retries_after_tool_error_within_cap(self):
        state = {
            "messages": [
                HumanMessage(content="please verify"),
                AIMessage(content="", tool_calls=[{"id": "c1", "name": "execute_python", "args": {}}]),
                ToolMessage(
                    content='{"ok": false, "error": {"code": "INVALID_INPUT", "message": "bad input"}}',
                    tool_call_id="c1",
                ),
                AIMessage(content="There was an error and I cannot proceed."),
            ]
        }

        cfg = type("Cfg", (), {"get_agent_v2_retry_config": lambda self: {"max_tool_error_retries": 2}})()
        with patch.object(self.graph, "get_config", return_value=cfg):
            decision = self.graph.should_continue(state)
        self.assertEqual(decision, "retry_after_tool_error")

    def test_should_continue_ends_when_retry_cap_exhausted(self):
        state = {
            "messages": [
                HumanMessage(content="please verify"),
                AIMessage(content="", tool_calls=[{"id": "c1", "name": "execute_python", "args": {}}]),
                ToolMessage(
                    content='{"ok": false, "error": {"code": "INVALID_INPUT", "message": "bad input"}}',
                    tool_call_id="c1",
                ),
                SystemMessage(content="retry 1", id="agent-v2-tool-error-retry-1"),
                AIMessage(content="Still failing."),
            ]
        }

        cfg = type("Cfg", (), {"get_agent_v2_retry_config": lambda self: {"max_tool_error_retries": 1}})()
        with patch.object(self.graph, "get_config", return_value=cfg):
            decision = self.graph.should_continue(state)
        self.assertEqual(decision, "__end__")

    def test_retry_after_tool_error_node_adds_guidance_only(self):
        state = {
            "messages": [
                HumanMessage(content="please verify"),
                AIMessage(
                    content="",
                    tool_calls=[{"id": "c1", "name": "execute_sql", "args": {"query": "SELECT 1"}}],
                ),
                ToolMessage(
                    content='{"ok": false, "error": {"code": "DB_ERROR", "message": "bad sql"}}',
                    tool_call_id="c1",
                ),
            ]
        }
        out = self.graph.retry_after_tool_error_node(state, config={})
        msgs = out.get("messages", [])
        self.assertEqual(len(msgs), 1)
        self.assertIsInstance(msgs[0], SystemMessage)

    def test_should_continue_blocks_identical_retry_call_for_correctable_error(self):
        state = {
            "messages": [
                HumanMessage(content="please verify"),
                AIMessage(content="", tool_calls=[{"id": "c1", "name": "execute_sql", "args": {"query": "PRAGMA table_info(alerts)"}}]),
                ToolMessage(
                    content='{"ok": false, "error": {"code": "READ_ONLY_ENFORCED", "message": "Only SELECT statements are allowed."}}',
                    tool_call_id="c1",
                ),
                AIMessage(content="", tool_calls=[{"id": "c2", "name": "execute_sql", "args": {"query": "PRAGMA table_info(alerts)"}}]),
            ]
        }

        cfg = type("Cfg", (), {"get_agent_v2_retry_config": lambda self: {"max_tool_error_retries": 3}})()
        with patch.object(self.graph, "get_config", return_value=cfg):
            decision = self.graph.should_continue(state)
        self.assertEqual(decision, "retry_after_tool_error")

    def test_should_continue_allows_changed_retry_call(self):
        state = {
            "messages": [
                HumanMessage(content="please verify"),
                AIMessage(content="", tool_calls=[{"id": "c1", "name": "execute_sql", "args": {"query": "PRAGMA table_info(alerts)"}}]),
                ToolMessage(
                    content='{"ok": false, "error": {"code": "READ_ONLY_ENFORCED", "message": "Only SELECT statements are allowed."}}',
                    tool_call_id="c1",
                ),
                AIMessage(content="", tool_calls=[{"id": "c2", "name": "read_file", "args": {"path": "artifacts/DB_SCHEMA_REFERENCE.yaml"}}]),
            ]
        }

        cfg = type("Cfg", (), {"get_agent_v2_retry_config": lambda self: {"max_tool_error_retries": 3}})()
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
                AIMessage(content="", tool_calls=[{"id": "c1", "name": "execute_sql", "args": {"query": "SELECT 1"}}]),
                ToolMessage(content='{"ok": true, "data": [{"n": 1}]}', tool_call_id="c1"),
                AIMessage(content="Here is the output table."),
            ]
        }
        out = self.graph.validate_answer_node(state, config={})
        self.assertTrue(out.get("needs_answer_rewrite"))
        msgs = out.get("messages", [])
        self.assertEqual(len(msgs), 1)
        self.assertIsInstance(msgs[0], SystemMessage)

    def test_should_continue_retries_after_empty_sql_result_within_cap(self):
        state = {
            "messages": [
                HumanMessage(content="summarize alerts for date"),
                AIMessage(content="", tool_calls=[{"id": "c1", "name": "execute_sql", "args": {"query": "SELECT * FROM alerts WHERE alert_date='2025-09-01'"}}]),
                ToolMessage(
                    content='{"ok": true, "data": [], "meta": {"row_count": 0}}',
                    tool_call_id="c1",
                ),
                AIMessage(content="No alerts found."),
            ]
        }

        cfg = type("Cfg", (), {"get_agent_v2_retry_config": lambda self: {"max_tool_error_retries": 2}})()
        with patch.object(self.graph, "get_config", return_value=cfg):
            decision = self.graph.should_continue(state)
        self.assertEqual(decision, "retry_after_tool_error")

    def test_should_continue_blocks_identical_sql_retry_after_empty_result(self):
        query = "SELECT * FROM alerts WHERE alert_date='2025-09-01'"
        state = {
            "messages": [
                HumanMessage(content="summarize alerts for date"),
                AIMessage(content="", tool_calls=[{"id": "c1", "name": "execute_sql", "args": {"query": query}}]),
                ToolMessage(
                    content='{"ok": true, "data": [], "meta": {"row_count": 0}}',
                    tool_call_id="c1",
                ),
                AIMessage(content="", tool_calls=[{"id": "c2", "name": "execute_sql", "args": {"query": query}}]),
            ]
        }

        cfg = type("Cfg", (), {"get_agent_v2_retry_config": lambda self: {"max_tool_error_retries": 3}})()
        with patch.object(self.graph, "get_config", return_value=cfg):
            decision = self.graph.should_continue(state)
        self.assertEqual(decision, "retry_after_tool_error")

    def test_should_continue_allows_changed_sql_retry_after_empty_result(self):
        state = {
            "messages": [
                HumanMessage(content="summarize alerts for date"),
                AIMessage(content="", tool_calls=[{"id": "c1", "name": "execute_sql", "args": {"query": "SELECT * FROM alerts WHERE alert_date='2025-09-01'"}}]),
                ToolMessage(
                    content='{"ok": true, "data": [], "meta": {"row_count": 0}}',
                    tool_call_id="c1",
                ),
                AIMessage(content="", tool_calls=[{"id": "c2", "name": "execute_sql", "args": {"query": "SELECT * FROM alerts WHERE DATE(alert_date)='2025-09-01'"}}]),
            ]
        }

        cfg = type("Cfg", (), {"get_agent_v2_retry_config": lambda self: {"max_tool_error_retries": 3}})()
        with patch.object(self.graph, "get_config", return_value=cfg):
            decision = self.graph.should_continue(state)
        self.assertEqual(decision, "tools")


if __name__ == "__main__":
    unittest.main()

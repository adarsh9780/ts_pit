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


if __name__ == "__main__":
    unittest.main()

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
        self.assertEqual(decision, "retry_failed_tool")

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

    def test_retry_failed_tool_node_reissues_last_failed_tool_call(self):
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
        out = self.graph.retry_failed_tool_node(state, config={})
        msgs = out.get("messages", [])
        self.assertEqual(len(msgs), 2)
        self.assertIsInstance(msgs[0], SystemMessage)
        self.assertIsInstance(msgs[1], AIMessage)
        retry_calls = getattr(msgs[1], "tool_calls", None) or []
        self.assertEqual(len(retry_calls), 1)
        self.assertEqual(retry_calls[0]["name"], "execute_sql")
        self.assertEqual(retry_calls[0]["args"], {"query": "SELECT 1"})


if __name__ == "__main__":
    unittest.main()

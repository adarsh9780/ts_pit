import unittest

from langchain_core.messages import AIMessage
from langchain_core.messages import HumanMessage

from backend.api.routers.agent import (
    _build_frontend_messages,
    _extract_fallback_ai_text,
    _should_stream_model_chunk,
)


class AgentStreamingTests(unittest.TestCase):
    def test_streams_agent_node(self):
        event = {"metadata": {"langgraph_node": "agent"}}
        self.assertTrue(_should_stream_model_chunk(event))

    def test_streams_direct_answer_node(self):
        event = {"metadata": {"langgraph_node": "direct_answer"}}
        self.assertTrue(_should_stream_model_chunk(event))

    def test_does_not_stream_other_nodes(self):
        event = {"metadata": {"langgraph_node": "tools"}}
        self.assertFalse(_should_stream_model_chunk(event))

    def test_extract_fallback_ai_text_from_chain_output_messages(self):
        event = {
            "data": {
                "output": {
                    "messages": [
                        AIMessage(content="**Plan:**\n1. Tell a joke to the user.")
                    ]
                }
            }
        }
        text = _extract_fallback_ai_text(event)
        self.assertIn("Plan", text)

    def test_extract_fallback_ai_text_ignores_non_ai_output(self):
        class _Msg:
            type = "system"
            content = "internal"

        event = {"data": {"output": {"messages": [_Msg()]}}}
        self.assertEqual(_extract_fallback_ai_text(event), "")

    def test_build_frontend_messages_keeps_multiple_assistant_messages_in_same_turn(self):
        state_messages = [
            HumanMessage(content="what can you do for me?"),
            AIMessage(content="Plan:\n1. Do A\n2. Do B"),
            AIMessage(content="Response:\nI can help with A and B."),
        ]

        result = _build_frontend_messages(state_messages)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["role"], "user")
        self.assertEqual(result[1]["role"], "agent")
        self.assertIn("Plan:", result[1]["content"])
        self.assertIn("1. Do A", result[1]["content"])
        self.assertIn("Response:", result[1]["content"])

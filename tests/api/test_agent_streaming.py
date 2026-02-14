import unittest

from backend.api.routers.agent import _should_stream_model_chunk


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


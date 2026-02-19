import asyncio
import unittest
from unittest.mock import patch

from ts_pit.azure_llm import AzureOpenAIModel


class _FakeChunk:
    def __init__(self, text: str):
        self.text = text


class _FakeModel:
    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        _ = (messages, stop, run_manager, kwargs)
        yield _FakeChunk("hello")
        yield _FakeChunk("world")

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        _ = (messages, stop, run_manager, kwargs)
        yield _FakeChunk("a")
        yield _FakeChunk("b")


class AzureStreamingDelegationTests(unittest.TestCase):
    def test_stream_delegates_to_wrapped_model(self):
        with patch.object(AzureOpenAIModel, "_initialize_model", autospec=True) as init_mock:
            init_mock.return_value = None
            model = AzureOpenAIModel()
        model._model = _FakeModel()
        model._refresh_model_if_needed = lambda: None

        chunks = list(model._stream(messages=[]))
        self.assertEqual([c.text for c in chunks], ["hello", "world"])

    def test_astream_delegates_to_wrapped_model(self):
        with patch.object(AzureOpenAIModel, "_initialize_model", autospec=True) as init_mock:
            init_mock.return_value = None
            model = AzureOpenAIModel()
        model._model = _FakeModel()
        model._refresh_model_if_needed = lambda: None

        async def _collect():
            out = []
            async for c in model._astream(messages=[]):
                out.append(c.text)
            return out

        chunks = asyncio.run(_collect())
        self.assertEqual(chunks, ["a", "b"])


if __name__ == "__main__":
    unittest.main()

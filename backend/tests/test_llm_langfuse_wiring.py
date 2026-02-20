import unittest
from unittest.mock import patch

from ts_pit import llm


class _ConfigStub:
    def __init__(self, provider: str):
        self.provider = provider

    def get_llm_config(self):
        if self.provider == "azure":
            return {
                "provider": "azure",
                "azure": {
                    "client_id": "client",
                    "tenant_id": "tenant",
                    "cert_path": "cert/path.pem",
                    "scope": "scope",
                    "deployment": "dep",
                    "endpoint": "https://example.test/",
                    "api_version": "2024-12-01-preview",
                    "api_key": "test-key",
                },
            }
        return {
            "provider": "gemini",
            "gemini": {
                "model": "gemini-2.5-flash",
                "api_key": "test-key",
            },
        }


class LlmLangfuseWiringTests(unittest.TestCase):
    def tearDown(self):
        llm._cached_llm = None

    def test_gemini_model_receives_callbacks(self):
        callback_obj = object()

        with patch.object(llm, "get_config", return_value=_ConfigStub("gemini")):
            with patch.object(
                llm,
                "get_langfuse_callbacks",
                return_value=(callback_obj,),
            ):
                with patch.object(llm, "init_chat_model", return_value="gem-model") as init_mock:
                    model = llm.get_llm_model()

        self.assertEqual(model, "gem-model")
        self.assertEqual(init_mock.call_args.kwargs.get("callbacks"), [callback_obj])

    def test_azure_model_receives_callbacks(self):
        callback_obj = object()

        with patch.object(llm, "get_config", return_value=_ConfigStub("azure")):
            with patch.object(
                llm,
                "get_langfuse_callbacks",
                return_value=(callback_obj,),
            ):
                with patch.object(llm, "AzureOpenAIModel", return_value="az-model") as model_ctor:
                    model = llm.get_llm_model()

        self.assertEqual(model, "az-model")
        self.assertEqual(model_ctor.call_args.kwargs.get("callbacks"), [callback_obj])


if __name__ == "__main__":
    unittest.main()

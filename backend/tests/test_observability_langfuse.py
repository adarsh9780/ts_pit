import os
import unittest
from unittest.mock import patch
import types

from ts_pit import observability


class _FakeCallbackHandler:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class _StrictPublicKeyHandler:
    def __init__(self, *, public_key=None):
        self.kwargs = {"public_key": public_key}


class LangfuseObservabilityTests(unittest.TestCase):
    def tearDown(self):
        observability.get_langfuse_callbacks.cache_clear()

    def test_disabled_returns_empty_callbacks(self):
        with patch.dict(os.environ, {}, clear=True):
            callbacks = observability.get_langfuse_callbacks()
        self.assertEqual(callbacks, ())

    def test_enabled_but_sdk_missing_returns_empty_callbacks(self):
        with patch.dict(
            os.environ,
            {
                "LANGFUSE_ENABLED": "true",
                "LANGFUSE_PUBLIC_KEY": "pk_test",
                "LANGFUSE_SECRET_KEY": "sk_test",
            },
            clear=True,
        ):
            with patch.object(
                observability, "_resolve_langfuse_handler_class", return_value=None
            ):
                callbacks = observability.get_langfuse_callbacks()
        self.assertEqual(callbacks, ())

    def test_enabled_builds_callback_handler(self):
        with patch.dict(
            os.environ,
            {
                "LANGFUSE_ENABLED": "true",
                "LANGFUSE_PUBLIC_KEY": "pk_test",
                "LANGFUSE_SECRET_KEY": "sk_test",
                "LANGFUSE_HOST": "http://localhost:3000",
                "LANGFUSE_RELEASE": "test-release",
                "LANGFUSE_DEBUG": "true",
            },
            clear=True,
        ):
            with patch.object(
                observability,
                "_resolve_langfuse_handler_class",
                return_value=_FakeCallbackHandler,
            ):
                callbacks = observability.get_langfuse_callbacks()

        self.assertEqual(len(callbacks), 1)
        self.assertIsInstance(callbacks[0], _FakeCallbackHandler)
        self.assertEqual(callbacks[0].kwargs["public_key"], "pk_test")
        self.assertEqual(callbacks[0].kwargs["secret_key"], "sk_test")
        self.assertEqual(callbacks[0].kwargs["host"], "http://localhost:3000")
        self.assertEqual(callbacks[0].kwargs["release"], "test-release")
        self.assertTrue(callbacks[0].kwargs["debug"])

    def test_allow_unauth_mode_without_keys(self):
        with patch.dict(
            os.environ,
            {
                "LANGFUSE_ENABLED": "true",
                "LANGFUSE_ALLOW_UNAUTH": "true",
                "LANGFUSE_HOST": "http://localhost:3000",
            },
            clear=True,
        ):
            with patch.object(
                observability,
                "_resolve_langfuse_handler_class",
                return_value=_FakeCallbackHandler,
            ):
                callbacks = observability.get_langfuse_callbacks()

        self.assertEqual(len(callbacks), 1)
        self.assertEqual(callbacks[0].kwargs["host"], "http://localhost:3000")
        self.assertNotIn("public_key", callbacks[0].kwargs)
        self.assertNotIn("secret_key", callbacks[0].kwargs)

    def test_handler_kwargs_are_filtered_by_constructor_signature(self):
        with patch.dict(
            os.environ,
            {
                "LANGFUSE_ENABLED": "true",
                "LANGFUSE_PUBLIC_KEY": "pk_test",
                "LANGFUSE_SECRET_KEY": "sk_test",
                "LANGFUSE_HOST": "http://localhost:3000",
                "LANGFUSE_RELEASE": "test-release",
                "LANGFUSE_DEBUG": "true",
            },
            clear=True,
        ):
            with patch.object(
                observability,
                "_resolve_langfuse_handler_class",
                return_value=_StrictPublicKeyHandler,
            ):
                callbacks = observability.get_langfuse_callbacks()

        self.assertEqual(len(callbacks), 1)
        self.assertEqual(callbacks[0].kwargs["public_key"], "pk_test")

    def test_initializes_langfuse_client_before_callback(self):
        client_obj = object()
        with patch.dict(
            os.environ,
            {
                "LANGFUSE_ENABLED": "true",
                "LANGFUSE_PUBLIC_KEY": "pk_test",
                "LANGFUSE_SECRET_KEY": "sk_test",
                "LANGFUSE_HOST": "http://localhost:3000",
                "LANGFUSE_RELEASE": "test-release",
                "LANGFUSE_DEBUG": "true",
            },
            clear=True,
        ):
            with patch.object(
                observability,
                "_resolve_langfuse_handler_class",
                return_value=_FakeCallbackHandler,
            ):
                with patch.object(
                    observability,
                    "_initialize_langfuse_client",
                    return_value=client_obj,
                ) as init_client:
                    callbacks = observability.get_langfuse_callbacks()

        self.assertEqual(len(callbacks), 1)
        init_client.assert_called_once_with(
            public_key="pk_test",
            secret_key="sk_test",
            host="http://localhost:3000",
            release="test-release",
            debug=True,
        )

    def test_resolve_handler_prefers_new_sdk_module(self):
        fake_module = types.SimpleNamespace(CallbackHandler=_FakeCallbackHandler)
        with patch.object(observability, "import_module", return_value=fake_module):
            callback_cls = observability._resolve_langfuse_handler_class()
        self.assertIs(callback_cls, _FakeCallbackHandler)

    def test_resolve_handler_falls_back_to_legacy_module(self):
        fake_module = types.SimpleNamespace(CallbackHandler=_FakeCallbackHandler)

        def _import_side_effect(name: str):
            if name == "langfuse.langchain":
                raise ModuleNotFoundError(name)
            if name == "langfuse.callback":
                return fake_module
            raise ModuleNotFoundError(name)

        with patch.object(
            observability, "import_module", side_effect=_import_side_effect
        ):
            callback_cls = observability._resolve_langfuse_handler_class()
        self.assertIs(callback_cls, _FakeCallbackHandler)


if __name__ == "__main__":
    unittest.main()

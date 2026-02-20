from __future__ import annotations

import os
from importlib import import_module
from functools import lru_cache
import inspect
from typing import Any

from .logger import logprint


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _resolve_langfuse_handler_class():
    module_candidates = (
        # Newer SDKs expose the LangChain callback handler here.
        "langfuse.langchain",
        # Older SDK path kept as fallback for compatibility.
        "langfuse.callback",
    )
    for module_name in module_candidates:
        try:
            module = import_module(module_name)
            callback_cls = getattr(module, "CallbackHandler", None)
            if callback_cls is not None:
                return callback_cls
        except Exception:
            continue
    return None


def _resolve_langfuse_client_class():
    try:
        module = import_module("langfuse")
        client_cls = getattr(module, "Langfuse", None)
        if client_cls is not None:
            return client_cls
    except Exception:
        return None
    return None


def _initialize_langfuse_client(
    *,
    public_key: str,
    secret_key: str,
    host: str,
    release: str,
    debug: bool,
):
    client_cls = _resolve_langfuse_client_class()
    if client_cls is None:
        return None
    kwargs: dict[str, Any] = {}
    if public_key:
        kwargs["public_key"] = public_key
    if secret_key:
        kwargs["secret_key"] = secret_key
    if host:
        kwargs["host"] = host
    if release:
        kwargs["release"] = release
    kwargs["debug"] = debug
    try:
        return client_cls(**kwargs)
    except Exception as exc:
        logprint(
            "Failed to initialize Langfuse client.",
            level="WARNING",
            exception=exc,
        )
        return None


@lru_cache(maxsize=1)
def get_langfuse_callbacks() -> tuple[Any, ...]:
    """Return Langfuse callback handler tuple, or empty tuple when disabled/unavailable."""
    enabled = _env_flag(
        "LANGFUSE_ENABLED",
        default=bool(
            os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY")
        ),
    )
    if not enabled:
        return ()

    callback_cls = _resolve_langfuse_handler_class()
    if callback_cls is None:
        logprint(
            "Langfuse SDK not installed; observability callbacks disabled.",
            level="WARNING",
        )
        return ()

    public_key = (os.getenv("LANGFUSE_PUBLIC_KEY") or "").strip()
    secret_key = (os.getenv("LANGFUSE_SECRET_KEY") or "").strip()
    host = (os.getenv("LANGFUSE_HOST") or "").strip()
    release = (os.getenv("LANGFUSE_RELEASE") or "").strip()
    debug = _env_flag("LANGFUSE_DEBUG", default=False)
    allow_unauth = _env_flag("LANGFUSE_ALLOW_UNAUTH", default=False)

    kwargs: dict[str, Any] = {}
    if public_key:
        kwargs["public_key"] = public_key
    if secret_key:
        kwargs["secret_key"] = secret_key
    if host:
        kwargs["host"] = host
    if release:
        kwargs["release"] = release
    kwargs["debug"] = debug

    if (not public_key or not secret_key) and not allow_unauth:
        logprint(
            "LANGFUSE_ENABLED=true but keys are missing. Set LANGFUSE_ALLOW_UNAUTH=true for local unauth mode.",
            level="WARNING",
        )
        return ()

    # Newer SDKs require an initialized Langfuse client before callback lookup by public key.
    # This keeps callback tracing and decorated internals aligned to the same project client.
    if public_key and secret_key:
        _initialize_langfuse_client(
            public_key=public_key,
            secret_key=secret_key,
            host=host,
            release=release,
            debug=debug,
        )

    try:
        # Langfuse SDK signatures differ by version.
        # Keep only supported kwargs to avoid constructor errors.
        try:
            params = inspect.signature(callback_cls.__init__).parameters
            has_var_kwargs = any(
                p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()
            )
            if has_var_kwargs:
                safe_kwargs = kwargs
            else:
                supported = {k for k in params.keys() if k != "self"}
                safe_kwargs = {k: v for k, v in kwargs.items() if k in supported}
        except Exception:
            safe_kwargs = kwargs

        handler = callback_cls(**safe_kwargs)
        return (handler,)
    except Exception as exc:
        logprint(
            "Failed to initialize Langfuse callback handler.",
            level="WARNING",
            exception=exc,
        )
        return ()


__all__ = ["get_langfuse_callbacks"]

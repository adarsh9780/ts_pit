from __future__ import annotations

import builtins
import os
import sys
import threading
from pathlib import Path
from typing import Any

from loguru import logger as _logger

from .config import get_config


_configured = False
_init_lock = threading.Lock()
LOG_DIR = Path("~/.ts_pit/logs").expanduser()


def _resolve_log_dir(raw_dir: str) -> Path:
    path = Path(raw_dir).expanduser()
    if path.is_absolute():
        return path
    project_root = Path(__file__).resolve().parents[1]
    return (project_root / path).resolve()


def _get_env_level(default: str = "INFO") -> str:
    return os.getenv("LOG_LEVEL", default).upper()


def _get_logging_settings() -> dict[str, Any]:
    cfg = get_config().get_logging_config()
    level = _get_env_level(str(cfg.get("level", "INFO")))
    return {
        "dir": _resolve_log_dir(str(cfg.get("dir", "~/.ts_pit/logs"))),
        "file_pattern": str(cfg.get("file_pattern", "app_{time:YYYYMMDD}.jsonl")),
        "level": level,
        "rotation": str(cfg.get("rotation", "10 MB")),
        "retention": str(cfg.get("retention", "14 days")),
        "compression": str(cfg.get("compression", "zip")),
    }


def init_logger() -> None:
    """Configure console + JSON file log sinks. Idempotent."""
    global _configured, LOG_DIR
    if _configured:
        return

    with _init_lock:
        if _configured:
            return

        settings = _get_logging_settings()
        LOG_DIR = settings["dir"]
        LOG_DIR.mkdir(parents=True, exist_ok=True)

        _logger.remove()

        _logger.add(
            sys.stdout,
            colorize=True,
            backtrace=False,
            diagnose=False,
            enqueue=True,
            level=settings["level"],
            filter=lambda record: record["extra"].get("to_console", True),
            format=(
                "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
                "<level>{level: <8}</level> | "
                "{extra[request_id]:^12} | "
                "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
                "<level>{message}</level>"
            ),
        )

        _logger.add(
            LOG_DIR / settings["file_pattern"],
            rotation=settings["rotation"],
            retention=settings["retention"],
            compression=settings["compression"],
            level=settings["level"],
            enqueue=True,
            filter=lambda record: record["extra"].get("to_file", True),
            serialize=True,
        )

        _configured = True


def logprint(
    *args: Any,
    level: str = "INFO",
    to_console: bool | None = None,
    to_file: bool | None = None,
    caller_depth: int = 1,
    **extra: Any,
) -> None:
    """Drop-in replacement for print() with structured logging."""
    init_logger()

    message = " ".join(str(a) for a in args)
    bind_kwargs = dict(**extra)
    if "request_id" not in bind_kwargs:
        bind_kwargs["request_id"] = "-"
    if to_console is not None:
        bind_kwargs["to_console"] = bool(to_console)
    if to_file is not None:
        bind_kwargs["to_file"] = bool(to_file)
    bind_kwargs.pop("caller_depth", None)

    _logger.opt(depth=max(1, int(caller_depth))).bind(**bind_kwargs).log(level.upper(), message)


def patch_print() -> None:
    """Monkey-patch builtins.print to route stdout calls through logprint()."""
    original_print = builtins.print

    def _wrapped_print(*args: Any, **kwargs: Any) -> None:
        original_kwargs = dict(kwargs)

        file_obj = original_kwargs.get("file", None)
        if file_obj is not None and file_obj is not sys.stdout:
            original_print(*args, **original_kwargs)
            return

        lvl = kwargs.pop("level", "INFO")
        to_console = kwargs.pop("to_console", None)
        to_file = kwargs.pop("to_file", None)

        sep = kwargs.pop("sep", " ")
        end = kwargs.pop("end", "\n")
        kwargs.pop("file", None)
        kwargs.pop("flush", None)

        message = sep.join(str(a) for a in args)
        if end and end != "\n":
            message += end.rstrip("\n")

        logprint(
            message,
            level=lvl,
            to_console=to_console,
            to_file=to_file,
            caller_depth=2,
            **kwargs,
        )

    builtins.print = _wrapped_print  # type: ignore


__all__ = ["init_logger", "logprint", "patch_print", "LOG_DIR"]

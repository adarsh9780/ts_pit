from __future__ import annotations

import contextlib
import io
import json
import sys
from typing import Any

try:
    import resource  # POSIX only
except Exception:  # pragma: no cover - platform specific
    resource = None

from RestrictedPython import PrintCollector, compile_restricted
from RestrictedPython.Guards import (
    full_write_guard,
    guarded_iter_unpack_sequence,
    guarded_unpack_sequence,
    safer_getattr,
)


def _inject_input_keys(exec_globals: dict[str, Any], input_data: Any) -> None:
    """
    Convenience: expose input_data keys as top-level variables when safe.

    Example: input_data={"x": 9} enables user code `result = x ** 0.5`.
    """
    if not isinstance(input_data, dict):
        return
    reserved = {
        "__builtins__",
        "input_data",
        "result",
        "_print_",
        "_getattr_",
        "_write_",
        "_getiter_",
        "_getitem_",
        "_iter_unpack_sequence_",
        "_unpack_sequence_",
    }
    for key, value in input_data.items():
        key_str = str(key)
        if not key_str.isidentifier():
            continue
        if key_str in reserved or key_str.startswith("_"):
            continue
        if key_str not in exec_globals:
            exec_globals[key_str] = value


def _set_limits(memory_limit_mb: int, cpu_time_seconds: int) -> list[str]:
    errors: list[str] = []
    if resource is None:
        errors.append("RLIMIT limits unavailable on this platform")
        return errors

    mem_bytes = int(memory_limit_mb) * 1024 * 1024

    try:
        _, current_hard = resource.getrlimit(resource.RLIMIT_AS)
        if current_hard in (-1, resource.RLIM_INFINITY):
            target_hard = mem_bytes
        else:
            target_hard = min(mem_bytes, current_hard)
        target_soft = min(mem_bytes, target_hard)
        resource.setrlimit(resource.RLIMIT_AS, (target_soft, target_hard))
    except (ValueError, OSError) as exc:
        errors.append(f"RLIMIT_AS not applied: {exc}")

    try:
        _, cpu_hard = resource.getrlimit(resource.RLIMIT_CPU)
        requested_cpu = int(cpu_time_seconds)
        if cpu_hard in (-1, resource.RLIM_INFINITY):
            target_cpu_hard = requested_cpu
        else:
            target_cpu_hard = min(requested_cpu, cpu_hard)
        target_cpu_soft = min(requested_cpu, target_cpu_hard)
        resource.setrlimit(resource.RLIMIT_CPU, (target_cpu_soft, target_cpu_hard))
    except (ValueError, OSError) as exc:
        errors.append(f"RLIMIT_CPU not applied: {exc}")

    return errors


def _safe_import_factory(allowed_imports: set[str]):
    def _safe_import(name, globals=None, locals=None, fromlist=(), level=0):
        root = name.split(".")[0]
        if root not in allowed_imports:
            raise ImportError(f"Import '{name}' is not allowed")
        return __import__(name, globals, locals, fromlist, level)

    return _safe_import


def _build_safe_builtins(allowed_builtins: set[str], safe_import) -> dict[str, Any]:
    builtins_obj = __builtins__
    if not isinstance(builtins_obj, dict):
        builtins_obj = builtins_obj.__dict__

    safe = {}
    for name in allowed_builtins:
        if name in builtins_obj:
            safe[name] = builtins_obj[name]

    safe["__import__"] = safe_import
    return safe


def main() -> int:
    req = json.loads(sys.stdin.read() or "{}")
    code: str = req.get("code", "")
    input_data = req.get("input_data")
    policy = req.get("policy", {})

    timeout_seconds = int(policy.get("timeout_seconds", 5))
    memory_limit_mb = int(policy.get("memory_limit_mb", 256))
    cpu_time_seconds = int(policy.get("cpu_time_seconds", timeout_seconds))
    max_output_kb = int(policy.get("max_output_kb", 128))
    allowed_imports = set(policy.get("allowed_imports", []))
    allowed_builtins = set(policy.get("allowed_builtins", []))
    extra_globals = policy.get("extra_globals", {}) or {}

    try:
        limit_warnings = _set_limits(
            memory_limit_mb=memory_limit_mb, cpu_time_seconds=cpu_time_seconds
        )

        safe_import = _safe_import_factory(allowed_imports)
        safe_builtins = _build_safe_builtins(allowed_builtins, safe_import)

        # RestrictedPython compilation
        byte_code = compile_restricted(code, "<user_code>", "exec")

        exec_globals: dict[str, Any] = {
            "__builtins__": safe_builtins,
            "input_data": input_data,
            "result": None,
            "_print_": PrintCollector,
            "_getattr_": safer_getattr,
            "_write_": full_write_guard,
            "_getiter_": iter,
            "_getitem_": lambda obj, key: obj[key],
            "_iter_unpack_sequence_": guarded_iter_unpack_sequence,
            "_unpack_sequence_": guarded_unpack_sequence,
        }
        exec_globals.update(extra_globals)
        _inject_input_keys(exec_globals, input_data)

        stdout_buffer = io.StringIO()
        stderr_buffer = io.StringIO()
        with contextlib.redirect_stdout(stdout_buffer), contextlib.redirect_stderr(stderr_buffer):
            exec(byte_code, exec_globals, exec_globals)

        max_output_bytes = max_output_kb * 1024
        printed_text = str(exec_globals.get("printed", ""))
        stdout_text = (stdout_buffer.getvalue() + printed_text)[:max_output_bytes]
        stderr_text = stderr_buffer.getvalue()[:max_output_bytes]
        # Don't surface platform capability notes (like missing RLIMIT on Windows)
        # as stderr; they confuse downstream LLM/tool consumers into treating
        # successful runs as failures.

        resp = {
            "ok": True,
            "result": exec_globals.get("result"),
            "stdout": stdout_text,
            "stderr": stderr_text,
            "timed_out": False,
            "resource_exceeded": False,
            "error": None,
        }
        sys.stdout.write(json.dumps(resp, default=str))
        return 0
    except MemoryError:
        sys.stdout.write(
            json.dumps(
                {
                    "ok": False,
                    "result": None,
                    "stdout": "",
                    "stderr": "",
                    "timed_out": False,
                    "resource_exceeded": True,
                    "error": "Memory limit exceeded",
                }
            )
        )
        return 2
    except Exception as e:
        sys.stdout.write(
            json.dumps(
                {
                    "ok": False,
                    "result": None,
                    "stdout": "",
                    "stderr": "",
                    "timed_out": False,
                    "resource_exceeded": False,
                    "error": str(e),
                }
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

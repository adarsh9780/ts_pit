from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class RunnerPolicy:
    """Execution policy for untrusted Python code."""

    timeout_seconds: int = 5
    memory_limit_mb: int = 256
    cpu_time_seconds: int = 5
    max_output_kb: int = 128
    allowed_imports: list[str] = field(default_factory=lambda: ["math", "statistics", "json"])
    allowed_builtins: list[str] = field(
        default_factory=lambda: ["abs", "all", "any", "bool", "dict", "enumerate", "float", "int", "len", "list", "max", "min", "print", "range", "round", "set", "sorted", "str", "sum", "tuple", "zip"]
    )
    extra_globals: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RunnerResult:
    ok: bool
    result: Any = None
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    resource_exceeded: bool = False
    error: str | None = None
    exit_code: int = 0

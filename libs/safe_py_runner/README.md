# safe-py-runner

A small reusable package to execute user-provided Python code with guardrails:

- isolated subprocess execution
- wall-clock timeout
- memory / CPU limits (POSIX)
- import allowlist
- builtin/global controls
- JSON input/output contract for external data

## Quick Example

```python
from safe_py_runner import RunnerPolicy, run_code

policy = RunnerPolicy(
    timeout_seconds=2,
    memory_limit_mb=128,
    cpu_time_seconds=2,
    allowed_imports=["math", "statistics"],
    allowed_builtins=["len", "range", "sum", "min", "max", "print"],
)

result = run_code(
    code="import math\nresult = math.sqrt(input_data['x'])",
    input_data={"x": 81},
    policy=policy,
)

print(result.ok, result.result)
```

## Security Notes

This package is a guardrail layer, not a complete OS sandbox by itself.
For production use with hostile inputs, pair this with container/namespace isolation.

## Project Integration (ts_pit)

Use the project setup script to provision the isolated runner venv:

```bash
uv run python scripts/setup_safe_py_runner_env.py
```

It reads `agent_v2.python_exec` from `config.yaml` and installs packages listed in
`agent_v2.python_exec.packages` into the runner venv.

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
    blocked_imports=["os", "subprocess", "socket"],
    blocked_builtins=["eval", "exec", "open", "__import__"],
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

Create and manage the runner environment externally (venv/uv/poetry/conda), then
point `agent_v2.safe_py_runner.venv_path` in `config.yaml` to the runner Python executable.

Use this diagnostic command to validate runtime path and required imports:

```bash
uv run python scripts/check_safe_py_runner_env.py
```

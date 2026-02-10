from safe_py_runner import RunnerPolicy, run_code


def test_run_code_success_math_import():
    policy = RunnerPolicy(
        timeout_seconds=2,
        memory_limit_mb=128,
        cpu_time_seconds=2,
        allowed_imports=["math"],
        allowed_builtins=["print", "int", "float", "str"],
    )

    result = run_code(
        code="import math\nresult = math.sqrt(int(input_data['x']))\nprint('done')",
        input_data={"x": 81},
        policy=policy,
    )

    assert result.ok is True
    assert result.result == 9.0
    assert "done" in result.stdout


def test_import_blocked():
    policy = RunnerPolicy(
        timeout_seconds=2,
        memory_limit_mb=128,
        cpu_time_seconds=2,
        allowed_imports=["math"],
        allowed_builtins=["print"],
    )

    result = run_code(
        code="import os\nresult = 1",
        policy=policy,
    )

    assert result.ok is False
    assert "not allowed" in (result.error or "")

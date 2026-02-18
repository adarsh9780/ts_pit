from __future__ import annotations

from _script_runner import run_operation

DEV_CHECK_OPERATIONS = {
    "check-safe-py-runner-env": "check_safe_py_runner_env.py",
    "test-logging-config": "test_logging_config.py",
    "test-p3-mapping": "test_p3_mapping.py",
    "test-tools": "test_tools.py",
    "verify-scripts-imports": "verify_scripts_imports.py",
}


def main() -> int:
    return run_operation(
        DEV_CHECK_OPERATIONS,
        "Developer checks and script-level regression helpers.",
    )


if __name__ == "__main__":
    raise SystemExit(main())

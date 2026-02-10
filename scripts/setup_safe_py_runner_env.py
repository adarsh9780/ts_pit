from __future__ import annotations

from backend.agent_v2.python_env import ensure_python_runtime
from backend.config import get_config


def main() -> int:
    cfg = get_config().get_agent_v2_python_exec_config()
    # Force creation in this setup script even if config has auto_create_venv=false.
    cfg = dict(cfg)
    cfg["auto_create_venv"] = True
    py_exec = ensure_python_runtime(cfg)
    print(f"safe_py_runner runtime ready: {py_exec}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

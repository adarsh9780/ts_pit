from __future__ import annotations

import json
import sys
from pathlib import Path

# Ensure project root is importable when script is executed directly.
try:
    from ts_pit.agent_v2.python_env import get_runtime_diagnostics
    from ts_pit.config import get_config
except ImportError:
    PROJECT_ROOT = Path(__file__).resolve().parent.parent / "src"
    sys.path.insert(0, str(PROJECT_ROOT))
    from ts_pit.agent_v2.python_env import get_runtime_diagnostics
    from ts_pit.config import get_config


def main() -> int:
    cfg = get_config().get_agent_safe_py_runner_config()
    diagnostics = get_runtime_diagnostics(cfg)
    print(json.dumps(diagnostics, indent=2))

    runtime_ok = bool(diagnostics.get("runtime_exists")) and diagnostics.get(
        "required_imports_ok", True
    )
    return 0 if runtime_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

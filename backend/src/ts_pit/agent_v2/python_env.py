from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any


def _expand_path(path_value: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(path_value))).resolve()


def _venv_python_path(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def resolve_python_executable(exec_cfg: dict[str, Any]) -> Path:
    """
    Resolve runner python executable from config.

    `venv_path` is expected to point directly to the python executable.
    For convenience, if a directory is provided we map it to venv python path.
    """
    venv_path = str(exec_cfg.get("venv_path", "")).strip()
    if not venv_path:
        raise RuntimeError(
            "agent_v2.safe_py_runner.venv_path is required and must point to "
            "the runner python executable."
        )

    candidate = _expand_path(venv_path)
    if candidate.is_dir():
        candidate = _venv_python_path(candidate)
    return candidate


def _validate_required_imports(python_executable: Path, required_imports: list[str]) -> None:
    imports = [str(name).strip() for name in required_imports if str(name).strip()]
    if not imports:
        return
    script_lines = [
        "missing=[]",
        "import importlib",
        f"targets={imports!r}",
        "for name in targets:",
        "    try:",
        "        importlib.import_module(name)",
        "    except Exception:",
        "        missing.append(name)",
        "print(','.join(missing))",
    ]
    try:
        proc = subprocess.run(
            [str(python_executable), "-c", "\n".join(script_lines)],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as e:
        hint = ""
        if os.name == "nt" and getattr(e, "winerror", None) == 1260:
            hint = (
                " Group policy blocked launching this interpreter. "
                "Use a permitted path under your allowed VDI folder."
            )
        raise RuntimeError(
            f"Failed import validation in runtime {python_executable}: {e}.{hint}"
        ) from e
    missing_raw = (proc.stdout or "").strip()
    if proc.returncode != 0:
        stderr_text = (proc.stderr or "").strip()
        raise RuntimeError(
            f"Failed import validation in runtime {python_executable}: "
            f"{stderr_text or proc.returncode}"
        )
    if missing_raw:
        raise RuntimeError(
            f"Runner runtime missing required imports: {missing_raw}. "
            f"Install them in {python_executable}."
        )


def get_runtime_diagnostics(exec_cfg: dict[str, Any]) -> dict[str, Any]:
    """Return runtime diagnostics for troubleshooting setup issues."""
    diagnostics: dict[str, Any] = {}
    diagnostics["venv_path_config"] = str(exec_cfg.get("venv_path", ""))
    diagnostics["required_imports"] = list(exec_cfg.get("required_imports", []))

    try:
        runtime = resolve_python_executable(exec_cfg)
        diagnostics["runtime_interpreter"] = str(runtime)
        diagnostics["runtime_exists"] = runtime.exists()
        if runtime.exists():
            try:
                _validate_required_imports(runtime, list(exec_cfg.get("required_imports", [])))
                diagnostics["required_imports_ok"] = True
            except Exception as e:
                diagnostics["required_imports_ok"] = False
                diagnostics["required_imports_error"] = str(e)
    except Exception as e:
        diagnostics["runtime_resolution_error"] = str(e)

    return diagnostics


def ensure_python_runtime(exec_cfg: dict[str, Any]) -> Path:
    """Validate configured runtime path and required imports."""
    py_exec = resolve_python_executable(exec_cfg)
    if not py_exec.exists() or not py_exec.is_file():
        raise RuntimeError(
            "agent_v2.safe_py_runner runtime not found.\n"
            f"Configured executable: {py_exec}\n"
            "Create/setup your runner environment externally and set "
            "`agent_v2.safe_py_runner.venv_path` to its python executable path.\n"
            "Then restart backend."
        )
    _validate_required_imports(py_exec, list(exec_cfg.get("required_imports", [])))
    return py_exec

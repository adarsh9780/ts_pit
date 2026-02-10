from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any


def _expand_path(path_value: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(path_value))).resolve()


def resolve_python_executable(exec_cfg: dict[str, Any]) -> Path:
    explicit = str(exec_cfg.get("python_executable", "")).strip()
    if explicit:
        return _expand_path(explicit)

    venv_path = str(exec_cfg.get("venv_path", "")).strip()
    if not venv_path:
        raise RuntimeError(
            "agent_v2.python_exec requires either python_executable or venv_path in config.yaml"
        )
    venv_dir = _expand_path(venv_path)
    return venv_dir / "bin" / "python"


def _create_venv(venv_dir: Path) -> None:
    venv_dir.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [sys.executable, "-m", "venv", str(venv_dir)],
        check=True,
        capture_output=True,
        text=True,
    )


def _install_packages(python_executable: Path, packages: list[str]) -> None:
    if not packages:
        return
    subprocess.run(
        [str(python_executable), "-m", "pip", "install", *packages],
        check=True,
        capture_output=True,
        text=True,
    )


def ensure_python_runtime(exec_cfg: dict[str, Any]) -> Path:
    """
    Validate python runtime for execute_python.

    Behavior:
    - If python_executable exists -> use it.
    - Else if auto_create_venv=true and venv_path is set -> create venv (+ optional packages).
    - Else fail fast with clear setup instructions.
    """
    py_exec = resolve_python_executable(exec_cfg)
    if py_exec.exists():
        return py_exec

    auto_create = bool(exec_cfg.get("auto_create_venv", False))
    venv_path_raw = str(exec_cfg.get("venv_path", "")).strip()
    if auto_create and venv_path_raw:
        venv_dir = _expand_path(venv_path_raw)
        _create_venv(venv_dir)
        py_exec = venv_dir / "bin" / "python"
        packages = [str(p) for p in (exec_cfg.get("packages") or []) if str(p).strip()]
        _install_packages(py_exec, packages)
        return py_exec

    raise RuntimeError(
        "agent_v2 python runtime not found.\n"
        f"Expected interpreter: {py_exec}\n"
        "Set agent_v2.python_exec.python_executable OR agent_v2.python_exec.venv_path.\n"
        "Recommended setup:\n"
        f"  python3 -m venv {py_exec.parent.parent}\n"
        f"  {py_exec} -m pip install -U pip RestrictedPython\n"
        "Then set agent_v2.python_exec.enabled=true and restart backend."
    )


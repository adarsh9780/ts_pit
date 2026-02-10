from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


def _expand_path(path_value: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(path_value))).resolve()


def _venv_python_path(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _resolve_executable_path(value: str) -> Path | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    expanded = os.path.expandvars(os.path.expanduser(raw))
    candidate = Path(expanded)
    if candidate.is_absolute() and candidate.exists():
        return candidate.resolve()
    found = shutil.which(expanded)
    if found:
        return Path(found).resolve()
    return None


def _canonicalize_interpreter(path_value: Path) -> Path:
    try:
        proc = subprocess.run(
            [str(path_value), "-c", "import sys;print(sys.executable)"],
            check=True,
            capture_output=True,
            text=True,
        )
        out = (proc.stdout or "").strip()
        if out:
            return Path(out).resolve()
    except Exception:
        pass
    return path_value.resolve()


def _discover_base_interpreter(exec_cfg: dict[str, Any]) -> Path:
    explicit_base = _resolve_executable_path(str(exec_cfg.get("base_python_executable", "")))
    if explicit_base:
        return _canonicalize_interpreter(explicit_base)

    explicit_runtime = _resolve_executable_path(str(exec_cfg.get("python_executable", "")))
    if explicit_runtime:
        return _canonicalize_interpreter(explicit_runtime)

    candidates = exec_cfg.get("interpreter_candidates", ["python3", "python", "py"])
    for name in candidates:
        found = _resolve_executable_path(str(name))
        if found:
            return _canonicalize_interpreter(found)

    return _canonicalize_interpreter(Path(sys.executable))


def resolve_python_executable(exec_cfg: dict[str, Any]) -> Path:
    explicit = str(exec_cfg.get("python_executable", "")).strip()
    if explicit:
        resolved = _resolve_executable_path(explicit)
        if resolved is None:
            raise RuntimeError(f"Configured python_executable not found: {explicit}")
        return _canonicalize_interpreter(resolved)

    venv_path = str(exec_cfg.get("venv_path", "")).strip()
    if not venv_path:
        raise RuntimeError(
            "agent_v2.python_exec requires either python_executable or venv_path in config.yaml"
        )
    venv_dir = _expand_path(venv_path)
    return _venv_python_path(venv_dir)


def _create_venv(venv_dir: Path, base_interpreter: Path, manager: str) -> None:
    venv_dir.parent.mkdir(parents=True, exist_ok=True)
    try:
        manager_value = str(manager or "python_venv").strip().lower()
        if manager_value == "uv_venv":
            subprocess.run(
                ["uv", "venv", str(venv_dir), "--python", str(base_interpreter)],
                check=True,
                capture_output=True,
                text=True,
            )
        else:
            subprocess.run(
                [str(base_interpreter), "-m", "venv", str(venv_dir)],
                check=True,
                capture_output=True,
                text=True,
            )
    except subprocess.CalledProcessError as e:
        stderr_text = (e.stderr or "").strip()
        stdout_text = (e.stdout or "").strip()
        details = stderr_text or stdout_text or str(e)
        raise RuntimeError(
            f"Failed to create venv at {venv_dir} using manager='{manager}': {details}"
        ) from e


def _install_packages(python_executable: Path, packages: list[str]) -> None:
    if not packages:
        return
    try:
        subprocess.run(
            [str(python_executable), "-m", "pip", "install", *packages],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        stderr_text = (e.stderr or "").strip()
        stdout_text = (e.stdout or "").strip()
        details = stderr_text or stdout_text or str(e)
        raise RuntimeError(
            f"Failed to install packages into {python_executable}: {details}"
        ) from e


def _build_install_package_list(exec_cfg: dict[str, Any]) -> list[str]:
    # Runner worker depends on RestrictedPython at minimum.
    base_packages = ["RestrictedPython"]
    configured = [str(p).strip() for p in (exec_cfg.get("packages") or []) if str(p).strip()]
    merged = base_packages + configured
    # preserve order, drop duplicates
    deduped: list[str] = []
    seen: set[str] = set()
    for pkg in merged:
        key = pkg.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(pkg)
    return deduped


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
    proc = subprocess.run(
        [str(python_executable), "-c", "\n".join(script_lines)],
        check=False,
        capture_output=True,
        text=True,
    )
    missing_raw = (proc.stdout or "").strip()
    if proc.returncode != 0:
        stderr_text = (proc.stderr or "").strip()
        raise RuntimeError(
            f"Failed import validation in runtime {python_executable}: {stderr_text or proc.returncode}"
        )
    if missing_raw:
        raise RuntimeError(
            f"Runner runtime missing required imports: {missing_raw}. "
            f"Install them in {python_executable}."
        )


def get_runtime_diagnostics(exec_cfg: dict[str, Any]) -> dict[str, Any]:
    """Return runtime diagnostics for troubleshooting setup issues."""
    diagnostics: dict[str, Any] = {}
    diagnostics["venv_manager"] = str(exec_cfg.get("venv_manager", "python_venv"))
    diagnostics["venv_path"] = str(exec_cfg.get("venv_path", ""))
    diagnostics["python_executable_config"] = str(exec_cfg.get("python_executable", ""))
    diagnostics["base_python_executable_config"] = str(exec_cfg.get("base_python_executable", ""))
    diagnostics["interpreter_candidates"] = list(exec_cfg.get("interpreter_candidates", []))
    diagnostics["auto_create_venv"] = bool(exec_cfg.get("auto_create_venv", False))
    diagnostics["required_imports"] = list(exec_cfg.get("required_imports", []))

    try:
        base = _discover_base_interpreter(exec_cfg)
        diagnostics["base_interpreter"] = str(base)
    except Exception as e:
        diagnostics["base_interpreter_error"] = str(e)

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
    """
    Validate python runtime for execute_python.

    Behavior:
    - If python_executable exists -> use it.
    - Else if auto_create_venv=true and venv_path is set -> create venv (+ optional packages).
    - Else fail fast with clear setup instructions.
    """
    py_exec = resolve_python_executable(exec_cfg)
    if py_exec.exists():
        try:
            _validate_required_imports(py_exec, list(exec_cfg.get("required_imports", [])))
        except RuntimeError:
            if not bool(exec_cfg.get("auto_create_venv", False)):
                raise
            _install_packages(py_exec, _build_install_package_list(exec_cfg))
            _validate_required_imports(py_exec, list(exec_cfg.get("required_imports", [])))
        return py_exec

    auto_create = bool(exec_cfg.get("auto_create_venv", False))
    venv_path_raw = str(exec_cfg.get("venv_path", "")).strip()
    if auto_create and venv_path_raw:
        venv_dir = _expand_path(venv_path_raw)
        manager = str(exec_cfg.get("venv_manager", "python_venv"))
        base_interpreter = _discover_base_interpreter(exec_cfg)
        _create_venv(venv_dir, base_interpreter=base_interpreter, manager=manager)
        py_exec = _venv_python_path(venv_dir)
        _install_packages(py_exec, _build_install_package_list(exec_cfg))
        _validate_required_imports(py_exec, list(exec_cfg.get("required_imports", [])))
        return py_exec

    base_hint = _discover_base_interpreter(exec_cfg)
    raise RuntimeError(
        "agent_v2 python runtime not found.\n"
        f"Expected interpreter: {py_exec}\n"
        "Set agent_v2.python_exec.python_executable OR agent_v2.python_exec.venv_path.\n"
        "Recommended setup:\n"
        f"  {base_hint} -m venv {py_exec.parent.parent}\n"
        f"  {py_exec} -m pip install -U pip RestrictedPython\n"
        "Then set agent_v2.python_exec.enabled=true and restart backend."
    )

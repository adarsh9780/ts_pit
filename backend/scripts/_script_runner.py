from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def run_legacy_script(script_name: str, script_args: list[str]) -> int:
    scripts_dir = Path(__file__).resolve().parent
    script_path = scripts_dir / script_name

    if not script_path.exists():
        print(f"Unknown script target: {script_name}", file=sys.stderr)
        return 2

    cmd = [sys.executable, str(script_path), *script_args]
    return subprocess.run(cmd, check=False).returncode


def run_operation(
    mapping: dict[str, str], description: str, argv: list[str] | None = None
) -> int:
    args = list(sys.argv[1:] if argv is None else argv)

    parser = argparse.ArgumentParser(
        description=description,
        usage="%(prog)s <operation> [args...]",
    )
    parser.add_argument("operation", nargs="?", help="Operation to execute.")

    if not args or args[0] in {"-h", "--help"}:
        parser.print_help()
        print("\nAvailable operations: " + ", ".join(sorted(mapping.keys())))
        return 0

    operation = args[0]
    passthrough = args[1:]

    if operation not in mapping:
        parser.print_usage()
        print(
            f"{parser.prog}: error: unknown operation '{operation}'. "
            f"Valid operations: {', '.join(sorted(mapping.keys()))}",
            file=sys.stderr,
        )
        return 2

    return run_legacy_script(mapping[operation], passthrough)

import subprocess
import sys
from pathlib import Path

# Get all python scripts in backend/scripts
scripts_dir = Path(__file__).parent
scripts = list(scripts_dir.glob("*.py"))

failures = []
passed = []

print(f"Verifying imports for {len(scripts)} scripts...")

for script in scripts:
    if script.name == "verify_scripts_imports.py":
        continue

    print(f"Testing {script.name}...", end=" ", flush=True)

    # Try to import the script by running it with python -c "import ..."
    # We run from backend root
    cmd = [sys.executable, "-c", f"import scripts.{script.stem}"]

    # We need to run this from backend directory
    # backend/scripts/verify_scripts_imports.py -> run from backend/
    cwd = scripts_dir.parent

    # We also need to ensure ts_pit is in path.
    # If installed via uv/pip it should be.
    # If not, we might need PYTHONPATH=src
    env = None  # os.environ.copy()
    # env["PYTHONPATH"] = str(cwd / "src") # Uncomment to force src path if package not installed

    res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)

    if res.returncode == 0:
        print("✅ OK")
        passed.append(script.name)
    else:
        # Some scripts might have side effects on import or argparse reqs
        # Let's try running with --help which usually is safe
        cmd_help = [sys.executable, str(script), "--help"]
        res_help = subprocess.run(cmd_help, cwd=cwd, capture_output=True, text=True)
        if res_help.returncode == 0:
            print("✅ OK (via --help)")
            passed.append(script.name)
        else:
            print("❌ FAILED")
            print(f"  Import Error: {res.stderr.strip()}")
            print(f"  Help Error: {res_help.stderr.strip()}")
            failures.append(script.name)

print("\nSummary:")
print(f"Passed: {len(passed)}")
print(f"Failed: {len(failures)}")

if failures:
    sys.exit(1)

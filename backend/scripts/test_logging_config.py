import sys
import os
from pathlib import Path

try:
    from ts_pit.logger import logprint
    from ts_pit.config import get_config
except ImportError:
    PROJECT_ROOT = Path(__file__).resolve().parent.parent / "src"
    sys.path.insert(0, str(PROJECT_ROOT))
    from ts_pit.logger import logprint
    from ts_pit.config import get_config


def test_logging():
    config = get_config()
    logging_config = config.get_logging_config()

    print(f"Loaded Logging Config: {logging_config}")

    # Test INFO log - should NOT appear if level is ERROR
    print("\n--- Testing INFO Log (Should generally NOT appear if level=ERROR) ---")
    logprint("This is an INFO message.", level="INFO")

    # Test ERROR log - SHOULD appear
    print("\n--- Testing ERROR Log (Should ALWAYS appear) ---")
    try:
        x = 1 / 0
    except Exception as e:
        logprint("This is an ERROR message with exception.", level="ERROR", exception=e)


if __name__ == "__main__":
    test_logging()

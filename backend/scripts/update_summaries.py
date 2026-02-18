import sqlite3
import random

import sys
from pathlib import Path

try:
    from ts_pit.config import get_config
except ImportError:
    PROJECT_ROOT = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(PROJECT_ROOT / "src"))
    from ts_pit.config import get_config

config = get_config()
DB_PATH = config.get_database_path()

LOREM_IPSUM = """
Lorem ipsum dolor sit amet, consectetur adipiscing elit. Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat. Duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla pariatur. Excepteur sint occaecat cupidatat non proident, sunt in culpa qui officia deserunt mollit anim id est laborum.
Sed ut perspiciatis unde omnis iste natus error sit voluptatem accusantium doloremque laudantium, totam rem aperiam, eaque ipsa quae ab illo inventore veritatis et quasi architecto beatae vitae dicta sunt explicabo. Nemo enim ipsam voluptatem quia voluptas sit aspernatur aut odit aut fugit.
"""


def update_summaries():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Get all article IDs
    cursor.execute("SELECT art_id FROM articles")
    articles = cursor.fetchall()

    print(f"Updating {len(articles)} articles...")

    for (art_id,) in articles:
        # Generate a random length summary between 200 and 400 chars
        start_idx = random.randint(0, 50)
        length = random.randint(200, 400)
        summary = LOREM_IPSUM[start_idx : start_idx + length].strip().replace("\n", " ")

        cursor.execute(
            "UPDATE articles SET art_summary = ? WHERE art_id = ?", (summary, art_id)
        )

    conn.commit()
    print("Update complete.")
    conn.close()


if __name__ == "__main__":
    update_summaries()

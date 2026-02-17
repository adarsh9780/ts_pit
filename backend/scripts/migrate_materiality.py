import sqlite3
import random

DB_PATH = "alerts.db"


def migrate_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Check if column exists
    cursor.execute("PRAGMA table_info(articles)")
    columns = [info[1] for info in cursor.fetchall()]

    if "Materiality" not in columns:
        print("Adding Materiality column...")
        cursor.execute("ALTER TABLE articles ADD COLUMN Materiality TEXT")
    else:
        print("Materiality column already exists.")

    # Populate with dummy data
    print("Populating with dummy data...")
    cursor.execute("SELECT art_id FROM articles")
    rows = cursor.fetchall()

    options = ["HHH", "HHL", "HLL", "LLL"]

    for row in rows:
        art_id = row[0]
        rating = random.choice(options)
        cursor.execute(
            "UPDATE articles SET Materiality = ? WHERE art_id = ?", (rating, art_id)
        )

    conn.commit()
    conn.close()
    print("Migration complete.")


if __name__ == "__main__":
    migrate_db()

import sqlite3
import os

db_path = os.path.join('instance', 'sentiment.db')

if not os.path.exists(db_path):
    print(f"Database not found at {db_path}")
    exit(1)

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

try:
    cursor.execute("ALTER TABLE analysis_history ADD COLUMN language VARCHAR(50)")
    print("Added language column")
except sqlite3.OperationalError as e:
    print(f"language column exists or error: {e}")

try:
    cursor.execute("ALTER TABLE analysis_history ADD COLUMN wordcloud_path VARCHAR(255)")
    print("Added wordcloud_path column")
except sqlite3.OperationalError as e:
    print(f"wordcloud_path column exists or error: {e}")

try:
    cursor.execute("ALTER TABLE analysis_history ADD COLUMN recommended_action TEXT")
    print("Added recommended_action column")
except sqlite3.OperationalError as e:
    print(f"recommended_action column exists or error: {e}")

conn.commit()
conn.close()
print("Migration completed.")

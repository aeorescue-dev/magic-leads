import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "leads.db")

def add_mailing_address_column():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Check if column exists
    cursor.execute("PRAGMA table_info(leads)")
    columns = [row[1] for row in cursor.fetchall()]
    
    if "mailing_address" not in columns:
        print("Adding mailing_address column...")
        cursor.execute("ALTER TABLE leads ADD COLUMN mailing_address TEXT")
        conn.commit()
        print("Column added successfully")
    else:
        print("mailing_address column already exists")
    
    conn.close()

if __name__ == "__main__":
    add_mailing_address_column()
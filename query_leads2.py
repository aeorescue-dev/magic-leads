import sqlite3
from datetime import datetime, timedelta

conn = sqlite3.connect('data/leads.db')
c = conn.cursor()

# Check what date('now') returns in SQLite
c.execute("SELECT date('now') as now, datetime('now') as now_dt")
print("SQLite date('now'):", c.fetchone())

# Check date_reported format for recent entries
c.execute("""
    SELECT date_reported, date(date_reported) as parsed_date, city, source_type 
    FROM leads 
    ORDER BY id DESC 
    LIMIT 20
""")
print("\n=== ÚLTIMOS 20 LEADS (date_reported bruto) ===")
for row in c.fetchall():
    print(f"  {row[0]} -> parsed: {row[1]} | {row[2]} | {row[3]}")

# Count by actual date_reported date (not parsed)
c.execute("""
    SELECT date_reported, COUNT(*) as cnt FROM leads 
    GROUP BY date_reported 
    ORDER BY date_reported DESC 
    LIMIT 15
""")
print("\n=== CONTAGEM POR date_reported (bruto) ===")
for row in c.fetchall():
    print(f"  {row[0]}: {row[1]}")

# Check last scrape run info
c.execute("SELECT * FROM scrape_runs ORDER BY id DESC LIMIT 5")
print("\n=== ÚLTIMOS SCRAPER RUNS ===")
for row in c.fetchall():
    print(f"  {row}")

conn.close()
import sqlite3
from datetime import datetime, timedelta

conn = sqlite3.connect('data/leads.db')
c = conn.cursor()

# Schema
c.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='leads'")
print("=== SCHEMA ===")
print(c.fetchone()[0])
print()

# Total leads inserted today
today = datetime.now().strftime('%Y-%m-%d')
c.execute("""
    SELECT COUNT(*) FROM leads 
    WHERE date(date_reported) = date('now')
""")
today_count = c.fetchone()[0]
print(f"=== LEADS INSERIDOS HOJE ({today}) ===")
print(f"Total: {today_count}")
print()

# Breakdown by city today
c.execute("""
    SELECT city, COUNT(*) as cnt FROM leads 
    WHERE date(date_reported) = date('now')
    GROUP BY city ORDER BY cnt DESC
""")
print("=== POR CIDADE (HOJE) ===")
for row in c.fetchall():
    print(f"  {row[0]}: {row[1]}")
print()

# Breakdown by source_type today
c.execute("""
    SELECT source_type, COUNT(*) as cnt FROM leads 
    WHERE date(date_reported) = date('now')
    GROUP BY source_type ORDER BY cnt DESC
""")
print("=== POR TIPO/FONTE (HOJE) ===")
for row in c.fetchall():
    print(f"  {row[0]}: {row[1]}")
print()

# Last 7 days trend
c.execute("""
    SELECT date(date_reported) as dia, COUNT(*) as cnt FROM leads 
    WHERE date(date_reported) >= date('now', '-7 days')
    GROUP BY dia ORDER BY dia DESC
""")
print("=== ÚLTIMOS 7 DIAS ===")
for row in c.fetchall():
    print(f"  {row[0]}: {row[1]}")
print()

# Total leads in DB
c.execute("SELECT COUNT(*) FROM leads")
total = c.fetchone()[0]
print(f"=== TOTAL NO BANCO ===")
print(f"  {total}")

conn.close()
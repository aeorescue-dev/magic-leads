import sqlite3
conn = sqlite3.connect('data/leads.db')
cur = conn.cursor()
cur.execute("SELECT issue_description, case_title, department, address FROM leads WHERE city IN ('Dallas', 'Dallasopendata') LIMIT 10")
for row in cur.fetchall():
    print(f"Desc: {row[0]}")
    print(f"Title: {row[1]}")
    print(f"Dept: {row[2]}")
    print(f"Address: {row[3]}")
    print()
conn.close()
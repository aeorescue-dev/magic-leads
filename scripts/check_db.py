import sqlite3
conn = sqlite3.connect('data/leads.db')
cur = conn.cursor()
cur.execute('''
    SELECT city, COUNT(*) as total, 
           SUM(CASE WHEN owner_name IS NOT NULL AND owner_name != "" THEN 1 ELSE 0 END) as with_owner
    FROM leads GROUP BY city
''')
for row in cur.fetchall():
    print(f'{row[0]}: total={row[1]}, with_owner={row[2]}')
conn.close()
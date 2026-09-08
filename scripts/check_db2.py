import sqlite3
conn = sqlite3.connect('data/leads.db')
cur = conn.cursor()
cur.execute('''
    SELECT city, 
           SUM(CASE WHEN mailing_address IS NOT NULL AND mailing_address != "" THEN 1 ELSE 0 END) as with_mailing,
           SUM(CASE WHEN owner_phone IS NOT NULL AND owner_phone != "" THEN 1 ELSE 0 END) as with_phone,
           SUM(CASE WHEN owner_email IS NOT NULL AND owner_email != "" THEN 1 ELSE 0 END) as with_email
    FROM leads GROUP BY city
''')
for row in cur.fetchall():
    print(f'{row[0]}: mailing={row[1]}, phone={row[2]}, email={row[3]}')
conn.close()
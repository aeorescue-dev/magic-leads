import sqlite3

conn = sqlite3.connect('data/leads.db')
cur = conn.cursor()

# Check current addresses with Dallasopendata
cur.execute("SELECT id, address, city FROM leads WHERE address LIKE '%Dallasopendata%' LIMIT 5")
for row in cur.fetchall():
    print(f"ID: {row[0]}, City: {row[2]}")
    print(f"  Address: {row[1]}")
    print()

# Clean up addresses - remove Dallasopendata from address field
cur.execute("""
    UPDATE leads 
    SET address = REPLACE(address, ', Dallasopendata, US', ''),
        address = REPLACE(address, ', Dallasopendata', ''),
        address = REPLACE(address, 'Dallasopendata, ', ''),
        address = REPLACE(address, ', Dallasopendata', '')
    WHERE address LIKE '%Dallasopendata%'
""")

conn.commit()
print(f"Rows updated: {cur.rowcount}")

# Verify
cur.execute("SELECT id, address, city FROM leads WHERE address LIKE '%Dallasopendata%' LIMIT 3")
for row in cur.fetchall():
    print(f"ID: {row[0]}, City: {row[2]}")
    print(f"  Address: {row[1]}")

conn.close()
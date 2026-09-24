import sqlite3
conn = sqlite3.connect('C:/Users/Fabio/Documents/Default Project/garimpador-leads/data/leads.db')
c = conn.cursor()
c.execute('SELECT name FROM sqlite_master WHERE type="table"')
tables = c.fetchall()
for t in tables:
    print(t[0])
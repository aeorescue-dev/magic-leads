import os
import sqlite3

# Database is at project root
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'leads.db')

conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

# Check test user
c.execute('SELECT id, email, company_name, plan, subscription_status, plan_until FROM users WHERE email = ?', ('test@magicleads.app',))
print("Test user:", c.fetchall())

# Check demo user
c.execute('SELECT id, email, password_hash, plan, subscription_status, plan_until FROM users WHERE email = ?', ('demo@magicleads.app',))
print("Demo user:", c.fetchall())

# All users
c.execute('SELECT id, email, plan, subscription_status FROM users')
for row in c.fetchall():
    print(row)

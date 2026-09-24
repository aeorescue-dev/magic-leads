#!/usr/bin/env python3
"""
Seed script to create test user in production SQLite database.
Run on Railway after deployment: python -m backend.scripts.seed_test_user
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sqlite3
import os
from services.security import hash_password

# Database path - check environment variables first, then fallback to project root
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # project root
DB_PATH = os.environ.get("LEADS_DB_PATH") or os.path.join(
    os.environ.get("DATA_DIR", os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "data", "leads.db"
)

TEST_EMAIL = "test@magicleads.app"
TEST_PASSWORD = "Test123!"
TEST_COMPANY = "Test Company"

def seed_test_user():
    """Create test user with Pro plan if not exists."""
    print(f"Looking for database at: {DB_PATH}")
    if not os.path.exists(DB_PATH):
        print(f"Database not found at {DB_PATH}")
        return False
    
    conn = sqlite3.connect(DB_PATH)
    try:
        c = conn.cursor()
        
        # Check if test user exists
        c.execute("SELECT id, email, company_name, plan, subscription_status FROM users WHERE email = ?", (TEST_EMAIL,))
        user = c.fetchone()
        
        if user:
            print(f"Test user already exists: {user}")
            # Ensure Pro plan and active subscription
            from services.security import hash_password
            
            pwd_hash = hash_password("Test123!")
            c.execute("""
                UPDATE users 
                SET password_hash = ?, company_name = ?, plan = 'pro', 
                    subscription_status = 'active', plan_until = '2025-12-31', locale = 'pt'
                WHERE email = ?
            """, (hash_password("Test123!"), "Test Company", "test@magicleads.app"))
            
            # Ensure subscription exists
            c.execute("SELECT id FROM users WHERE email = ?", ("test@magicleads.app",))
            user = c.fetchone()
            if user:
                user_id = user[0]
                # Check subscriptions table
                c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='subscriptions'")
                if c.fetchone():
                    c.execute("""
                        INSERT OR REPLACE INTO subscriptions 
                        (user_id, plan, status, can_access, stripe_subscription_id, current_period_end)
                        VALUES (?, 'pro', 'active', 1, 'sub_test_123', '2025-12-31')
                    """, (user[0],))
            
            conn.commit()
            print("Test user updated with Pro plan")
            return True
        else:
            # Create test user
            from services.security import hash_password
            
            pwd_hash = hash_password("Test123!")
            
            c.execute("""
                INSERT INTO users 
                (email, password_hash, company_name, plan, subscription_status, plan_until, locale)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, ("test@magicleads.app", hash_password("Test123!"), "Test Company", 
                  "pro", "active", "2025-12-31", "pt"))
            
            user_id = c.lastrowid
            
            # Create subscription record
            c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='subscriptions'")
            if c.fetchone():
                c.execute("""
                    INSERT INTO subscriptions 
                    (user_id, plan, status, can_access, stripe_subscription_id, current_period_end)
                    VALUES (?, 'pro', 'active', 1, 'sub_test_123', '2025-12-31')
                """, (c.lastrowid,))
            
            conn.commit()
            print("Test user created with Pro plan")
            return True
            
    except Exception as e:
        print(f"Error: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

if __name__ == "__main__":
    print("Seeding test user...")
    success = seed_test_user()
    if success:
        print("Test user seeded successfully!")
        sys.exit(0)
    else:
        print("Failed to seed test user")
        sys.exit(1)
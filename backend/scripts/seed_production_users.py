#!/usr/bin/env python3
"""
Seed script to ensure demo and test users exist in production SQLite database.
Run on Railway after deployment: python seed_production_users.py
"""
import os
import sqlite3
import sys

# Add /app to path for imports
sys.path.insert(0, '/app')

from backend.services.security import hash_password

# Database path - check environment variables first, then fallback
DB_PATH = os.environ.get("LEADS_DB_PATH") or os.path.join(
    os.environ.get("DATA_DIR", "/data"), "leads.db"
)

# User definitions - matches .env DEMO_EMAIL/DEMO_PASSWORD and test credentials
USERS_TO_SEED = [
    {
        "email": "demo@magicleads.app",
        "password": "Demo2026#Magic",  # From .env DEMO_PASSWORD
        "company_name": "Demo User",
        "plan": "pro",
        "subscription_status": "active",
        "plan_until": "2025-12-31",
        "locale": "pt",
    },
    {
        "email": "test@magicleads.app",
        "password": "Test123!",
        "company_name": "Test Company",
        "plan": "pro",
        "subscription_status": "active",
        "plan_until": "2025-12-31",
        "locale": "pt",
    },
]


def seed_users():
    """Create or update users with correct passwords and Pro plans."""
    print(f"Looking for database at: {DB_PATH}")
    if not os.path.exists(DB_PATH):
        print(f"Database not found at {DB_PATH}")
        return False

    conn = sqlite3.connect(DB_PATH)
    try:
        c = conn.cursor()

        # Garante a coluna locale (adicionada por migração do app) antes de usar
        user_cols = {r["name"] for r in c.execute("PRAGMA table_info(users)").fetchall()}
        if user_cols and "locale" not in user_cols:
            c.execute("ALTER TABLE users ADD COLUMN locale TEXT DEFAULT 'pt'")
            conn.commit()

        for user_def in USERS_TO_SEED:
            email = user_def["email"]

            # Check if user exists
            c.execute("SELECT id, email, plan, subscription_status FROM users WHERE email = ?", (email,))
            user = c.fetchone()

            if user:
                print(f"User {email} exists, updating...")
                c.execute("""
                    UPDATE users
                    SET password_hash = ?, company_name = ?, plan = 'pro',
                        subscription_status = 'active', plan_until = '2025-12-31', locale = 'pt'
                    WHERE email = ?
                """, (hash_password(user_def["password"]), user_def["company_name"], email))
                print(f"  Updated {email} with Pro plan")
            else:
                # Create user
                c.execute("""
                    INSERT INTO users
                    (email, password_hash, company_name, plan, subscription_status, plan_until, locale)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (user_def["email"], hash_password(user_def["password"]),
                      user_def["company_name"], "pro", "active", "2025-12-31", "pt"))
                user_id = c.lastrowid
                print(f"Created user {email} with id {user_id}")

        conn.commit()
        print("All users seeded successfully!")
        return True

    except Exception as e:
        print(f"Error: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


if __name__ == "__main__":
    print("Seeding production users...")
    success = seed_users()
    if success:
        print("All production users seeded successfully!")
        sys.exit(0)
    else:
        print("Failed to seed production users")
        sys.exit(1)

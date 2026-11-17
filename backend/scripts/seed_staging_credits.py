"""Seed sintÃ©tico do staging para o Marco 1A.

Nunca correr em produÃ§Ã£o. Requer RAILWAY_ENVIRONMENT_NAME=staging ou
CREDITS_SEED=1. Cria 2 contas de teste e 50 leads sintÃ©ticos com sinal pronto.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

if (
    os.environ.get("RAILWAY_ENVIRONMENT_NAME") != "staging"
    and os.environ.get("CREDITS_SEED") != "1"
):
    print("Refusing to seed outside staging. Set RAILWAY_ENVIRONMENT_NAME=staging or CREDITS_SEED=1.")
    sys.exit(2)

import sqlite3  # noqa: E402

from backend.services import credits  # noqa: E402
from backend.services.db import DB_PATH  # noqa: E402
from backend.services.security import hash_password  # noqa: E402

PASSWORD = os.environ.get("STAGING_TEST_PASSWORD", "dev-demo-only")
TEST_USERS = [
    ("qa-free+staging@magicleads.app", "QA Free Co"),
    ("qa-buyer+staging@magicleads.app", "QA Buyer Co"),
]
CITIES = [
    ("NYC", "NY", "10001"),
    ("Chicago", "IL", "60601"),
    ("Boston", "MA", "02108"),
    ("Dallas", "TX", "75201"),
]
TRADES = [
    "Plumbing", "Electrical", "Heating", "Paint", "Roof", "Structure",
    "Door_Window", "Unsanitary", "Mold", "Debris", "Rodent", "Elevator",
    "Gas", "Lead", "Grass", "Permit_Rejected",
]

credits.init()
conn = sqlite3.connect(DB_PATH, timeout=20)
conn.row_factory = sqlite3.Row
now = datetime.now(timezone.utc)

user_ids: list[int] = []
for email, company in TEST_USERS:
    conn.execute(
        "INSERT INTO users (email, password_hash, company_name, plan, subscription_status, locale, "
        "account_status, email_verified_at) VALUES (?, ?, ?, 'free', 'expired', 'en', 'active', ?) "
        "ON CONFLICT(email) DO UPDATE SET password_hash=excluded.password_hash, "
        "company_name=excluded.company_name, account_status='active', email_verified_at=excluded.email_verified_at",
        (email, hash_password(PASSWORD), company, now.isoformat()),
    )
    user_ids.append(int(conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()["id"]))

# Interesses mínimos para o dashboard não redirecionar para o onboarding no staging.
for uid in user_ids:
    for category in ("Plumbing", "Electrical", "Heating", "Paint"):
        conn.execute(
            "INSERT OR IGNORE INTO user_interests (user_id, category, push_enabled) VALUES (?, ?, 0)",
            (uid, category),
        )

# Reset only the test users' ledger/purchases/reveals so the demo is deterministic.
placeholders = ",".join("?" for _ in user_ids)
conn.execute(f"DELETE FROM lead_exclusivity WHERE user_id IN ({placeholders})", user_ids)
conn.execute(f"DELETE FROM lead_reveals WHERE user_id IN ({placeholders})", user_ids)
conn.execute(f"DELETE FROM credit_ledger WHERE user_id IN ({placeholders})", user_ids)
conn.execute(f"DELETE FROM credit_purchases WHERE user_id IN ({placeholders})", user_ids)
conn.execute(f"UPDATE credit_wallets SET balance_cents=0, reserved_cents=0 WHERE user_id IN ({placeholders})", user_ids)
conn.execute("DELETE FROM leads WHERE source_type='credits_seed'")

first_names = ["Alice", "Bruno", "Carla", "Daniel", "Elena", "Felipe", "Grace", "Hugo", "Iris", "Joel"]
last_names = ["Owner", "Builder", "Homes", "Renovations", "Property", "Contractor", "Realty", "Works", "Group", "Trust"]

for i in range(50):
    city, state, zip_code = CITIES[i % len(CITIES)]
    trade = TRADES[i % len(TRADES)]
    owner = f"{first_names[i % len(first_names)]} {last_names[(i // 2) % len(last_names)]}"
    conn.execute(
        "INSERT INTO leads (external_id, source_type, address, city, state, zip_code, neighborhood, "
        "issue_category, issue_description, case_title, owner_name, mailing_address, date_reported, "
        "created_at, is_qualified, is_junk, case_status, signal_type, signal_status, "
        "signal_ready, phone_ready, owner_source, "
        "owner_kind, parcel_id, lead_status) "
        "VALUES (?, 'credits_seed', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 0, 'open', "
        "'open_request', 'open', 1, 0, "
        "'seed_staging', 'person', ?, 'available')",
        (
            f"credits-seed-{i:03d}",
            f"{100 + i} Seed Street",
            city,
            state,
            zip_code,
            f"Test Zone {(i % 4) + 1}",
            trade,
            f"Synthetic {trade.lower()} opportunity for staging",
            f"{trade} Â· Staging signal {i + 1}",
            owner,
            f"{200 + i} Mail Avenue, {city}, {state} {zip_code}",
            (now - timedelta(days=i % 14)).isoformat(),
            now.isoformat(),
            f"SEED-{city.upper()}-{i:03d}",
        ),
    )

conn.commit()
leads = conn.execute("SELECT COUNT(*) FROM leads WHERE source_type='credits_seed'").fetchone()[0]
print(f"Seeded users={user_ids} leads={leads} db={DB_PATH}")
conn.close()


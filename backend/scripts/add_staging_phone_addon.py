"""Injeta um add-on de telefones (24h) para QA visual no staging.

Não é endpoint público. Requer staging (ou ALLOW_ADDON_SEED=1).
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys

from backend.services import daily_quota
from backend.services.db import DB_PATH
from backend.services.plans import ADDON_BY_CODE


def main() -> int:
    if (
        os.environ.get("RAILWAY_ENVIRONMENT_NAME") != "staging"
        and os.environ.get("ALLOW_ADDON_SEED") != "1"
    ):
        print("Recusado fora do staging.", file=sys.stderr)
        return 2
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", required=True)
    parser.add_argument("--pack", required=True, choices=sorted(ADDON_BY_CODE))
    args = parser.parse_args()
    conn = sqlite3.connect(DB_PATH, timeout=20)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT id FROM users WHERE email=?", (args.email,)).fetchone()
        if not row:
            print("Utilizador não encontrado.", file=sys.stderr)
            return 2
        user_id = int(row["id"])
    finally:
        conn.close()
    result = daily_quota.add_addon(user_id, args.pack, stripe_session_id=f"qa:{user_id}:{args.pack}")
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

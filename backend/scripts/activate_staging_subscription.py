"""Ativa um plano semanal para QA visual no staging.

Não é um endpoint público: corre dentro do contentor/CLI, nunca é exposto à
aplicação. Em produção exige `ALLOW_BILLING_SEED=1`; em staging aceita
`RAILWAY_ENVIRONMENT_NAME=staging`.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

from backend.services import subscription_billing
from backend.services.db import DB_PATH
from backend.services.plans import PLAN_BY_CODE


def main() -> int:
    if (
        os.environ.get("RAILWAY_ENVIRONMENT_NAME") != "staging"
        and os.environ.get("ALLOW_BILLING_SEED") != "1"
    ):
        print("Recusado fora do staging.", file=sys.stderr)
        return 2
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", required=True)
    parser.add_argument("--plan", required=True, choices=sorted(PLAN_BY_CODE))
    parser.add_argument("--days", type=int, default=7)
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

    until = (datetime.now(timezone.utc) + timedelta(days=max(1, args.days))).isoformat()
    result = subscription_billing.activate_weekly_subscription(
        user_id, args.plan, plan_until=until, status="active"
    )
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

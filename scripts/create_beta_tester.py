"""Cria/renova uma conta de beta tester no staging.

Uso (NUNCA em produção):

    ALLOW_STAGING_SEED=1 LEADS_DB_PATH=/caminho/staging/leads.db \
      python scripts/create_beta_tester.py --email tester@exemplo.com \
      --password 'SenhaForte123!' --name "Nome do Tester" [--days 14] [--dry-run]

O script recusa correr sem as variáveis e recusa caminhos do repositório de
produção. Não altera a landing nem o código da aplicação.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

if os.getenv("ALLOW_STAGING_SEED") != "1":
    raise SystemExit("Refusing: set ALLOW_STAGING_SEED=1 for staging only")
if not os.getenv("LEADS_DB_PATH"):
    raise SystemExit("Refusing: set LEADS_DB_PATH to the staging database")
if "garimpador-leads" in str(Path(os.environ["LEADS_DB_PATH"]).resolve()):
    raise SystemExit("Refusing a path inside the production repository")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services import security  # noqa: E402
from backend.services.db import db_service  # noqa: E402

INTERESTS = [
    "Roof", "Structure", "Plumbing", "Grass", "Paint", "Permit_Rejected",
    "Heating", "Electrical", "Elevator", "Gas", "Rodent", "Mold", "Lead",
    "Unsanitary", "Door_Window", "Debris",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Conta de beta tester (staging)")
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--name", default="Beta Tester")
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    email = args.email.strip().lower()
    if "@" not in email or len(email) < 5:
        raise SystemExit("email invalido")
    if len(args.password) < 8:
        raise SystemExit("password deve ter pelo menos 8 caracteres")

    svc = db_service._service
    existing = svc.get_user_by_email(email)
    if args.dry_run:
        print(("existing" if existing else "new"), email, f"+{args.days}d", args.name)
        return

    if existing:
        user = existing
        svc.extend_access(user["id"], days=args.days)
        svc.set_user_interests(user["id"], INTERESTS)
        print(f"Conta existente renovada: {email} (+{args.days} dias)")
    else:
        user = svc.create_user(
            email,
            security.hash_password(args.password),
            args.name,
            plan="pro",
            subscription_status="active",
        )
        svc.extend_access(user["id"], days=args.days)
        svc.set_user_interests(user["id"], INTERESTS)
        print(f"Conta criada: {email} / {args.password} (+{args.days} dias)")

    print(f"user_id={user['id']} interesses={len(INTERESTS)}")


if __name__ == "__main__":
    main()

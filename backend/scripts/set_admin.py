"""Promove/revoga o flag is_admin de um utilizador pelo email.

uso (local ou Railway shell, com LEADS_DB_PATH a apontar para a BD certa):

    python -m backend.scripts.set_admin fabio@magicleads.com
    python -m backend.scripts.set_admin fabio@magicleads.com --revoke
    python -m backend.scripts.set_admin --list

Nao existe endpoint HTTP para isto de proposito: promocao de privilegios
feita pela propria API permitiria escalacao (basta ter a propria conta).
"""
from __future__ import annotations

import argparse
import os
import sys

import anyio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.services.db import db_service  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Gerir o flag is_admin de um utilizador")
    parser.add_argument("email", nargs="?", help="Email do utilizador")
    parser.add_argument("--revoke", action="store_true", help="Revoga em vez de promover")
    parser.add_argument("--list", action="store_true", help="Lista os admins atuais")
    args = parser.parse_args()

    if args.list:
        users = anyio.run(db_service.get_all_users)
        admins = [u for u in users if u.get("is_admin")]
        if not admins:
            print("Nenhum administrador definido.")
            return 0
        for u in admins:
            print(f"  id={u['id']:<6} {u['email']}")
        return 0

    if not args.email:
        parser.error("email obrigatorio (ou use --list)")

    # `db_service` e a AsyncDatabaseService: sem `anyio.run` isto devolvia uma
    # corrotina (sempre truthy) e o script imprimia "OK" sem promover ninguem.
    ok = anyio.run(db_service.set_user_admin, args.email, not args.revoke)
    if not ok:
        print(f"Utilizador nao encontrado: {args.email}")
        return 1

    acao = "revogado" if args.revoke else "promovido a admin"
    print(f"OK: {args.email} {acao}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

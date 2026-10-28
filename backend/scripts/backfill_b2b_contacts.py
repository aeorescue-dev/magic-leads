#!/usr/bin/env python3
"""Backfill: liga contactos B2B orfaos (lead_id NULL) a leads `import_b2b`.

Porque existe
-------------
`import_contractors.py` (versao anterior) gravava em `outbound_contacts` com
`lead_id=None`. O painel e o `enqueue_batch` pesquisam por `oc.lead_id = leads.id`
e por `leads.source_type='import_b2b'`, logo esses contactos eram invisiveis:
"Com e-mail" continuava 0.

Este script cria o lead `import_b2b` correspondente (via `import_b2b_lead`, que
tambem actualiza o contacto com o `lead_id` certo) para cada contacto orfao.

Idempotente: correr duas vezes nao duplica nada (external_id = 'b2b:<email>').

Uso:
    python -m backend.scripts.backfill_b2b_contacts --dry-run
    python -m backend.scripts.backfill_b2b_contacts
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from ..services import db as dbmod
from ..services.db import db_service


def _orphans() -> list[dict]:
    conn = dbmod.get_connection()
    try:
        rows = conn.execute(
            "SELECT id, email, company_name, city, state, company_domain "
            "FROM outbound_contacts "
            "WHERE lead_id IS NULL AND COALESCE(email, '') <> '' "
            "ORDER BY id"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


async def main(dry_run: bool) -> int:
    rows = _orphans()
    print(f"Contactos orfaos (lead_id NULL): {len(rows)}")
    if not rows:
        return 0

    linked = 0
    for row in rows:
        print(f"  [{row['id']}] {row['email']} | {row.get('company_name')} | {row.get('city')}")
        if dry_run:
            continue
        if not row.get("city"):
            print("     SKIP: sem cidade (import_b2b exige cidade)")
            continue
        result = await db_service.import_b2b_lead(
            email=row["email"],
            company_name=row.get("company_name") or row["email"].split("@")[1],
            city=row["city"],
            category="General Contractors",
            contact_name=None,
            domain=row.get("company_domain"),
            state=row.get("state"),
        )
        if result and result.get("lead_id"):
            linked += 1
            print(f"     -> lead_id={result.get('lead_id')}")
        else:
            print("     FALHOU")

    if dry_run:
        print("\nDRY-RUN: nada gravado.")
        return 0

    print(f"\nLigados: {linked}/{len(rows)}")
    return 0 if linked == len(rows) else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Backfill de contactos B2B orfaos")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    sys.exit(asyncio.run(main(args.dry_run)))

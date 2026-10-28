#!/usr/bin/env python3
"""CLI de enriquecimento de e-mails por cidade (usa o worker SMTP da VPS).

Exemplos:
    python -m backend.scripts.enrich_city --city Chicago --limit 10
    python -m backend.scripts.enrich_city --city Chicago --only-company --limit 50
    python -m backend.scripts.enrich_city --city Boston --nicho general_contractors --limit 200

Fluxo por lead:
  1. `discovery_engine.enrich_lead_email` descobre o dominio da empresa
     (heuristica por slug + corroboracao do site);
  2. a validacao RCPT e' delegada ao micro-worker VPS
     (`VPS_WORKER_URL`/`VPS_WORKER_SECRET`), porque a porta 25 de saida esta'
     bloqueada no Railway;
  3. apenas e-mails `valid` viram linha em `outbound_contacts`
     (catch-all / all-accept nunca sao promovidos).

Nada e' enviado: nunca ha' DATA no SMTP. `send_enabled` nao e' tocado.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time

from ..services import discovery_engine, outbound_templates
from ..services.db import db_service
from ..services.lead_filter import classify_owner_name


def _usable_name(owner_name: str | None, only_company: bool) -> bool:
    cls = classify_owner_name(owner_name or "")
    if cls in ("institutional", "empty"):
        return False
    if only_company and cls != "company":
        return False
    return True


async def _run(city: str, niche: str, limit: int, only_company: bool) -> dict:
    city = (city or "").strip().upper()
    categories = outbound_templates.niche_categories(niche)
    leads = await db_service.list_outbound_leads(city, categories, limit)

    stats = {
        "city": city,
        "niche": niche,
        "candidates": len(leads),
        "created": 0,
        "no_email": 0,
        "skipped": 0,
        "error": 0,
    }
    started = time.time()

    for idx, lead in enumerate(leads, 1):
        if not _usable_name(lead.get("owner_name"), only_company):
            stats["skipped"] += 1
        else:
            result = await discovery_engine.enrich_lead_email(db_service, lead)
            status = result.get("status")
            if status == "success":
                stats["created"] += 1
                print(
                    f"[OK]  lead={lead.get('id')} email={result.get('email')} "
                    f"status={result.get('email_status')} ({result.get('email_source')})"
                )
            elif status == "skipped":
                stats["skipped"] += 1
            elif status == "no_email_found":
                stats["no_email"] += 1
            else:
                stats["error"] += 1
                print(f"[ERR] lead={lead.get('id')} {result.get('error')}")

        if idx % 10 == 0 or idx == len(leads):
            elapsed = time.time() - started
            print(
                f"--- progresso {idx}/{len(leads)} | criados={stats['created']} "
                f"sem_email={stats['no_email']} saltados={stats['skipped']} "
                f"| {elapsed:.0f}s ---"
            )

    return stats


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Enriquece e-mails de uma cidade via worker SMTP da VPS"
    )
    parser.add_argument("--city", required=True)
    parser.add_argument(
        "--nicho",
        default="general_contractors",
        choices=sorted(outbound_templates.NICHES),
    )
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument(
        "--only-company",
        action="store_true",
        help="Processa apenas nomes de empresa (ignora pessoas fisicas: quase nunca resolvem dominio)",
    )
    args = parser.parse_args()

    if not (os.getenv("VPS_WORKER_URL") or "").strip():
        print("ERRO: VPS_WORKER_URL ausente — o probe cairia na porta 25 local.")
        return 2

    stats = asyncio.run(_run(args.city, args.nicho, args.limit, args.only_company))
    print("\n=== RESUMO ===")
    for k, v in stats.items():
        print(f"{k}: {v}")
    return 0 if stats["created"] else 1


if __name__ == "__main__":
    sys.exit(main())

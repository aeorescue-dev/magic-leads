#!/usr/bin/env python3
"""Valida e-mails candidatos de uma lista de dominios usando o worker VPS.

Uso principal (lote B2B): recebe dominios de empresas e valida caixas genericas
e/ou personalizadas atraves do micro-worker SMTP da Contabo, gravando em
`outbound_contacts` apenas o que o MX confirmar como `valid`.

    python -m backend.scripts.validate_domains --domains acme.com,foo.com --city Chicago
    python -m backend.scripts.validate_domains --csv contractors.csv
    python -m backend.scripts.validate_domains --csv contractors.csv --dry-run

CSV aceita as colunas: company, domain, city, state (state opcional).
`company` e `city` sao obrigatorios; `domain` e' obrigatorio.

Regras anti-spam:
  * so' `status == "valid"` vira contacto (catch-all/all-accept e' descartado);
  * no maximo `VPS_RATE_LIMIT_SECONDS` (1s) por dominio — o proprio worker aplica;
  * nunca ha' DATA: nenhuma mensagem e' enviada.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import os
import sys
import time

from ..services import vps_prober
from ..services.db import db_service
from ..services.enrichment_emaillistverify import normalize_email

# Ordem de probabilidade para caixas genericas de empresas de oficio.
DEFAULT_LOCALS = ["info", "contact", "office", "sales", "estimates", "admin"]


def _load_csv(path: str) -> list[dict]:
    rows: list[dict] = []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for raw in csv.DictReader(fh):
            domain = (raw.get("domain") or "").strip().lower()
            company = (raw.get("company") or raw.get("company_name") or "").strip()
            city = (raw.get("city") or "").strip()
            if not domain or not company or not city:
                continue
            rows.append(
                {
                    "company": company,
                    "domain": domain,
                    "city": city,
                    "state": (raw.get("state") or "").strip() or None,
                }
            )
    return rows


def _load_domains(arg: str, city: str, state: str | None) -> list[dict]:
    out = []
    for domain in (arg or "").split(","):
        domain = domain.strip().lower()
        if not domain:
            continue
        out.append(
            {"company": domain.split(".")[0].replace("-", " ").title(),
             "domain": domain, "city": city, "state": state}
        )
    return out


async def _run(items: list[dict], locals_: list[str], dry_run: bool) -> dict:
    stats = {"targets": len(items), "validated": 0, "saved": 0,
             "inconclusive": 0, "invalid": 0, "errors": 0}
    started = time.time()

    for idx, item in enumerate(items, 1):
        domain, company, city = item["domain"], item["company"], item["city"]
        found = None
        for local in locals_:
            email = f"{local}@{domain}"
            if not normalize_email(email):
                continue
            try:
                res = vps_prober.probe_smtp_via_vps(email, domain, timeout=20.0)
            except Exception as exc:  # noqa: BLE001
                stats["errors"] += 1
                print(f"[ERR] {email}: {exc}")
                continue
            status = res.get("status")
            stats["validated"] += 1
            print(f"   {email} -> {status} (code={res.get('code')}, "
                  f"mx={res.get('mx_host')}, {res.get('latency_ms')}ms)")
            if status == "valid":
                found = email
                break
            if status == "invalid":
                stats["invalid"] += 1
            else:
                stats["inconclusive"] += 1

        if found:
            if dry_run:
                print(f"[DRY] salvaria {company} <{found}> ({city})")
            else:
                contact = await db_service.upsert_outbound_contact(
                    lead_id=None, email=found, city=city, state=item.get("state"),
                    company_name=company, contact_name=None,
                    email_source="smtp_direct_vps", email_status="valid",
                    company_domain=domain,
                )
                if contact:
                    stats["saved"] += 1
                    print(f"[OK]  {found} salvo (contact_id={contact.get('id')})")
        else:
            print(f"[--]  {company}: nenhuma caixa confirmada em {domain}")

        if idx % 5 == 0 or idx == len(items):
            print(f"--- progresso {idx}/{len(items)} | salvos={stats['saved']} "
                  f"| {time.time() - started:.0f}s ---")

    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="Valida dominios via worker SMTP da VPS")
    parser.add_argument("--domains", help="Lista separada por virgulas: acme.com,foo.com")
    parser.add_argument("--csv", help="CSV com colunas company,domain,city[,state]")
    parser.add_argument("--city", default="Chicago")
    parser.add_argument("--state")
    parser.add_argument("--locals", default=",".join(DEFAULT_LOCALS),
                        help="Caixas a testar, por ordem")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not (os.getenv("VPS_WORKER_URL") or "").strip():
        print("ERRO: VPS_WORKER_URL ausente — sem worker nao ha' validacao real.")
        return 2

    if args.csv:
        items = _load_csv(args.csv)
    elif args.domains:
        items = _load_domains(args.domains, args.city, args.state)
    else:
        parser.error("informe --domains ou --csv")

    if not items:
        print("Nada a validar.")
        return 1

    locals_ = [x.strip().lower() for x in args.locals.split(",") if x.strip()]
    print(f"Alvos: {len(items)} dominios | caixas: {locals_}")
    if args.dry_run:
        print("MODO DRY-RUN: nada sera' gravado\n")

    stats = asyncio.run(_run(items, locals_, args.dry_run))
    print("\n=== RESUMO ===")
    for k, v in stats.items():
        print(f"{k}: {v}")
    return 0 if stats["saved"] or args.dry_run else 1


if __name__ == "__main__":
    sys.exit(main())

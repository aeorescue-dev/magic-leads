#!/usr/bin/env python3
"""Importa contractors licenciados (nome + website) e valida e-mails via VPS.

Porque existe
-------------
As bases 311 nao trazem identidade de empresa (Boston: 0/2.790 com owner_name).
O rendimento da descoberta por heuristica nesses dados e' ~4%. Com o **website
conhecido** o dominio deixa de ser adivinhado e o rendimento sobe para 40-60%.

Este script aceita exportacoes dos registos de licenciamento estaduais:

  * Massachusetts  -> DPL / Board of Building Regulations (Licensed Contractors)
  * Illinois       -> IDFPR License Lookup (Roofing, Plumbing, Electrical)
  * Texas          -> TDLR (Air Conditioning & Refrigeration Contractors)
  * New York City  -> DOB NOW / Licensed Trades

Formato CSV (cabecalho obrigatorio):
    company,website,city,state
    Skender,https://www.skender.com,Chicago,IL
    Acme Roofing,acmeroofing.com,Boston,MA

Fluxo por linha:
  1. normaliza o website -> dominio registravel;
  2. confirma MX do dominio (senao descarta: nunca vale a pena sondar);
  3. gera candidatos (`info@`, `contact@`, ... e/ou padrao do nome);
  4. valida RCPT no worker SMTP da Contabo (nunca ha' DATA);
  5. grava em `outbound_contacts` apenas `status == "valid"`.

Uso:
    python -m backend.scripts.import_contractors --csv backend/data/imports/chicago_contractors.csv
    python -m backend.scripts.import_contractors --csv lista.csv --dry-run
    python -m backend.scripts.import_contractors --csv lista.csv --report falhas.csv
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import sys
import time

from ..services import niche_classifier, outbound_templates, vps_prober
from ..services.company_discovery import (
    CompanyDiscovery,
    default_fetch,
    email_patterns,
    extract_text,
    registrable_domain,
)
from ..services.db import db_service
from ..services.enrichment_emaillistverify import normalize_email
from ..services.lead_filter import classify_owner_name

MAX_CANDIDATES = 6


def _read_csv(path: str) -> tuple[list[dict], list[dict]]:
    ok: list[dict] = []
    bad: list[dict] = []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for raw in csv.DictReader(fh):
            company = (raw.get("company") or raw.get("company_name") or "").strip()
            website = (raw.get("website") or raw.get("domain") or "").strip()
            city = (raw.get("city") or "").strip()
            state = (raw.get("state") or "").strip() or None
            if not company or not website or not city:
                bad.append({**raw, "reason": "campos obrigatorios ausentes"})
                continue
            domain = registrable_domain(website)
            if not domain:
                bad.append({**raw, "reason": "website invalido"})
                continue
            ok.append(
                {"company": company, "website": website, "domain": domain,
                 "city": city, "state": state,
                 "category": (raw.get("category") or "").strip() or None}
            )
    return ok, bad


def _candidates(company: str, domain: str) -> list[str]:
    cls = classify_owner_name(company)
    locals_ = email_patterns(company, cls)[:MAX_CANDIDATES]
    out, seen = [], set()
    for local in locals_:
        email = f"{local}@{domain}"
        if email in seen or not normalize_email(email):
            continue
        seen.add(email)
        out.append(email)
    return out


async def _run(items: list[dict], dry_run: bool, niche_label: str) -> tuple[dict, list[dict]]:
    stats = {"companies": len(items), "with_mx": 0, "validated": 0,
             "saved": 0, "no_mx": 0, "no_valid_email": 0, "quarantined": 0}
    misses: list[dict] = []
    discovery = CompanyDiscovery()
    started = time.time()

    for idx, item in enumerate(items, 1):
        domain, company = item["domain"], item["company"]
        lead = {"owner_name": company, "city": item["city"]}

        # Confirma que o dominio tem destino SMTP. Sem MX, aceita-se o A do
        # proprio dominio (MX implicito, RFC 5321 5.1); so' se nao existir
        # nenhum dos dois e' que se descarta sem gastar sondagem.
        website = item["website"]
        if "://" not in website:
            website = f"https://{website}"
        try:
            info = await asyncio.to_thread(discovery.domain_from_website, website, lead)
        except Exception as exc:  # noqa: BLE001
            info = None
            print(f"[ERR] {company}: {exc}")
        if not info:
            has_a = await asyncio.to_thread(discovery._resolver.a_record, domain)
            if not has_a:
                stats["no_mx"] += 1
                misses.append({**item, "reason": "sem MX e sem A"})
                print(f"[--]  {company}: sem MX nem A em {domain}")
                continue
        stats["with_mx"] += 1

        # --- 1. nicho por EMPRESA (nunca pelo lote) ----------------------
        verdict = niche_classifier.classify(company, domain=domain)
        if verdict["status"] != "confirmed":
            # segundo sinal: texto do site (1 fetch). Sem isto, GCs cujo nome
            # nao contem "construction" (Skender, Walsh) ficavam unknown.
            page = await asyncio.to_thread(default_fetch, f"https://{domain}/", 6.0)
            if page and page.get("html"):
                try:
                    title, body_text = extract_text(page["html"])
                except Exception:  # noqa: BLE001
                    title, body_text = "", ""
                site = f"{title} {body_text[:6000]}".strip()
                if site:
                    verdict = niche_classifier.classify(
                        company, domain=domain, text=site
                    )

        niche_key = verdict["niche"]
        niche_status = verdict["status"]
        evidence = json.dumps(verdict, ensure_ascii=False)
        print(f"   nicho: {niche_key or '-'} ({niche_status}, "
              f"score={verdict['score']}, margin={verdict['margin']})")

        if niche_status != "confirmed" or not niche_key:
            if not dry_run:
                await db_service.import_b2b_lead(
                    email=f"quarantine+{domain}@local.invalid",
                    company_name=company,
                    city=item["city"],
                    category=item.get("category") or niche_label,
                    domain=domain,
                    state=item["state"],
                    niche_key=None,
                    niche_status="ambiguous" if niche_status == "ambiguous" else "unknown",
                    niche_score=verdict["score"],
                    niche_evidence=evidence,
                    create_contact=False,
                )
            stats["quarantined"] += 1
            misses.append({**item, "reason": f"nicho {niche_status}"})
            print(f"   QUARENTENA ({niche_status}) - sem contacto, sem sondagem SMTP")
            continue

        # --- 2. validacao SMTP so' para nicho confirmado -----------------
        found = None
        for email in _candidates(company, domain):
            try:
                res = vps_prober.probe_smtp_via_vps(email, domain, timeout=20.0)
            except Exception as exc:  # noqa: BLE001
                print(f"[ERR] {email}: {exc}")
                continue
            status = res.get("status")
            stats["validated"] += 1
            print(f"   {email} -> {status} (code={res.get('code')})")
            if status == "valid":
                found = email
                break

        if not found:
            stats["no_valid_email"] += 1
            misses.append({**item, "reason": "nenhuma caixa valid"})
            continue

        if dry_run:
            print(f"[DRY] salvaria {company} <{found}> ({item['city']}) "
                  f"nicho={niche_key}")
            stats["saved"] += 1
            continue

        contact = await db_service.import_b2b_lead(
            email=found,
            company_name=company,
            city=item["city"],
            category=outbound_templates.NICHES[niche_key]["label"],
            contact_name=None,
            domain=domain,
            state=item["state"],
            niche_key=niche_key,
            niche_status="confirmed",
            niche_score=verdict["score"],
            niche_evidence=evidence,
        )
        if contact:
            stats["saved"] += 1
            print(f"[OK]  {found} salvo (contact_id={contact.get('id')}, "
                  f"nicho={niche_key})")

        if idx % 5 == 0 or idx == len(items):
            print(f"--- {idx}/{len(items)} | salvos={stats['saved']} "
                  f"| {time.time() - started:.0f}s ---")

    return stats, misses


def main() -> int:
    ap = argparse.ArgumentParser(description="Importa contractors com website e valida via VPS")
    ap.add_argument("--csv", required=True)
    ap.add_argument(
        "--nicho",
        default=outbound_templates.DEFAULT_NICHE,
        choices=sorted(outbound_templates.NICHES),
        help="Nicho do painel ao qual estes contactos pertencem (default: general_contractors)",
    )
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--report", help="CSV de saida com as empresas sem e-mail valido")
    args = ap.parse_args()

    if not (os.getenv("VPS_WORKER_URL") or "").strip():
        print("ERRO: VPS_WORKER_URL ausente — sem worker nao ha' validacao real.")
        return 2

    items, bad = _read_csv(args.csv)
    for row in bad:
        print(f"[ SKIP ] linha invalida: {row}")
    if not items:
        print("Nada a importar.")
        return 1

    niche_label = outbound_templates.NICHES[args.nicho]["label"]
    print(f"Empresas a processar: {len(items)} | nicho: {niche_label}")
    stats, misses = asyncio.run(_run(items, args.dry_run, niche_label))
    print("\n=== RESUMO ===")
    for k, v in stats.items():
        print(f"{k}: {v}")

    if args.report and misses:
        with open(args.report, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(misses[0].keys()))
            w.writeheader()
            w.writerows(misses)
        print(f"Relatorio de falhas: {args.report}")

    return 0 if stats["saved"] else 1


if __name__ == "__main__":
    sys.exit(main())

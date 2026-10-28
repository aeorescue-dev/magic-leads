#!/usr/bin/env python3
"""Reclassifica o nicho dos contactos existentes (niche_classifier).

Necessario porque os contactos importados antes do classificador ficaram com a
etiqueta do LOTE (`--nicho`), nao com o nicho real da empresa. Sem isto, o gate
de envio recusa-os (niche_status='unknown') ou, pior, enviava copy errado.

Uso:
    python -m backend.scripts.backfill_niche --dry-run
    python -m backend.scripts.backfill_niche
    python -m backend.scripts.backfill_niche --only-unknown
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import sys

from ..services import niche_classifier
from ..services.company_discovery import default_fetch, extract_text


def _rows(only_unknown: bool) -> list[dict]:
    from ..services.db import DB_PATH as _DB_PATH
    db = _DB_PATH
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    try:
        where = "WHERE COALESCE(oc.niche_status,'unknown') <> 'confirmed'" if only_unknown else ""
        rows = con.execute(
            f"""
            SELECT oc.id AS contact_id, oc.email, oc.company_name, oc.company_domain,
                   oc.city, oc.lead_id, COALESCE(oc.niche_key,'') AS old_niche,
                   COALESCE(oc.niche_status,'unknown') AS old_status
            FROM outbound_contacts oc
            {where}
            ORDER BY oc.id
            """
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def _apply(updates: list[dict]) -> None:
    from ..services.db import DB_PATH as _DB_PATH
    db = _DB_PATH
    con = sqlite3.connect(db)
    try:
        for u in updates:
            con.execute(
                "UPDATE outbound_contacts SET niche_key=?, niche_status=? WHERE id=?",
                (u["niche_key"], u["niche_status"], u["contact_id"]),
            )
            if u.get("lead_id"):
                con.execute(
                    "UPDATE leads SET niche_key=?, niche_status=?, niche_score=?, "
                    "niche_evidence=? WHERE id=?",
                    (u["niche_key"], u["niche_status"], u["score"],
                     u["evidence"], u["lead_id"]),
                )
        con.commit()
    finally:
        con.close()


async def main(dry_run: bool, only_unknown: bool) -> int:
    rows = _rows(only_unknown)
    print(f"contactos a reclassificar: {len(rows)}\n")

    updates: list[dict] = []
    ok = 0
    for r in rows:
        company = (r.get("company_name") or "").strip()
        domain = (r.get("company_domain") or "").strip()
        if not domain and r.get("email") and "@" in r["email"]:
            domain = r["email"].split("@", 1)[1]

        verdict = niche_classifier.classify(company, domain=domain)
        if verdict["status"] != "confirmed" and domain:
            page = await asyncio.to_thread(default_fetch, f"https://{domain}/", 6.0)
            if page and page.get("html"):
                try:
                    title, body = extract_text(page["html"])
                except Exception:  # noqa: BLE001
                    title, body = "", ""
                site = f"{title} {body[:6000]}".strip()
                if site:
                    verdict = niche_classifier.classify(
                        company, domain=domain, text=site
                    )

        niche = verdict["niche"]
        status = verdict["status"]
        mark = "OK " if status == "confirmed" else "-- "
        print(f"{mark}#{r['contact_id']:3} {r['email'][:34]:34} "
              f"{company[:26]:26} -> {str(niche):20} {status:10} "
              f"(era {r['old_niche'] or '-'}/{r['old_status']})")
        if status == "confirmed":
            ok += 1
        updates.append({
            "contact_id": r["contact_id"],
            "lead_id": r.get("lead_id"),
            "niche_key": niche,
            "niche_status": status,
            "score": verdict["score"],
            "evidence": json.dumps(verdict, ensure_ascii=False),
        })

    print(f"\nconfirmados: {ok}/{len(rows)}")
    if dry_run:
        print("DRY-RUN: nada gravado.")
        return 0
    _apply(updates)
    print("base actualizada.")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Reclassifica nicho dos contactos")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only-unknown", action="store_true")
    args = ap.parse_args()
    sys.exit(asyncio.run(main(args.dry_run, args.only_unknown)))

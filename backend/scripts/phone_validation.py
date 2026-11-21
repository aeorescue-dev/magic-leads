"""Validacao real do telefone do proprietario nas 4 cidades (read-only).

O que faz
---------
1. Le uma amostra estratificada de leads de producao (pessoa / entidade /
   absentee / registo antigo) por cidade.
2. Resolve o proprietario pela camada unica (4 adapters) e mostra a prova:
   parcela, metodo, confianca, ano, stale.
3. Aplica a politica e diz o que o clique faria (ready/in_progress/blocked).
4. Com `--live`, consulta a Searchbug com um TETO DURO de chamadas e sem
   gravar telefone em `leads` nem em `phone_lookups`.
5. Escreve CSV para revisao manual + resumo JSON/consola.

Nao altera dados. A unica accao externa e' a consulta paga, e so' com `--live`.

Exemplos
--------
    python -m backend.scripts.phone_validation --city all --limit 40
    python -m backend.scripts.phone_validation --city NYC --limit 20 --live --max-calls 20
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import random
import re
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

CITIES = ("NYC", "CHICAGO", "BOSTON", "DALLAS")
DEFAULT_DB = os.getenv("DB_PATH") or str(Path(__file__).resolve().parents[2] / "data" / "leads.db")


def _ro_connection(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _norm(value: Optional[str]) -> str:
    return " ".join(re.findall(r"[A-Z0-9]+", str(value or "").upper()))


def _is_entity(name: Optional[str]) -> bool:
    from backend.services.lead_rules import is_corporate_name

    return bool(name) and is_corporate_name(name)


def _lead_kind(lead: dict[str, Any]) -> str:
    from backend.services.lead_rules import get_owner_kind

    kind = get_owner_kind(lead.get("owner_name"))
    return "company" if kind == "company" else ("person" if kind == "person" else "unknown")


def _sample(db_path: str, city: str, limit: int) -> list[dict[str, Any]]:
    """Amostra estratificada: pessoa, entidade, absentee, sem duplicados."""
    conn = _ro_connection(db_path)
    try:
        base = """
            SELECT id, address, city, state, zip_code, owner_name, owner_phone,
                   mailing_address, bbl, phone_verified, issue_category
            FROM leads
            WHERE UPPER(city) = ? AND phone_eligible = 1
              AND TRIM(COALESCE(owner_name, '')) <> ''
              AND TRIM(COALESCE(address, '')) <> ''
            ORDER BY id DESC
            LIMIT 2000
        """
        rows = [dict(r) for r in conn.execute(base, (city.upper(),)).fetchall()]
    finally:
        conn.close()

    # Pool recente e baralhado: evita que a amostra seja sempre a mesma ponta
    # do feed (que tem vies de cidade/nicho).
    random.shuffle(rows)
    from backend.services.owner_resolution.base import mailing_matches_property

    person = [r for r in rows if not _is_entity(r.get("owner_name"))]
    entity = [r for r in rows if _is_entity(r.get("owner_name"))]
    absentee = [
        r for r in person
        if r.get("mailing_address")
        and not mailing_matches_property(r.get("address"), r.get("mailing_address"))
    ]
    owner_occupied = [r for r in person if r not in absentee]

    buckets = [entity, absentee, owner_occupied]
    picked: list[dict[str, Any]] = []
    seen: set[int] = set()
    per_bucket = max(1, limit // len(buckets))
    for bucket in buckets:
        for row in bucket:
            if len(picked) >= limit:
                break
            if row["id"] in seen:
                continue
            seen.add(row["id"])
            picked.append(row)
            if sum(1 for p in picked if p in bucket) >= per_bucket:
                break
    # Completa com o que sobrar, sem repetir.
    for row in rows:
        if len(picked) >= limit:
            break
        if row["id"] not in seen:
            seen.add(row["id"])
            picked.append(row)
    return picked[:limit]


async def _evaluate(row: dict[str, Any], live: bool, budget: dict[str, int]):
    from backend.services import phone_policy
    from backend.services.owner_resolution import resolve_owner
    from backend.services.searchbug import searchbug_service

    record = await resolve_owner(
        row.get("address", ""), row.get("city"), bbl=row.get("bbl")
    )
    lead = dict(row)
    decision = await phone_policy.decide(lead, owner=record, allow_resolve=False)

    out: dict[str, Any] = {
        "id": row["id"],
        "city": row["city"],
        "address": row.get("address"),
        "owner_name_db": row.get("owner_name"),
        "owner_name_resolved": record.owner_name if record else None,
        "owner_kind": record.owner_kind if record else _lead_kind(lead),
        "parcel_key": record.parcel_key if record else None,
        "match_method": record.match_method if record else None,
        "confidence": record.confidence if record else None,
        "record_year": record.record_year if record else None,
        "stale": record.stale if record else None,
        "absentee": record.is_absentee if record else None,
        "decision": decision.state,
        "reason": decision.reason,
        "candidate_kind": decision.candidates[0].kind if decision.candidates else None,
        "candidate_layer": decision.candidates[0].layer if decision.candidates else None,
        "provider_called": False,
        "provider_success": None,
        "returned_name": None,
        "name_match": None,
        "phone_type": None,
        "verified_formula": None,
        "label": None,
        "review": "",
    }

    if not live or not decision.allow_paid_call:
        return out
    if budget["remaining"] <= 0:
        out["reason"] = "validation_budget_exhausted"
        return out

    candidate = decision.candidates[0]
    budget["remaining"] -= 1
    budget["used"] += 1
    result = await searchbug_service.lookup_phone(
        candidate.address,
        row.get("city", ""),
        row.get("state", ""),
        owner_name=candidate.owner_name,
        zip_code=row.get("zip_code"),
        lead_id=row["id"],
        trigger="validation",
    )
    out["provider_called"] = True
    out["provider_success"] = bool(result.success)
    out["returned_name"] = " ".join(
        part for part in [getattr(result, "returned_first", None), getattr(result, "returned_last", None)] if part
    ) or None
    out["name_match"] = getattr(result, "name_match", None)
    out["phone_type"] = getattr(result, "phone_type", None)
    out["layer"] = getattr(result, "layer", None)
    if result.success and result.phone:
        out["verified_formula"] = phone_policy.verified_result(
            candidate, bool(getattr(result, "verified", False)), record
        )
        out["label"] = phone_policy.label_for(candidate, out["verified_formula"])
    return out


async def _run(args) -> int:
    if args.live and args.max_calls <= 0:
        print("ERRO: --live exige --max-calls > 0 (teto duro de custo).", file=sys.stderr)
        return 2
    # Semente fixa: a mesma amostra produz o mesmo relatorio. Sem isto, cada
    # execucao escolhia 50 leads diferentes do pool de 300 e os numeros nao
    # eram comparaveis.
    random.seed(int(args.seed))
    budget = {"remaining": int(args.max_calls), "used": 0}
    cities = CITIES if args.city == "all" else (args.city.upper(),)
    rows_out: list[dict[str, Any]] = []

    for city in cities:
        sample = _sample(args.db, city, args.limit)
        print(f"[{city}] amostra={len(sample)}", file=sys.stderr)
        for row in sample:
            rows_out.append(await _evaluate(row, args.live, budget))

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / f"phone-validation-{stamp}.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows_out[0].keys()) if rows_out else ["id"])
        writer.writeheader()
        writer.writerows(rows_out)

    summary: dict[str, Any] = {
        "generated_at": stamp,
        "seed": int(args.seed),
        "live": bool(args.live),
        "live_calls_used": budget["used"],
        "live_calls_remaining": budget["remaining"],
        "by_city": {},
    }
    for city in cities:
        city_rows = [r for r in rows_out if str(r["city"]).upper() == city]
        called = [r for r in city_rows if r["provider_called"]]
        success = [r for r in called if r["provider_success"]]
        verified = [r for r in success if r["verified_formula"]]
        mismatched = [
            r for r in success
            if r["name_match"] is not None and r["name_match"] < 0.6
        ]
        summary["by_city"][city] = {
            "sample": len(city_rows),
            "decisions": dict(Counter(r["decision"] for r in city_rows)),
            "reasons": dict(Counter(r["reason"] for r in city_rows)),
            "owner_kinds": dict(Counter(str(r["owner_kind"]) for r in city_rows)),
            "confidence": dict(Counter(str(r["confidence"]) for r in city_rows)),
            "stale": sum(1 for r in city_rows if r["stale"]),
            "provider_called": len(called),
            "provider_success": len(success),
            "delivered_verified": len(verified),
            "name_mismatch": len(mismatched),
            "no_phone": len(called) - len(success),
        }

    json_path = out_dir / f"phone-validation-{stamp}.json"
    json_path.write_text(json.dumps({"summary": summary, "rows": rows_out}, indent=2), encoding="utf-8")

    print(json.dumps(summary, indent=2))
    print(f"\nCSV: {csv_path}\nJSON: {json_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--city", default="all", choices=[*CITIES, "all"])
    parser.add_argument("--limit", type=int, default=30, help="amostra por cidade")
    parser.add_argument("--seed", type=int, default=20261120, help="semente reprodutivel")
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--output", default="reports/phone-validation")
    parser.add_argument("--live", action="store_true", help="consulta paga real")
    parser.add_argument("--max-calls", type=int, default=0, help="teto duro de chamadas pagas")
    args = parser.parse_args()
    if not Path(args.db).exists():
        print(f"ERRO: DB nao encontrada: {args.db}", file=sys.stderr)
        return 2
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())

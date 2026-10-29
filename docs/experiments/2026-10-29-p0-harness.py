"""P0-0 — Experimento de telefone Searchbug ($0,20/chamada).

Standalone, read-only sobre `leads`. Escreve apenas /data/phone_experiment.jsonl.

Braços (40 chamadas = $8,00):
  A/B  — 10 pares no MESMO endereco (NYC): ordem atual (FIRST LAST) vs invertida
         (LAST FIRST). Mede o efeito da inversao com o endereco controlado.
  C    — 5 pares no MESMO endereco (Boston): ZIP de 4 digitos (como esta na BD)
         vs ZIP de 5 digitos com zero a esquerda.
  D    — 10 leads SEM nome (NYC/Chicago), L3 address-only. Mede o hit rate bruto
         e captura o nome devolvido para validacao futura.

Uso:
  python /tmp/p0_experiment.py --dry-run
  python /tmp/p0_experiment.py --max-calls 40
"""

import argparse
import asyncio
import json
import random
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, "/app")

from backend.config import settings  # noqa: E402
from backend.services.db import get_connection  # noqa: E402
from backend.services.lead_rules import (  # noqa: E402
    address_is_resolvable,
    is_institutional_name,
)
from backend.services.metrics import searchbug_metrics  # noqa: E402
from backend.services.searchbug import (  # noqa: E402
    _clean_owner_name,
    is_corporate_name,
    phone_lookup_service,
)

SEED = 20261030
PRICE = 0.20
OUT_PATH = Path("/data/phone_experiment.jsonl")

ENTITY_MARKERS = (
    "CONDO", "CONDOMINIUM", "TRUST", "TRST", "ESTATE", "CHURCH", "INSTITUTE",
    "SCHOOL", "CENTER", "TENANT", "PRES", "MGMT", "REALTY", "PROPERTIES",
    "INVESTMENT", "FIRM", "HOLDINGS", "ASSOCIATION", "ASSN", "CLUB", "LODGE",
    "MANOR", "GARDENS", "PLAZA", "TOWERS", "HOMES", "APARTMENTS", "ARMS",
    "VILLAS",
)
NUMBER_WORDS = {
    "ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX", "SEVEN", "EIGHT", "NINE",
    "TEN", "ELEVEN", "TWELVE", "THIRTEEN", "FOURTEEN", "FIFTEEN", "SIXTEEN",
    "SEVENTEEN", "EIGHTEEN", "NINETEEN", "TWENTY", "THIRTY", "FORTY", "FIFTY",
    "SIXTY", "SEVENTY", "EIGHTY", "NINETY", "HUNDRED",
}
NAME_STOP = {"MR", "MRS", "MS", "DR", "SR", "JR", "II", "III", "IV", "V"}


def zip5(value):
    z = (value or "").strip()
    if re.fullmatch(r"\d{5}(-\d{4})?", z):
        return z[:5]
    if z.isdigit() and len(z) == 4:
        return z.zfill(5)
    return ""


def clean_person(raw):
    if not raw:
        return None
    clean, err = _clean_owner_name(raw)
    if err or is_institutional_name(clean) or is_corporate_name(clean):
        return None
    up = clean.upper()
    if any(j in up for j in (
        "UNAVAILABLE", "TAXPAYER", "OWNER OF", "RAILROAD", "CITY OF",
        "UNKNOWN", "PRIVATE OWNER", "RLTY", "MGMT", "ASSOC", "HDFC",
    )):
        return None
    tokens = clean.split()
    if not (2 <= len(tokens) <= 4):
        return None
    if len(tokens[0]) == 1:
        return None
    if "&" in clean or "-" in clean:
        return None
    if any(m in up for m in ENTITY_MARKERS):
        return None
    if tokens[0].upper() in NUMBER_WORDS:
        return None
    if tokens[-1].upper().strip(".") in {
        "TR", "TS", "EST", "ESTATE", "TRUSTEE", "CD", "CONDO", "HDFC",
    }:
        return None
    return clean


def tokens(name):
    return {
        t for t in re.findall(r"[A-Z]+", (name or "").upper())
        if t not in NAME_STOP and len(t) > 1
    }


def name_match(owner, first, last):
    o = tokens(owner)
    r = tokens(first) | tokens(last)
    if not o:
        return None
    return round(len(o & r) / len(o), 3)


def split_for_arm(name, arm):
    """Devolve o `owner_name` a passar ao provider para obter a ordem desejada."""
    toks = name.split()
    if arm == "current":
        return name
    if len(toks) == 2:
        return f"{toks[1]} {toks[0]}"
    # LAST FIRST MIDDLE -> FIRST LAST MIDDLE
    return " ".join([toks[1], toks[0]] + toks[2:])


def load_rows():
    conn = get_connection()
    try:
        return [dict(r) for r in conn.execute(
            """SELECT id, city, state, address, zip_code, owner_name
               FROM leads
               WHERE COALESCE(owner_phone,'') = ''
                 AND COALESCE(address,'') <> ''"""
        ).fetchall()]
    finally:
        conn.close()


def has_house_number(address):
    first = (address or "").split(",")[0].strip().split()
    return bool(first) and bool(re.match(r"^\d", first[0]))


def build_pools(rows, rng):
    ab, boston_zip, l3 = [], [], []

    for r in rows:
        if not address_is_resolvable(r["address"]):
            continue
        if not has_house_number(r["address"]):
            continue
        name = clean_person(r["owner_name"])
        has_zip5 = bool(zip5(r["zip_code"]))
        raw_zip = (r["zip_code"] or "").strip()

        if r["city"] == "NYC" and has_zip5 and name and len(name.split()) == 2:
            ab.append((r, name))
        if r["city"] == "Boston" and len(raw_zip) == 4 and name:
            boston_zip.append((r, name))
        if r["city"] in ("NYC", "Chicago") and not (r["owner_name"] or "").strip() and has_zip5:
            l3.append(r)

    rng.shuffle(ab)
    rng.shuffle(boston_zip)
    rng.shuffle(l3)
    return ab[:10], boston_zip[:5], l3[:10]


def extract(result):
    raw = result.raw if isinstance(result.raw, dict) else {}
    status = raw.get("Status") or raw.get("STATUS")
    first = last = None
    if isinstance(raw, dict):
        data = raw.get("Data") or raw.get("DATA") or {}
        records = data.get("RECORD") or data.get("Record") or [] if isinstance(data, dict) else []
        if isinstance(records, dict):
            records = [records]
        if records:
            first = records[0].get("FNAME") or records[0].get("FirstName")
            last = records[0].get("LNAME") or records[0].get("LastName")
    return status, first, last


def log(entry):
    with OUT_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def plan(ab, boston_zip, l3):
    jobs = []
    for r, name in ab:
        jobs.append(("A", r, name, name, zip5(r["zip_code"])))
        jobs.append(("B", r, name, split_for_arm(name, "inverted"), zip5(r["zip_code"])))
    for r, name in boston_zip:
        z = (r["zip_code"] or "").strip()
        inverted = split_for_arm(name, "inverted")
        jobs.append(("C4", r, name, inverted, z))
        jobs.append(("C5", r, name, inverted, z.zfill(5)))
    for r in l3:
        jobs.append(("D", r, None, None, zip5(r["zip_code"])))
    return jobs


async def run(jobs, max_calls):
    done = 0
    aborted = None
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text("", encoding="utf-8")

    for arm, row, owner, sent_name, zip_sent in jobs:
        if done >= max_calls:
            break
        started = datetime.now(timezone.utc).isoformat()
        t0 = time.monotonic()
        result = await phone_lookup_service._lookup_searchbug_nape(
            row["address"],
            row["city"],
            row["state"],
            owner_name=sent_name,
            zip_code=zip_sent,
        )
        latency = int((time.monotonic() - t0) * 1000)
        status, first, last = extract(result)
        entry = {
            "ts": started,
            "arm": arm,
            "lead_id": row["id"],
            "city": row["city"],
            "address": row["address"],
            "zip_sent": zip_sent,
            "owner_raw": owner,
            "name_sent": sent_name,
            "success": bool(result.success and result.phone),
            "phone_last4": (result.phone or "")[-4:] or None,
            "phone_type": result.phone_type,
            "connected": result.is_connected,
            "returned_first": first,
            "returned_last": last,
            "name_match": name_match(owner, first, last) if owner else None,
            "provider_status": status,
            "error": result.error,
            "latency_ms": latency,
            "cost_usd": PRICE,
        }
        log(entry)
        done += 1
        flag = "OK " if entry["success"] else "---"
        print(f"[{done:02d}/{max_calls}] {arm:<2} {flag} {row['city']:<8} "
              f"zip={zip_sent:<5} match={entry['name_match']} "
              f"err={str(result.error)[:45]}", flush=True)

        err = (result.error or "").lower()
        if any(x in err for x in ("not configured", "http 401", "http 402",
                                  "http 429", "insufficient", "quota")):
            aborted = result.error
            break
        await asyncio.sleep(0.4)

    try:
        await searchbug_metrics.flush_once()
    except Exception:
        pass
    await phone_lookup_service.aclose()
    return done, aborted


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-calls", type=int, default=40)
    args = ap.parse_args()

    # Cap absoluto: este harness e um artefacto de experimento, nao um job de producao.
    if args.max_calls > 50:
        print("ABORT: cap absoluto de 50 chamadas ($10,00). Editar o codigo para exceder.")
        return 2

    missing = [
        k for k in ("SEARCHBUG_API_KEY", "SEARCHBUG_ACCOUNT_CODE")
        if not getattr(settings, k, "")
    ]
    if missing:
        print("ABORT: credenciais em falta:", ", ".join(missing))
        return 2

    rng = random.Random(SEED)
    rows = load_rows()
    ab, boston_zip, l3 = build_pools(rows, rng)
    jobs = plan(ab, boston_zip, l3)

    print(f"universo lido: {len(rows)} leads")
    print(f"pares A/B (NYC): {len(ab)} -> {len(ab)*2} chamadas")
    print(f"pares ZIP (Boston): {len(boston_zip)} -> {len(boston_zip)*2} chamadas")
    print(f"L3 sem nome: {len(l3)} -> {len(l3)} chamadas")
    print(f"total planeado: {len(jobs)} chamadas = ${len(jobs)*PRICE:.2f}")
    print(f"cap: {args.max_calls} chamadas = ${args.max_calls*PRICE:.2f}")

    print("\n--- amostra A/B (NYC) ---")
    for r, name in ab:
        print(f"  {name!r:<32} {r['address'][:38]!r:<42} zip={r['zip_code']}")

    print("\n--- amostra C (Boston, ZIP 4->5) ---")
    for r, name in boston_zip:
        print(f"  {name!r:<32} {r['address'][:32]!r:<36} zip={r['zip_code']!r} -> {str(r['zip_code']).zfill(5)}")

    print("\n--- amostra D (sem nome) ---")
    for r in l3:
        print(f"  {r['city']:<8} {r['address'][:44]!r:<50} zip={r['zip_code']}")

    if args.dry_run:
        print("\nDRY RUN — nenhuma chamada feita.")
        return 0

    print("\n--- execucao ---")
    done, aborted = await run(jobs, args.max_calls)
    print(f"\nchamadas: {done} · custo estimado: ${done*PRICE:.2f}")
    if aborted:
        print(f"ABORTADO: {aborted}")
    print(f"resultados: {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

"""One-off: normaliza moradas de Boston e recupera owners do parcel dataset.

Read-only na fonte (CKAN); escreve apenas em `leads` (address/zip/owner) e na
config de enriquecimento de Boston. Idempotente: pode correr mais de uma vez.
"""
from __future__ import annotations

import json
import sqlite3
import time

import httpx

from backend.services.boston_address import clean_boston_location
from backend.services.db import db_service, get_connection
from backend.services.enrichment import normalize_street, parse_address

CKAN = "https://data.boston.gov/api/3/action/datastore_search"
RESOURCE = "bdb17c2b-e9ab-44e4-a070-bf804a0e1a7f"
FIELDS = [
    "full_address",
    "OWNER",
    "ZIPCODE",
    "OWNER_MAIL_ADDRESS",
    "OWNER_MAIL_CS",
    "OWNER_MAIL_ZIPCODE",
]
PAGE = 5000


def _zip5(value) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    return digits[:5] if len(digits) >= 5 else ""


def fix_addresses(conn) -> dict:
    rows = [dict(r) for r in conn.execute(
        "SELECT id, address, zip_code FROM leads WHERE UPPER(TRIM(city))='BOSTON'"
    ).fetchall()]
    changed = 0
    conflicts = 0
    for row in rows:
        street, zc = clean_boston_location(row["address"], row["zip_code"])
        if not street or street == row["address"] and not (zc and zc != row["zip_code"]):
            continue
        try:
            conn.execute(
                "UPDATE leads SET address=?, zip_code=COALESCE(?, zip_code), "
                "updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (street, zc or row["zip_code"], row["id"]),
            )
            changed += 1
        except sqlite3.IntegrityError:
            conflicts += 1
        if changed and changed % 500 == 0:
            conn.commit()
    conn.commit()
    return {"total": len(rows), "changed": changed, "conflicts": conflicts}


def fetch_boston_owners() -> dict:
    """Índice (número, rua normalizada) -> [(owner, zip, mailing)].

    Constrói o índice página a página para não manter 168k registos em memória
    (o contentor de produção tem memória limitada e o script corre ao lado da
    app).
    """
    index: dict[tuple[str, str], list[tuple[str, str, str]]] = {}
    offset = 0
    total = None
    seen = 0
    with httpx.Client(timeout=120) as client:
        while total is None or offset < total:
            resp = client.get(
                CKAN,
                params={
                    "resource_id": RESOURCE,
                    "limit": PAGE,
                    "offset": offset,
                    "fields": ",".join(FIELDS),
                },
            )
            resp.raise_for_status()
            data = resp.json()
            if not data.get("success"):
                raise RuntimeError(str(data.get("error"))[:200])
            result = data["result"]
            total = int(result.get("total") or 0)
            chunk = result.get("records") or []
            for rec in chunk:
                owner = " ".join(str(rec.get("OWNER") or "").split()).strip()
                if not owner or owner.upper().startswith(("N/A", "UNKNOWN")):
                    continue
                parsed = parse_address(str(rec.get("full_address") or ""))
                if not parsed:
                    continue
                num, street = parsed
                key = (str(num).strip(), normalize_street(street))
                index.setdefault(key, []).append(
                    (
                        owner,
                        _zip5(rec.get("ZIPCODE")),
                        " ".join(
                            str(rec.get("OWNER_MAIL_ADDRESS") or "").split()
                        ).strip(),
                    )
                )
            seen += len(chunk)
            offset += PAGE
            print(f"[BOSTON] dataset {seen}/{total} (index {len(index)})", flush=True)
            if not chunk:
                break
    return {"records": seen, "keys": len(index), "index": index}


def apply_owners(conn, index: dict) -> dict:
    rows = [dict(r) for r in conn.execute(
        "SELECT id, address, zip_code FROM leads "
        "WHERE UPPER(TRIM(city))='BOSTON' AND COALESCE(TRIM(owner_name),'')=''"
    ).fetchall()]
    matched = 0
    updated = 0
    for row in rows:
        parsed = parse_address(row["address"] or "")
        if not parsed:
            continue
        num, street = parsed
        key = (str(num).strip(), normalize_street(street))
        candidates = index.get(key) or []
        if not candidates:
            continue
        matched += 1
        zc = _zip5(row["zip_code"])
        chosen = None
        if zc:
            chosen = next((c for c in candidates if c[1] == zc), None)
        if chosen is None and len(candidates) == 1:
            chosen = candidates[0]
        if chosen is None:
            continue
        owner, _zc, mailing = chosen
        conn.execute(
            "UPDATE leads SET owner_name=?, "
            "mailing_address=COALESCE(NULLIF(mailing_address,''), ?), "
            "updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (owner, mailing or None, row["id"]),
        )
        updated += 1
        if updated % 500 == 0:
            conn.commit()
    conn.commit()
    return {"leads_sem_owner": len(rows), "matched": matched, "updated": updated}


def main() -> int:
    t0 = time.perf_counter()
    conn = get_connection()
    try:
        addr = fix_addresses(conn)
        print("[BOSTON] addresses:", json.dumps(addr), flush=True)
        owners = fetch_boston_owners()
        print(
            "[BOSTON] owners index:",
            json.dumps({k: v for k, v in owners.items() if k != "index"}),
            flush=True,
        )
        res = apply_owners(conn, owners["index"])
        print("[BOSTON] owners:", json.dumps(res), flush=True)
    finally:
        conn.close()

    db_service._service.set_outbound_config("enrich_enabled", "1", city="BOSTON")
    print("[BOSTON] enrich_enabled=1", flush=True)
    print("[BOSTON] done in %.1fs" % (time.perf_counter() - t0), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

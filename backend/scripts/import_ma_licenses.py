"""Importa licenças de Massachusetts (HIC/CSL) para `contractor_entities`.

Fonte oficial:
* OPSI / DOL — export CSV do portal https://madpl.mylicense.com/Verification/
  (a própria página oferece "download a data file of your search results").
* API oficial (opcional) — https://licensing.api.secure.digital.mass.gov/api
  com header `X-API-Key`; o pedido de chave é feito em
  https://www.mass.gov/forms/request-to-access-the-ma-professional-licensing-api

O CSV do OPSI é manual; este script normaliza e faz upsert. Sem `--write` é
apenas dry-run. A API só é chamada com `--api-enrich` e chave no ambiente.

Uso:
    python -m backend.scripts.import_ma_licenses --csv opsI.csv
    python -m backend.scripts.import_ma_licenses --csv opsI.csv --write
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import re
import urllib.parse
import urllib.request

from backend.services.contractor_ingest import _record, record_entities

_API = "https://licensing.api.secure.digital.mass.gov/api/licenses/"


def _norm_header(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")


def _pick(row: dict, *names: str) -> str:
    for name in names:
        value = row.get(name)
        if value:
            return str(value).strip()
    return ""


def load_rows(path: str) -> tuple[list[dict], int]:
    records: list[dict] = []
    skipped = 0
    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            return [], 0
        mapping = {name: _norm_header(name) for name in reader.fieldnames}
        for raw in reader:
            row = {mapping[key]: value for key, value in raw.items() if key in mapping}
            license_number = _pick(
                row, "license_number", "license", "licensenumber", "license_no", "number"
            )
            business = _pick(row, "business_name", "company", "company_name", "dba")
            first = _pick(row, "first_name", "firstname")
            last = _pick(row, "last_name", "lastname", "surname")
            legal_name = business or " ".join(part for part in (first, last) if part)
            city = _pick(row, "city", "town", "city_town")
            state = _pick(row, "state", "state_code") or "MA"
            license_type = _pick(row, "license_type", "type", "profession")
            if not legal_name or not city:
                skipped += 1
                continue
            rec = _record(
                legal_name=legal_name,
                city=city.upper(),
                state=state.upper(),
                role="contractor",
                license=license_number or None,
                license_type=license_type or None,
                source="ma_licensing_csv",
                external_id=license_number or legal_name,
            )
            if rec:
                records.append(rec)
            else:
                skipped += 1
    return records, skipped


def _api_lookup(license_number: str, key: str) -> dict | None:
    request = urllib.request.Request(
        _API + urllib.parse.quote(license_number, safe=""),
        headers={"X-API-Key": key, "User-Agent": "MagicLeadsMAImport/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8", "ignore"))
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", required=True)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--api-enrich", action="store_true")
    parser.add_argument("--limit", type=int, default=5000)
    args = parser.parse_args()

    records, skipped = load_rows(args.csv)
    records = records[: max(1, args.limit)]
    print("ROWS", len(records), "SKIPPED", skipped)

    key = os.getenv("MA_LICENSING_API_KEY", "").strip()
    if args.api_enrich and key:
        enriched = 0
        for rec in records:
            number = rec.get("license")
            if not number:
                continue
            data = _api_lookup(number, key)
            if not data:
                continue
            rec["license_type"] = data.get("TypeName") or rec.get("license_type")
            if data.get("City"):
                rec["city"] = str(data["City"]).upper()
            enriched += 1
        print("API_ENRICHED", enriched)

    if not args.write:
        print("DRY_RUN: nada foi escrito. Use --write após aprovação.")
        for rec in records[:5]:
            print(" ", rec.get("legal_name"), "|", rec.get("city"), "|", rec.get("license_type"))
        return 0

    stats = asyncio.run(record_entities(records, max_records=len(records)))
    print("UPSERT", stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

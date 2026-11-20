#!/usr/bin/env python3
"""Backfill de ZIP nas oportunidades de Chicago (dry-run por defeito).

Uso:
  python -m backend.scripts.backfill_chicago_zip --dry-run
  python -m backend.scripts.backfill_chicago_zip --apply

Para cada oportunidade antiga:
1. tenta resolver o ZIP por coordenadas, usando o ID da violação guardado no
   histórico (`chi-violation-<id>`) para reler lat/lng da fonte;
2. se não houver coordenadas, tenta o endereço normalizado nos leads 311.

A origem fica sempre em `zip_source`. Nunca inventa um ZIP.
"""
from __future__ import annotations

import argparse
import json
import re
import time

from backend.services.db import get_connection
from backend.services.opportunity_workflow import opportunity_workflow
from backend.services.phase1_enrichment import socrata
from backend.services.zip_lookup import resolve_chicago_zip


def _violation_coordinates(history_json: str) -> tuple[object, object]:
    ids = re.findall(r"chi-violation-(\d+)", history_json or "")
    if not ids:
        return None, None
    try:
        rows = socrata(
            "chi_violations",
            {"$limit": 1, "$where": f"id='{ids[0]}'"},
        )
    except Exception:  # noqa: BLE001 - backfill não pode parar por uma linha
        return None, None
    if not rows:
        return None, None
    return rows[0].get("latitude"), rows[0].get("longitude")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Grava as alterações")
    parser.add_argument("--limit", type=int, default=0, help="0 = todas")
    parser.add_argument("--no-remote", action="store_true", help="Não consulta a fonte")
    args = parser.parse_args()

    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT id, address, city, zip_code, history_json
            FROM opportunity_workflow
            WHERE UPPER(TRIM(city)) = 'CHICAGO'
              AND LENGTH(TRIM(COALESCE(zip_code, ''))) < 5
            ORDER BY id
            """
        ).fetchall()
    finally:
        conn.close()
    if args.limit:
        rows = rows[: int(args.limit)]

    resolved = []
    unresolved = []
    cache: dict[str, tuple[object, object, str]] = {}
    for row in rows:
        address = str(row["address"] or "").strip().upper()
        lat = lng = None
        if not args.no_remote:
            if address not in cache:
                lat, lng = _violation_coordinates(row["history_json"])
                cache[address] = (lat, lng, "remote")
                time.sleep(0.05)
            lat, lng, _ = cache[address]
        zip_code, source = resolve_chicago_zip(
            address=row["address"], lat=lat, lng=lng
        )
        if zip_code:
            resolved.append((row["id"], zip_code, source))
            if args.apply:
                opportunity_workflow.update_enrichment(
                    row["id"], zip_code=zip_code, zip_source=source
                )
        else:
            unresolved.append(row["id"])

    print(
        json.dumps(
            {
                "apply": args.apply,
                "total": len(rows),
                "resolved": len(resolved),
                "unresolved": len(unresolved),
                "by_source": {
                    source: sum(
                        1 for _, _, item_source in resolved if item_source == source
                    )
                    for source in {item[2] for item in resolved}
                },
                "unresolved_ids": unresolved[:20],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

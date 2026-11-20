#!/usr/bin/env python3
"""Backfill de ZIP nas oportunidades de Chicago (dry-run por defeito).

Uso:
  python backend/scripts/backfill_chicago_zip.py --dry-run
  python backend/scripts/backfill_chicago_zip.py --apply

O coletor novo já preenche o ZIP em novas violações; este script serve para
reparar as linhas antigas. A origem fica em `zip_source`.
"""
from __future__ import annotations

import argparse
import json

from backend.services.db import get_connection
from backend.services.opportunity_workflow import opportunity_workflow
from backend.services.zip_lookup import resolve_chicago_zip


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Grava as alterações")
    parser.add_argument("--limit", type=int, default=0, help="0 = todas")
    args = parser.parse_args()

    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT id, address, city, zip_code
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
    for row in rows:
        zip_code, source = resolve_chicago_zip(address=row["address"])
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
                    source: sum(1 for _, _, item_source in resolved if item_source == source)
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

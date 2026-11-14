"""Ingestão da Fase 1 no staging (dados reais, limits pequenos).

Uso:

    ALLOW_STAGING_INGEST=1 LEADS_DB_PATH=<staging.db> \
      python scripts/ingest_phase1_staging.py --limit 20

Recusa correr sem as duas variáveis e recusa qualquer caminho dentro do repo de
produção. `--dry-run` busca e compõe os candidatos sem escrever na base.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

if os.getenv("ALLOW_STAGING_INGEST") != "1":
    raise SystemExit("Refusing to ingest: set ALLOW_STAGING_INGEST=1 for staging only")
if not os.getenv("LEADS_DB_PATH"):
    raise SystemExit("Refusing to ingest: set LEADS_DB_PATH to the staging database")
if "garimpador-leads" in str(Path(os.environ["LEADS_DB_PATH"]).resolve()):
    raise SystemExit("Refusing to ingest a path inside the production repository")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services.db import init_db  # noqa: E402
from backend.services.phase1_enrichment import phase1_enrichment  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 1 staging enrichment")
    parser.add_argument("--limit", type=int, default=20, help="rows per source (small on purpose)")
    parser.add_argument("--permit-rows", type=int, default=400, help="permit scan window")
    parser.add_argument("--dry-run", action="store_true", help="fetch and compose, do not write")
    args = parser.parse_args()

    limit = max(1, min(args.limit, 100))
    print(f"Phase 1 ingestion -> {os.environ['LEADS_DB_PATH']} (limit={limit})")
    candidates = phase1_enrichment.build_candidates(
        hpd_complaints=limit,
        hpd_deadlines=limit,
        ecb=limit * 2,
        chi_violations=limit,
        permit_rows=max(50, args.permit_rows),
    )
    print(f"candidates: {len(candidates)}")
    for candidate in candidates:
        print(
            "  -",
            candidate.get("city"),
            candidate.get("address"),
            "| category:",
            candidate.get("category"),
            "| deadline:",
            candidate.get("compliance_deadline"),
            "| fine:",
            candidate.get("fine_balance") or 0,
            "| value:",
            candidate.get("job_value"),
            "| source:",
            candidate.get("value_source"),
        )
    if args.dry_run:
        print(json.dumps(candidates[:2], indent=2, ensure_ascii=False, default=str))
        return

    init_db()
    stats = phase1_enrichment.ingest(candidates=candidates)
    print("Result:", json.dumps(stats, ensure_ascii=False))


if __name__ == "__main__":
    main()

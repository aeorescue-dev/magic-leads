"""Reclassifica a fila preventiva do staging (uma vez, após mudar keywords).

    ALLOW_STAGING_RECLASSIFY=1 LEADS_DB_PATH=<staging.db> \
      python scripts/reclassify_staging_opportunities.py [--dry-run]

Recusa correr sem as variáveis e recusa o repositório de produção.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

if os.getenv("ALLOW_STAGING_RECLASSIFY") != "1":
    raise SystemExit("Refusing to reclassify: set ALLOW_STAGING_RECLASSIFY=1")
if not os.getenv("LEADS_DB_PATH"):
    raise SystemExit("Refusing to reclassify: set LEADS_DB_PATH to the staging database")
if "garimpador-leads" in str(Path(os.environ["LEADS_DB_PATH"]).resolve()):
    raise SystemExit("Refusing to reclassify a path inside the production repository")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services.phase1_enrichment import phase1_enrichment  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Reclassify staging opportunities")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    result = phase1_enrichment.reclassify_existing(dry_run=args.dry_run)
    print(result)


if __name__ == "__main__":
    main()

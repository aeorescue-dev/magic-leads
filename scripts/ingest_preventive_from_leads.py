"""Ingestão preventiva a partir dos leads (staging).

Uso (NUNCA em produção):

    ALLOW_STAGING_INGEST=1 LEADS_DB_PATH=/caminho/staging/leads.db \
      python scripts/ingest_preventive_from_leads.py

O script recusa correr sem as variáveis e recusa caminhos do repositório de
produção. Em produção, a mesma função (`preventive_ingestion.ingest_from_leads`)
deve ser chamada depois do ciclo de ingestão.
"""
from __future__ import annotations

import argparse
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

from backend.services.preventive_ingestion import preventive_ingestion  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingestão preventiva (staging)")
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument(
        "--open-requests-only",
        action="store_true",
        help="Ingere apenas signal_type=open_request (exclui obrigações legais)",
    )
    args = parser.parse_args()

    stats = preventive_ingestion.ingest_from_leads(
        limit=args.limit,
        include_legal_obligation=not args.open_requests_only,
    )
    print(
        "Ingestão preventiva: "
        f"{stats['scanned']} analisados, "
        f"{stats['ingested']} criados, "
        f"{stats['skipped_duplicate']} já existentes"
    )
    if stats["ids"]:
        print("Novos IDs:", ", ".join(str(item) for item in stats["ids"]))


if __name__ == "__main__":
    main()

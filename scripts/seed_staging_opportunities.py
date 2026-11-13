"""Seed de oportunidades preventivas para testes de staging.

Uso (NUNCA em produção):

    ALLOW_STAGING_SEED=1 LEADS_DB_PATH=/caminho/staging/leads.db \
      python scripts/seed_staging_opportunities.py

O script recusa correr sem ALLOW_STAGING_SEED=1 e sem LEADS_DB_PATH.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

if os.getenv("ALLOW_STAGING_SEED") != "1":
    raise SystemExit("Refusing to seed: set ALLOW_STAGING_SEED=1 for staging only")
if not os.getenv("LEADS_DB_PATH"):
    raise SystemExit("Refusing to seed: set LEADS_DB_PATH to the staging database")
if "garimpador-leads" in str(Path(os.environ["LEADS_DB_PATH"]).resolve()):
    raise SystemExit("Refusing to seed a path inside the production repository")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services.opportunity_workflow import opportunity_workflow  # noqa: E402

SAMPLES = [
    {
        "source_record_id": "staging-preventive-heat-1",
        "address": "3430 BROADWAY",
        "city": "NYC",
        "state": "NY",
        "zip_code": "10031",
        "bbl": "1020710061",
        "category": "Heating",
        "severity": "immediate",
        "compliance_deadline": None,
    },
    {
        "source_record_id": "staging-preventive-mold-1",
        "address": "111 E 21ST ST",
        "city": "NYC",
        "state": "NY",
        "zip_code": "11226",
        "bbl": "3050820084",
        "category": "Mold",
        "severity": "high",
    },
    {
        "source_record_id": "staging-preventive-plumbing-1",
        "address": "2419 W 60TH ST",
        "city": "Chicago",
        "state": "IL",
        "zip_code": "60629",
        "category": "Plumbing",
        "severity": "high",
    },
    {
        "source_record_id": "staging-preventive-structure-1",
        "address": "7310 LAKEWOOD BLVD",
        "city": "Dallas",
        "state": "TX",
        "zip_code": "75214",
        "category": "Structure",
        "severity": "medium",
    },
    {
        "source_record_id": "staging-preventive-unsanitary-1",
        "address": "412 E 8TH ST",
        "city": "Boston",
        "state": "MA",
        "zip_code": "02127",
        "category": "Unsanitary",
        "severity": "high",
    },
    {
        "source_record_id": "staging-preventive-electric-1",
        "address": "2345 VALENTINE AVE",
        "city": "NYC",
        "state": "NY",
        "zip_code": "10458",
        "bbl": "2032450042",
        "category": "Electrical",
        "severity": "high",
    },
]


def main() -> None:
    print(f"Seeding {len(SAMPLES)} opportunities into {os.environ['LEADS_DB_PATH']}")
    for sample in SAMPLES:
        row = opportunity_workflow.create_opportunity(
            source_kind="preventive",
            source_type="pre_inspection",
            signal_type="open_request",
            **sample,
        )
        print(f"  #{row['id']} {row['city']} {row['category']} {sample['address']}")


if __name__ == "__main__":
    main()

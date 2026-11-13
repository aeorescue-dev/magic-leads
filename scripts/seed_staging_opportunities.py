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
from backend.services import security  # noqa: E402
from backend.services.db import db_service  # noqa: E402
from backend.models.schemas import (  # noqa: E402
    EnrichedLead,
    IssueCategory,
    SourceType,
    UrgencyLevel,
)
from datetime import datetime, timedelta, timezone  # noqa: E402

STAGING_EMAIL = os.getenv("STAGING_USER_EMAIL", "staging@magicleads.app")
STAGING_PASSWORD = os.getenv("STAGING_USER_PASSWORD", "Staging123!")

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


RICH_CONTEXT = {
    "staging-preventive-heat-1": {
        "description": "Sem aquecimento e água quente em todo o edifício desde a madrugada.",
        "owner_name": "Hamilton Heights Holdings",
        "owner_type": "Empresa",
        "inspection_status": "possible",
        "received_at": "2026-11-12T08:10:00",
    },
    "staging-preventive-mold-1": {
        "description": "Infiltração no teto do banheiro com mofo visível e odor forte.",
        "owner_name": "E 21st Realty",
        "owner_type": "Empresa",
        "inspection_status": "possible",
        "received_at": "2026-11-12T07:40:00",
    },
    "staging-preventive-plumbing-1": {
        "description": "Vazamento recorrente na coluna de água do banheiro; vizinho reportou.",
        "owner_name": "W 60th Property Group",
        "owner_type": "Empresa",
        "inspection_status": "possible",
        "received_at": "2026-11-11T16:20:00",
    },
    "staging-preventive-structure-1": {
        "description": "Fachada e calçada em mau estado; risco de notificação de conservação.",
        "owner_name": "Lakewood Holdings",
        "owner_type": "Empresa",
        "inspection_status": "possible",
        "received_at": "2026-11-10T11:05:00",
    },
    "staging-preventive-unsanitary-1": {
        "description": "Acúmulo de lixo e infiltração na área comum do edifício.",
        "owner_name": "South Boston Partners",
        "owner_type": "Empresa",
        "inspection_status": "possible",
        "received_at": "2026-11-09T09:30:00",
    },
    "staging-preventive-electric-1": {
        "description": "Fiação exposta e falta de energia em duas unidades do 2.º andar.",
        "owner_name": "Fordham 188 LLC",
        "owner_type": "Empresa",
        "inspection_status": "possible",
        "received_at": "2026-11-12T06:15:00",
    },
}
for _sample in SAMPLES:
    _sample.update(RICH_CONTEXT.get(_sample["source_record_id"], {}))


def seed_reactive_leads() -> None:
    now = datetime.now(timezone.utc)
    rows = [
        EnrichedLead(
            external_id="staging-reactive-heat-1",
            source_type=SourceType.HPD_VIOLATION,
            address="1420 CLAREMONT PKWY",
            city="NYC",
            state="NY",
            zip_code="10456",
            lat=None,
            lng=None,
            county="BRONX",
            issue_category=IssueCategory.HEATING,
            issue_description="Falta de aquecimento reiterada; correção exigida pelo código de habitação.",
            urgency_level=UrgencyLevel.HIGH,
            owner_name="Claremont Housing",
            owner_phone="+17185550111",
            owner_email=None,
            mailing_address="1420 Claremont Pkwy, Bronx, NY 10456",
            date_reported=now - timedelta(days=1),
            image_url=None,
            source_url=None,
            case_status="Open",
            sla_target_dt=(now + timedelta(days=3)).date().isoformat(),
        ),
        EnrichedLead(
            external_id="staging-reactive-elevator-1",
            source_type=SourceType.DOB_VIOLATION,
            address="620 W 141ST ST",
            city="NYC",
            state="NY",
            zip_code="10031",
            lat=None,
            lng=None,
            county="NEW YORK",
            issue_category=IssueCategory.ELEVATOR,
            issue_description="Elevador de serviço fora de operação; risco imediato e audiência marcada.",
            urgency_level=UrgencyLevel.HIGH,
            owner_name="Hamilton Heights Holdings",
            owner_phone="+17185550112",
            owner_email=None,
            mailing_address="620 W 141st St, New York, NY 10031",
            date_reported=now - timedelta(days=2),
            image_url=None,
            source_url=None,
            case_status="Open",
        ),
        EnrichedLead(
            external_id="staging-reactive-plumbing-1",
            source_type=SourceType.SERVICE_311,
            address="2419 W 60TH ST",
            city="Chicago",
            state="IL",
            zip_code="60629",
            lat=None,
            lng=None,
            county="COOK",
            issue_category=IssueCategory.PLUMBING,
            issue_description="Vazamento de esgoto no subsolo; correção urgente para evitar interdição.",
            urgency_level=UrgencyLevel.HIGH,
            owner_name="W 60th Property Group",
            owner_phone="+13125550113",
            owner_email=None,
            mailing_address="2419 W 60th St, Chicago, IL 60629",
            date_reported=now - timedelta(hours=8),
            image_url=None,
            source_url=None,
            case_status="Open",
        ),
        EnrichedLead(
            external_id="staging-reactive-structure-1",
            source_type=SourceType.BUILDING_PERMIT,
            address="5908 PRESTON RD",
            city="Dallas",
            state="TX",
            zip_code="75230",
            lat=None,
            lng=None,
            county="DALLAS",
            issue_category=IssueCategory.STRUCTURE,
            issue_description="Reforma interior de cozinha e banheiros; execução pode começar imediatamente.",
            urgency_level=UrgencyLevel.MEDIUM,
            owner_name="Preston Hollow Builders",
            owner_phone="+12145550114",
            owner_email=None,
            mailing_address="5908 Preston Rd, Dallas, TX 75230",
            date_reported=now - timedelta(days=3),
            image_url=None,
            source_url=None,
            case_status="Issued",
        ),
    ]
    for lead in rows:
        db_service._service.insert_lead_new(lead)
        print(f"  reactive lead {lead.external_id} {lead.address}")


def main() -> None:
    print(f"Seeding {len(SAMPLES)} opportunities into {os.environ['LEADS_DB_PATH']}")
    svc = db_service._service
    user = svc.get_user_by_email(STAGING_EMAIL.lower())
    if user is None:
        user = svc.create_user(
            STAGING_EMAIL.lower(),
            security.hash_password(STAGING_PASSWORD),
            "Staging Contractor",
            plan="pro",
            subscription_status="active",
        )
    if user:
        svc.extend_access(user["id"], days=30)
        svc.set_user_interests(
            user["id"],
            [
                "Roof", "Structure", "Plumbing", "Grass", "Paint",
                "Permit_Rejected", "Heating", "Electrical", "Elevator",
                "Gas", "Rodent", "Mold", "Lead", "Unsanitary",
                "Door_Window", "Debris",
            ],
        )
        print(f"Staging login: {STAGING_EMAIL} / {STAGING_PASSWORD}")
    for sample in SAMPLES:
        row = opportunity_workflow.create_opportunity(
            source_kind="preventive",
            source_type="pre_inspection",
            signal_type="open_request",
            **sample,
        )
        print(f"  #{row['id']} {row['city']} {row['category']} {sample['address']}")

    seed_reactive_leads()


if __name__ == "__main__":
    main()

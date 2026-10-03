"""Regressão: mailing_address deve persistir corretamente no insert_lead.

Causa raiz original: `EnrichedLead` (Pydantic) não declarava o campo
`mailing_address`, pelo que o valor era descartado antes de chegar ao INSERT
mesmo que a coluna e o `getattr(...)` existissem no `insert_lead_new`.
"""
import uuid
from datetime import datetime

from backend.models.schemas import (
    EnrichedLead,
    IssueCategory,
    SourceType,
    UrgencyLevel,
)
from backend.services.db import db_service


def _make_lead(mailing_address=None, street="TEST STREET") -> int:
    """Insere um lead e devolve o id.

    O endereço tem de ser único por teste: `insert_lead_new` faz
    ON CONFLICT(address, city), por isso reutilizar o mesmo endereço
    transformaria o segundo teste num UPDATE e Mascaria o bug.
    """
    uniq = uuid.uuid4().hex[:8]
    payload = EnrichedLead(
        external_id=f"pytest-mailing-{uniq}",
        source_type=SourceType.SERVICE_311,
        address=f"{uniq} {street}",
        city="BROOKLYN",
        state="NY",
        zip_code="11201",
        lat=None,
        lng=None,
        county="KINGS",
        issue_category=IssueCategory.ROOF,
        issue_description="Test mailing address persistence",
        urgency_level=UrgencyLevel.HIGH,
        owner_name="TEST OWNER",
        owner_phone="(718) 555-0100",
        owner_email=None,
        mailing_address=mailing_address,
        date_reported=datetime(2026, 1, 15, 12, 0, 0),
        image_url=None,
        source_url=None,
    )
    row = db_service._service.insert_lead_new(payload)
    assert row is not None, "insert_lead_new devolveu None"
    return row["id"]


def test_mailing_address_persists_on_insert():
    """mailing_address inserido deve ser recuperado igual."""
    expected = "456 CORP BLVD, NYC, NY 10002"
    lead_id = _make_lead(mailing_address=expected)

    row = db_service._service.get_lead_by_id(lead_id)
    assert row is not None, "Lead não encontrado após insert"
    assert row["mailing_address"] == expected, \
        f"mailing_address não persistiu: {row.get('mailing_address')!r}"


def test_mailing_address_none_when_not_provided():
    """Se mailing_address não for fornecido, deve ficar NULL."""
    lead_id = _make_lead(mailing_address=None)

    row = db_service._service.get_lead_by_id(lead_id)
    assert row is not None
    assert not row["mailing_address"], \
        f"mailing_address deveria ser None/vazio: {row.get('mailing_address')!r}"


def test_enriched_lead_model_exposes_mailing_address():
    """O schema Pydantic tem de declarar o campo (causa raiz do bug)."""
    assert "mailing_address" in EnrichedLead.model_fields, \
        "EnrichedLead.model_fields não declara mailing_address"

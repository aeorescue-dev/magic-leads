"""Contrato HTTP: o feed tem de publicar o verdito de entrega da Regra A.

Regressao que motivou este ficheiro: o backend passava a calcular `charged`
em `lead_rules.classify()`, mas `_to_lead_response()` NAO o punha no
`LeadResponse`. Como `/api/leads/{id}` tem `response_model=LeadResponse`, o
Pydantic descartava o campo e o browser recebia um lead pago com
`corporate=false` e sem `charged`.

Consequencia no browser: `isFreeLead()` caia no fallback `!!corporate`, o card
mostrava "1 credito" e a reserva voltava a ser BLOQUEADA quando a cota diaria
estava esgotada -- exactamente o bug que a Regra A veio remover. Passava
igualmente no backend (que cobrava certo) e so rebentava no browser.

Estes testes fixam o contrato na fronteira HTTP. As expectativas sao derivadas
de `classify()` para nao duplicar a regra: o que se verifica e que o campo
EXISTE e que bate certo com a regra, nao um segundo hardcode dela.
"""
from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

import backend.main as main_module
from backend.main import _hash_token, app
from backend.models.schemas import (
    EnrichedLead,
    IssueCategory,
    SourceType,
    UrgencyLevel,
)
from backend.services.db import db_service
from backend.services.lead_rules import classify

EMAIL = "pytest-feed-flags@magicleads.app"
TOKEN = "pytest-feed-flags-token"

_EXT = {"n": 0}

# owner_name, owner_phone, mailing_address
CASES = [
    # nome + telefone -> sucesso total, pago
    ("JOHN DOE", "(718) 555-0200", "123 TEST AVE, BROOKLYN, NY 11201"),
    # nome sem telefone e sem morada -> entregue de graca
    ("JOHN DOE", None, None),
    # telefone sem nome -> entregue de graca
    (None, "(718) 555-0200", None),
    # corporativo (nome + morada, sem telefone) -> 0 creditos
    ("65 MS LLC", None, "PO BOX 9, NEW YORK, NY 10001"),
    # lead vazio -> entregue de graca
    (None, None, None),
]


def _make_lead(owner_name, owner_phone, mailing_address) -> int:
    _EXT["n"] += 1
    payload = EnrichedLead(
        external_id=f"pytest-feed-flags-{_EXT['n']}",
        source_type=SourceType.SERVICE_311,
        address=f"{_EXT['n']} TEST STREET",
        city="BROOKLYN",
        state="NY",
        zip_code="11201",
        lat=None,
        lng=None,
        county="KINGS",
        issue_category=IssueCategory.ROOF,
        issue_description="Contrato de flags de entrega",
        urgency_level=UrgencyLevel.HIGH,
        owner_name=owner_name,
        owner_phone=owner_phone,
        owner_email=None,
        mailing_address=mailing_address,
        date_reported=datetime(2026, 1, 15, 12, 0, 0),
        image_url=None,
        source_url=None,
    )
    row = db_service._service.insert_lead_new(payload)
    assert row is not None, "insert_lead_new devolveu None (lead ja existiria?)"
    return row["id"]


class _NoPhone:
    async def lookup_phone(self, *args, **kwargs):
        class R:
            success = False
            phone = None
            error = "NORESULTS"

        return R()


class _NoName:
    async def enrich(self, *args, **kwargs):
        return None


@pytest.fixture(scope="module")
def user_and_client():
    svc = db_service._service
    user = svc.get_user_by_email(EMAIL) or svc.create_user(
        EMAIL, "pytest-hash-not-used", "Pytest Feed Flags", plan="pro",
        subscription_status="active",
    )
    assert user is not None
    user_id = user["id"]
    svc.create_user_session(user_id, _hash_token(TOKEN), "Pytest", None)
    svc.extend_access(user_id, days=7)
    return TestClient(app), {"Authorization": f"Bearer {TOKEN}"}, user_id


@pytest.fixture
def no_external_data(monkeypatch):
    monkeypatch.setattr(main_module, "searchbug_service", _NoPhone())
    monkeypatch.setattr(main_module, "owner_enrichment", _NoName())


@pytest.mark.parametrize("owner_name,owner_phone,mailing_address", CASES)
def test_single_lead_publishes_delivery_flags(
    user_and_client, no_external_data, owner_name, owner_phone, mailing_address
):
    """`charged`, `complete_delivery` e `incomplete_delivery` tem de existir."""
    client, headers, _ = user_and_client
    lead_id = _make_lead(owner_name, owner_phone, mailing_address)

    r = client.get(f"/api/leads/{lead_id}", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()

    for key in ("charged", "complete_delivery", "incomplete_delivery", "corporate"):
        assert key in body, f"campo {key!r} ausente no payload do lead"

    expected = classify(
        {
            "owner_name": owner_name,
            "owner_phone": owner_phone,
            "mailing_address": mailing_address,
            "address": f"{_EXT['n']} TEST STREET",
        }
    )
    assert body["charged"] is expected["charged"]
    assert body["complete_delivery"] is expected["complete_delivery"]
    assert body["incomplete_delivery"] is expected["incomplete_delivery"]


@pytest.mark.parametrize("owner_name,owner_phone,mailing_address", CASES)
def test_feed_list_publishes_delivery_flags(
    user_and_client, no_external_data, owner_name, owner_phone, mailing_address
):
    """A lista do feed tem de trazer os mesmos flags (e nao so o detalhe)."""
    client, headers, _ = user_and_client
    lead_id = _make_lead(owner_name, owner_phone, mailing_address)

    r = client.get("/api/leads?city=BROOKLYN&per_page=200", headers=headers)
    assert r.status_code == 200, r.text
    leads = r.json()["leads"]

    row = next((x for x in leads if x["id"] == str(lead_id)), None)
    assert row is not None, f"lead {lead_id} nao apareceu no feed"
    assert "charged" in row, "campo 'charged' ausente na lista do feed"
    assert isinstance(row["charged"], bool)


def test_paid_lead_still_publishes_charged_while_masked(user_and_client, no_external_data):
    """Caso que rebentou: mascarado, o preco tem de continuar conhecido.

    A UI precisa de mostrar o preco ANTES de reservar e so tem o veredicto:
    `owner_name`/`owner_phone` chegam a None sem reveal ativo.
    """
    client, headers, _ = user_and_client
    lead_id = _make_lead("JOHN DOE", "(718) 555-0200", "123 TEST AVE, BROOKLYN, NY 11201")

    r = client.get(f"/api/leads/{lead_id}", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["revealed"] is False
    assert body["owner_name"] is None, "owner_name deveria estar mascarado no feed"
    assert body["owner_phone"] is None, "owner_phone deveria estar mascarado no feed"
    # ... e mesmo assim o preco tem de ser conhecido
    assert body["charged"] is True
    assert body["complete_delivery"] is True


def test_free_lead_is_not_marked_paid(user_and_client, no_external_data):
    """Guarda contra regressao de preco: nada sem telefone pode ser cobrado."""
    client, headers, _ = user_and_client
    lead_id = _make_lead("JOHN DOE", None, None)

    r = client.get(f"/api/leads/{lead_id}", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["charged"] is False
    assert body["complete_delivery"] is False
    assert body["incomplete_delivery"] is True

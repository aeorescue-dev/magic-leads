"""Regressão: a reserva NUNCA pode debitar crédito com dados do dono incompletos.

Histórico do bug: POST /api/leads/{id}/reserve com consentimento chamava
`reveal_lead()` PRIMEIRO (que incrementava `user_daily_stats.leads_used` e
reservava o lead) e só DEPOIS tentava estornar via `process_refund()` quando o
enriquecimento falhava. Duas consequências graves:

1. O telefone continuava a ser OPCIONAL: um lead sem `owner_phone` (por exemplo
   quando o Searchbug responde NORESULTS) era cobrado na mesma mesma.
2. O estorno era best-effort e limitado a 2/dia, por isso o cliente ficava
   com o crédito perdido para sempre e ainda assim via um 200 com o lead marcado
   como reservado.

Invariantes fixados aqui (fail closed, "debit last"):
1. Sem `owner_name` OU sem `owner_phone` => HTTP 422, `leads_used` inalterado e
   o lead continua `available` (nada foi reservado).
2. Com `owner_name` E `owner_phone` => HTTP 200, `leads_used` +1 e lead reservado.
3. `precheck_reveal()` é uma pré-validação SEM efeito colateral: não consome cota
   e não altera o status do lead.
4. O re-clique (reveal ativo no mesmo dia) não consome um segundo crédito.
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

EMAIL = "pytest-reserve-atomic@magicleads.app"

# Contador determinístico para external_id único por teste.
_EXT = {"n": 0}


def _make_lead(owner_name=None, owner_phone=None, mailing_address="123 TEST AVE, BROOKLYN, NY 11201") -> int:
    """Insere um lead 311 minimalista e devolve o id."""
    _EXT["n"] += 1
    payload = EnrichedLead(
        external_id=f"pytest-reserve-atomic-{_EXT['n']}",
        source_type=SourceType.SERVICE_311,
        address=f"{_EXT['n']} TEST STREET",
        city="BROOKLYN",
        state="NY",
        zip_code="11201",
        lat=None,
        lng=None,
        county="KINGS",
        issue_category=IssueCategory.ROOF,
        issue_description="Building collapse - teste de quota",
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
    assert row is not None, "insert_lead_new devolveu None (lead já existiria?)"
    return row["id"]


class _NoPhone:
    """Searchbug em modo NORESULTS (o caso real que causava a cobrança indevida)."""

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
    """Cria utilizador + sessão diretamente na BD de teste.

    Não usa POST /api/auth/register de propósito: esse endpoint tem rate limit
    (3/min por IP) e o teste ficaria flaky dependendo dos outros módulos.
    """
    svc = db_service._service
    user = svc.get_user_by_email(EMAIL) or svc.create_user(
        EMAIL, "pytest-hash-not-used", "Pytest Reserve", plan="pro",
        subscription_status="active",
    )
    assert user is not None, "não foi possível criar o utilizador de teste"
    user_id = user["id"]

    token = "pytest-reserve-atomic-token"
    svc.create_user_session(user_id, _hash_token(token), "Pytest", None)
    # Garante can_access para o endpoint de reserva passar na validação de plano.
    svc.extend_access(user_id, days=7)

    return TestClient(app), {"Authorization": f"Bearer {token}"}, user_id


@pytest.fixture
def no_external_data(monkeypatch):
    """Enriquecimento externo sempre vazio => nunca preenche nome/telefone."""
    monkeypatch.setattr(main_module, "searchbug_service", _NoPhone())
    monkeypatch.setattr(main_module, "owner_enrichment", _NoName())


def _used(user_id: int) -> int:
    return int(db_service._service.get_daily_leads_used(user_id).get("used") or 0)


def test_precheck_reveal_has_no_side_effects(user_and_client, no_external_data):
    """precheck_reveal não consome cota nem reserva o lead."""
    _, _, user_id = user_and_client
    lead_id = _make_lead(owner_name=None, owner_phone=None)

    before_used = _used(user_id)
    before = db_service._service.get_lead_by_id(lead_id)

    res = db_service._service.precheck_reveal(user_id, lead_id)
    assert res["status"] == "ok", res
    assert res["already_revealed"] is False

    after_used = _used(user_id)
    after = db_service._service.get_lead_by_id(lead_id)

    assert after_used == before_used, "precheck_reveal consumiu cota!"
    assert after["lead_status"] == before["lead_status"], "precheck_reveal alterou o status do lead"
    assert after["reserved_until"] == before["reserved_until"], "precheck_reveal reservou o lead"


def test_no_credit_debited_when_owner_data_incomplete(user_and_client, no_external_data):
    """Sem nome e sem telefone/morada => 422 e ZERO créditos consumidos."""
    client, headers, user_id = user_and_client
    lead_id = _make_lead(owner_name=None, owner_phone=None, mailing_address=None)

    before_used = _used(user_id)

    r = client.post(
        f"/api/leads/{lead_id}/reserve",
        headers=headers,
        json={"minutes": 60, "consent": True, "idempotency": f"pytest-422-{lead_id}"},
    )

    assert r.status_code == 422, f"devolveu {r.status_code}: {r.text}"
    body = r.json()
    assert body["error"] == "incomplete_lead_data", body
    assert body["charged"] is False, body
    assert body["reserved"] is False, body
    # Regra A exige owner_name E (owner_phone OU mailing_address)
    assert set(body["params"]["missing"]) == {"owner_name", "owner_phone_or_mailing_address"}, body

    assert _used(user_id) == before_used, (
        f"BUG: crédito foi debitado apesar do 422 "
        f"({before_used} -> {_used(user_id)})"
    )

    lead = db_service._service.get_lead_by_id(lead_id)
    assert lead["lead_status"] == "available", "lead foi reservado apesar do 422"
    assert lead["reserved_until"] is None, "lead foi reservado apesar do 422"


def test_no_credit_debited_when_name_missing_but_mailing_present(user_and_client, no_external_data):
    """Morada presente mas nome ausente => 422 e ZERO créditos consumidos."""
    client, headers, user_id = user_and_client
    lead_id = _make_lead(owner_name=None, owner_phone=None, mailing_address="123 CORP AVE")

    before_used = _used(user_id)

    r = client.post(
        f"/api/leads/{lead_id}/reserve",
        headers=headers,
        json={"minutes": 60, "consent": True, "idempotency": f"pytest-422c-{lead_id}"},
    )

    assert r.status_code == 422, f"devolveu {r.status_code}: {r.text}"
    body = r.json()
    assert body["error"] == "incomplete_lead_data", body
    assert body["charged"] is False, body
    assert body["reserved"] is False, body
    # Apenas owner_name está em falta (mailing_address está presente)
    assert set(body["params"]["missing"]) == {"owner_name"}, body

    assert _used(user_id) == before_used, (
        f"BUG: crédito foi debitado apesar do 422 "
        f"({before_used} -> {_used(user_id)})"
    )

    lead = db_service._service.get_lead_by_id(lead_id)
    assert lead["lead_status"] == "available", "lead foi reservado apesar do 422"
    assert lead["reserved_until"] is None, "lead foi reservado apesar do 422"


def test_corporate_lead_without_phone_is_allowed(user_and_client, no_external_data):
    """Lead corporativo (nome + morada, sem telefone) => 200, reserva grátis (0 créditos)."""
    client, headers, user_id = user_and_client
    lead_id = _make_lead(owner_name="JOHN DOE", owner_phone=None, mailing_address="123 CORP AVE")

    before_used = _used(user_id)

    r = client.post(
        f"/api/leads/{lead_id}/reserve",
        headers=headers,
        json={"minutes": 60, "consent": True, "idempotency": f"pytest-corp-{lead_id}"},
    )

    assert r.status_code == 200, f"devolveu {r.status_code}: {r.text}"
    body = r.json()
    assert body["revealed"] is True, body
    assert body["owner"]["name"] == "JOHN DOE", body
    assert body.get("corporate") is True, body
    assert body["used"] == 0, body
    assert body["limit"] == 10
    assert body["remaining"] == 10

    assert _used(user_id) == before_used, "BUG: crédito foi debitado em lead corporativo"
    lead = db_service._service.get_lead_by_id(lead_id)
    assert lead["lead_status"] == "reserved"
    assert lead["owner_name"] == "JOHN DOE"
    assert lead["owner_phone"] is None


def test_credit_debited_once_when_data_complete(user_and_client, no_external_data):
    """Nome + telefone presentes => 200, +1 crédito e lead reservado."""
    client, headers, user_id = user_and_client
    lead_id = _make_lead(owner_name="JANE ROE", owner_phone="(718) 555-0100")

    before_used = _used(user_id)

    r = client.post(
        f"/api/leads/{lead_id}/reserve",
        headers=headers,
        json={"minutes": 60, "consent": True, "idempotency": f"pytest-ok-{lead_id}"},
    )

    assert r.status_code == 200, f"devolveu {r.status_code}: {r.text}"
    body = r.json()
    assert body["revealed"] is True, body
    assert body["owner"]["name"] == "JANE ROE", body
    assert body["owner"]["phone"] == "(718) 555-0100", body

    assert _used(user_id) == before_used + 1, "não debitou exatamente 1 crédito"

    lead = db_service._service.get_lead_by_id(lead_id)
    assert lead["lead_status"] == "reserved", lead["lead_status"]
    assert lead["reserved_by"] == user_id


def test_reclick_does_not_debit_twice(user_and_client, no_external_data):
    """Re-clique no mesmo lead com reveal ativo não consome um 2º crédito."""
    client, headers, user_id = user_and_client
    lead_id = _make_lead(owner_name="CARL OTTO", owner_phone="(718) 555-0200")

    r1 = client.post(
        f"/api/leads/{lead_id}/reserve",
        headers=headers,
        json={"minutes": 60, "consent": True, "idempotency": f"pytest-idem-1-{lead_id}"},
    )
    assert r1.status_code == 200, r1.text
    after_first = _used(user_id)

    r2 = client.post(
        f"/api/leads/{lead_id}/reserve",
        headers=headers,
        json={"minutes": 60, "consent": True, "idempotency": f"pytest-idem-2-{lead_id}"},
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["counted_again"] is False, r2.json()
    assert _used(user_id) == after_first, "re-clique consumiu um segundo crédito"


def test_failed_reserve_does_not_consume_daily_quota(user_and_client, no_external_data):
    """Um 422 não pode 'gastar' a cota: o contador de créditos fica intacto."""
    client, headers, user_id = user_and_client
    lead_id = _make_lead(owner_name=None, owner_phone=None)

    before = db_service._service.get_daily_leads_used(user_id)
    before_used = int(before.get("used") or 0)
    before_remaining = int(before.get("remaining") or 0)

    r = client.post(
        f"/api/leads/{lead_id}/reserve",
        headers=headers,
        json={"minutes": 60, "consent": True, "idempotency": f"pytest-quota-{lead_id}"},
    )
    assert r.status_code == 422, r.text

    after = db_service._service.get_daily_leads_used(user_id)
    assert int(after.get("used") or 0) == before_used, (
        f"BUG: 422 consumiu cota: {before} -> {after}"
    )
    assert int(after.get("remaining") or 0) == before_remaining, (
        f"BUG: 422 reduziu o saldo de créditos: {before} -> {after}"
    )

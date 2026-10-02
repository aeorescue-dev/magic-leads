"""Caminho do PROVIDER dentro do endpoint de reserva.

Complementa `test_reserve_atomic_quota.py`, que usa um provider que responde
sempre `NORESULTS`. Aqui o provider RESPONDE COM TELEFONE, que e o caminho que
converte um lead entregue de graca num lead cobrado. Sem estes testes, a regra
"so se cobra em sucesso total" podia passar em metade dos casos e a cobranca
errada depois de um telefone aparecer nao era apanhada por ninguem.

Cadeia real exercitada: lead sem telefone -> `searchbug_service.lookup_phone`
devolve numero -> `update_owner_phone` persiste -> `reveal_lead` debita.
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

EMAIL = "pytest-provider-path@magicleads.app"
TOKEN = "pytest-provider-path-token"

_EXT = {"n": 0}


def _make_lead(owner_name=None, owner_phone=None, mailing_address=None) -> int:
    _EXT["n"] += 1
    payload = EnrichedLead(
        external_id=f"pytest-provider-path-{_EXT['n']}",
        source_type=SourceType.SERVICE_311,
        address=f"{_EXT['n']} PROVIDER STREET",
        city="BROOKLYN",
        state="NY",
        zip_code="11201",
        lat=None,
        lng=None,
        county="KINGS",
        issue_category=IssueCategory.ROOF,
        issue_description="Caminho de provider",
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
    assert row is not None
    return row["id"]


class _PhoneFound:
    """Searchbug que ACERTA: e o caminho que deve passar a cobrar."""

    def __init__(self, phone="+17185550111"):
        self.phone = phone
        self.calls = []

    async def lookup_phone(self, address, city, state, owner_name=None, zip_code=None):
        self.calls.append(
            {"address": address, "city": city, "state": state, "owner_name": owner_name}
        )

        class R:
            success = True

        R.phone = self.phone
        R.error = None
        R.provider = "Searchbug"
        return R()


class _NoPhone:
    async def lookup_phone(self, *args, **kwargs):
        class R:
            success = False
            phone = None
            error = "NORESULTS"
            provider = "Searchbug"

        return R()


class _ProviderExplodes:
    async def lookup_phone(self, *args, **kwargs):
        raise RuntimeError("Searchbug fora do ar (500)")


class _NoName:
    async def enrich(self, *args, **kwargs):
        return None


@pytest.fixture(scope="module")
def user_and_client():
    svc = db_service._service
    user = svc.get_user_by_email(EMAIL) or svc.create_user(
        EMAIL, "pytest-hash-not-used", "Pytest Provider Path", plan="pro",
        subscription_status="active",
    )
    assert user is not None
    user_id = user["id"]
    svc.create_user_session(user_id, _hash_token(TOKEN), "Pytest", None)
    svc.extend_access(user_id, days=7)
    return TestClient(app), {"Authorization": f"Bearer {TOKEN}"}, user_id


def _used(user_id: int) -> int:
    return int(db_service._service.get_daily_leads_used(user_id).get("used") or 0)


@pytest.fixture
def reset_quota():
    """Devolve a cota a 0 antes de cada teste, e restaura no fim."""
    from backend.services.db import get_connection

    def _reset(user_id):
        svc = db_service._service
        today = datetime.utcnow().date().isoformat()
        conn = get_connection()
        try:
            conn.execute(
                """INSERT OR REPLACE INTO user_daily_stats
                   (user_id, date, leads_used, leads_limit, reset_at)
                   VALUES (?, ?, 0, 10, ?)""",
                (user_id, today, svc._utc_tomorrow_midnight().isoformat()),
            )
            conn.commit()
        finally:
            conn.close()

    yield _reset


# ---------------------------------------------------------------------------
def test_provider_phone_turns_a_free_lead_into_a_paid_one(
    user_and_client, reset_quota, monkeypatch
):
    """Nome sem telefone + provider ACERTA => sucesso total => debita.

    Este e o unico caminho em que um lead que ia ser entregue de graca passa a
    ser cobrado. A Regra A diz que a cobranca segue a qualidade FINAL dos dados,
    nao a que o lead tinha quando o user clicou.
    """
    client, headers, user_id = user_and_client
    reset_quota(user_id)

    provider = _PhoneFound()
    monkeypatch.setattr(main_module, "searchbug_service", provider)
    monkeypatch.setattr(main_module, "owner_enrichment", _NoName())

    lead_id = _make_lead(owner_name="MARIA SANTOS", owner_phone=None, mailing_address=None)

    r = client.post(
        f"/api/leads/{lead_id}/reserve",
        headers=headers,
        json={"minutes": 60, "consent": True, "idempotency": f"prov-paid-{lead_id}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()

    assert provider.calls, "o provider nem foi consultado"
    assert body["charged"] is True, "com telefone do provider devia cobrar"
    assert body["incomplete_delivery"] is False
    assert body["owner"]["phone"] == "+17185550111", body["owner"]
    assert _used(user_id) == 1, "cota nao foi consumida num lead que virou completo"


def test_provider_noresults_keeps_the_lead_free(user_and_client, reset_quota, monkeypatch):
    """Nome sem telefone + provider FALHA => entregue de graca, cota intacta."""
    client, headers, user_id = user_and_client
    reset_quota(user_id)

    monkeypatch.setattr(main_module, "searchbug_service", _NoPhone())
    monkeypatch.setattr(main_module, "owner_enrichment", _NoName())

    lead_id = _make_lead(owner_name="MARIA SANTOS", owner_phone=None, mailing_address=None)

    r = client.post(
        f"/api/leads/{lead_id}/reserve",
        headers=headers,
        json={"minutes": 60, "consent": True, "idempotency": f"prov-free-{lead_id}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["charged"] is False, "provider falhou mas o lead foi cobrado"
    assert body["incomplete_delivery"] is True
    assert body["missing"], "devia dizer o que falta"
    assert body["owner"]["name"] == "MARIA SANTOS", "o nome tem de ser entregue"
    assert not body["owner"]["phone"], "nao ha telefone para entregar"
    assert _used(user_id) == 0, "lead incompleto consumiu cota"


def test_provider_outage_does_not_break_delivery(user_and_client, reset_quota, monkeypatch):
    """Provider levantado nao pode devolver 5xx nem perder o lead.

    O Searchbug e um servico externo pago e instavel. Se a sua queda levasse o
    utilizador a um 500, ele perderia a reserva que ja estava a tentar fazer.
    """
    client, headers, user_id = user_and_client
    reset_quota(user_id)

    monkeypatch.setattr(main_module, "searchbug_service", _ProviderExplodes())
    monkeypatch.setattr(main_module, "owner_enrichment", _NoName())

    lead_id = _make_lead(owner_name="MARIA SANTOS", owner_phone=None, mailing_address=None)

    r = client.post(
        f"/api/leads/{lead_id}/reserve",
        headers=headers,
        json={"minutes": 60, "consent": True, "idempotency": f"prov-out-{lead_id}"},
    )
    assert r.status_code == 200, f"provider em queda devolveu {r.status_code}: {r.text}"
    body = r.json()

    assert body["charged"] is False
    assert body["reserved"] is True, "o lead ficou por entregar"
    assert _used(user_id) == 0


def test_provider_is_not_called_when_the_lead_already_has_a_phone(
    user_and_client, reset_quota, monkeypatch
):
    """Sem telefone em falta nao ha motivo para pagar uma consulta."""
    client, headers, user_id = user_and_client
    reset_quota(user_id)

    provider = _PhoneFound()
    monkeypatch.setattr(main_module, "searchbug_service", provider)
    monkeypatch.setattr(main_module, "owner_enrichment", _NoName())

    lead_id = _make_lead(owner_name="JOHN DOE", owner_phone="(718) 555-0700")

    r = client.post(
        f"/api/leads/{lead_id}/reserve",
        headers=headers,
        json={"minutes": 60, "consent": True, "idempotency": f"prov-nocall-{lead_id}"},
    )
    assert r.status_code == 200, r.text
    assert provider.calls == [], "pagou uma consulta ao provider sem necessidade"
    assert r.json()["charged"] is True
    assert _used(user_id) == 1
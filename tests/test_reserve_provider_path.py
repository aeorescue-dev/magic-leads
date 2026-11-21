"""Caminho PAGO do telefone: clique enfileira, worker entrega.

Substitui a suite antiga que assumia chamada sincrona no `/reserve`. O que se
guarda de proposito:
  * a cota so' fica consumida quando ha telefone entregue ou job aceite;
  * falha definitiva devolve a unidade;
  * telefone ja existente nunca chama o provider;
  * `verified` vem da prova (nome + camada), nao de "o provider respondeu".
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import backend.services.phone_jobs as phone_jobs
from backend.config import settings
from backend.main import _hash_token, app
from backend.models.schemas import (
    EnrichedLead,
    IssueCategory,
    SourceType,
    UrgencyLevel,
)
from backend.services import daily_quota, phone_cache
from backend.services.db import db_service
from backend.services.enrichment import owner_enrichment
from backend.services.searchbug import PhoneLookupResult
from backend.utils.time import utcnow

EMAIL = "pytest-provider-path@magicleads.app"
TOKEN = "pytest-provider-path-token"

_EXT = {"n": 0}


def _make_lead(owner_name=None, owner_phone=None, mailing_address=None) -> tuple[int, str]:
    _EXT["n"] += 1
    address = f"{_EXT['n']} PROVIDER STREET"
    payload = EnrichedLead(
        external_id=f"pytest-provider-path-{_EXT['n']}",
        source_type=SourceType.SERVICE_311,
        address=address,
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
    return int(row["id"]), address


class _PhoneFound:
    def __init__(self, phone="+17185550111"):
        self.phone = phone
        self.calls = []

    async def lookup_phone(self, address, city, state, owner_name=None, zip_code=None, **kwargs):
        self.calls.append(
            {"address": address, "city": city, "state": state, "owner_name": owner_name}
        )
        return PhoneLookupResult(
            success=True,
            phone=self.phone,
            provider="Searchbug",
            verified=True,
            name_match=1.0,
            layer=kwargs.get("layer") or "L2",
        )


class _NoPhone:
    def __init__(self):
        self.calls = []

    async def lookup_phone(self, *args, **kwargs):
        self.calls.append(kwargs)
        return PhoneLookupResult(
            success=False, error="no_results", provider="Searchbug"
        )


class _TransportError:
    async def lookup_phone(self, *args, **kwargs):
        return PhoneLookupResult(
            success=False,
            error="transport_error:empty_or_non_json",
            provider="Searchbug",
        )


async def _no_enrich(*args, **kwargs):
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


def _reset_quota(user_id: int) -> None:
    svc = db_service._service
    today = utcnow().date().isoformat()
    from backend.services.db import get_connection

    conn = get_connection()
    try:
        conn.execute(
            """INSERT OR REPLACE INTO user_daily_stats
               (user_id, date, leads_used, leads_limit, reset_at)
               VALUES (?, ?, 0, 10, ?)""",
            (user_id, today, svc._utc_tomorrow_midnight().isoformat()),
        )
        conn.execute(
            "UPDATE user_daily_usage SET phone_used=0, letter_used=0 WHERE user_id=?",
            (user_id,),
        )
        conn.execute("DELETE FROM phone_attempts WHERE user_id=?", (user_id,))
        conn.commit()
    finally:
        conn.close()


def _phone_used(user_id: int) -> int:
    return int(daily_quota.usage_payload(user_id)["phone_used"])


def _drain_jobs(lead_id: int) -> list[dict]:
    summaries = []
    for job in phone_jobs.claim_due(limit=20, lead_id=lead_id):
        summaries.append(asyncio.run(phone_jobs.process_one(job)))
    return summaries


@pytest.fixture(autouse=True)
def _isolate_provider(monkeypatch):
    """Nenhum teste toca na rede: owner e provider sao sempre locais."""
    _reset_quota(1)
    monkeypatch.setattr(settings, "SEARCHBUG_MOCK", False, raising=False)
    monkeypatch.setattr(settings, "PHONE_L3_UNNAMED_ENABLED", False, raising=False)
    monkeypatch.setattr(owner_enrichment, "enrich", _no_enrich)


def test_click_enqueues_without_calling_provider(user_and_client, monkeypatch):
    client, headers, user_id = user_and_client
    _reset_quota(user_id)
    provider = _PhoneFound()
    monkeypatch.setattr(phone_jobs, "searchbug_service", provider)

    lead_id, address = _make_lead(owner_name="MARIA SANTOS")

    r = client.post(
        f"/api/leads/{lead_id}/reserve",
        headers=headers,
        json={"minutes": 60, "consent": True, "idempotency": f"async-{lead_id}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["phone_state"] == "in_progress", body
    assert body["owner"]["phone"] is None
    assert body["charged"] is True, "o job aceite reserva a unidade"
    assert provider.calls == [], "o clique NAO pode chamar a Searchbug"
    assert _phone_used(user_id) == 1

    key = phone_cache.build_cache_key(lead_id, "MARIA SANTOS", address, "11201")
    job = phone_jobs.get_by_cache_key(key)
    assert job and job["status"] == "pending", job


def test_worker_delivers_phone_and_marks_verified(user_and_client, monkeypatch):
    client, headers, user_id = user_and_client
    _reset_quota(user_id)
    provider = _PhoneFound()
    monkeypatch.setattr(phone_jobs, "searchbug_service", provider)

    lead_id, address = _make_lead(owner_name="MARIA SANTOS")
    # Proveniencia persistida (como se viesse de um BBL exacto).
    db_service._service.update_owner_resolution(
        lead_id,
        SimpleNamespace(
            parcel_key="4087860042",
            owner_kind="person",
            record_year=2025,
            match_method="bbl",
            confidence="high",
            source_dataset="data.cityofnewyork.us/64uk-42ks",
        ),
    )
    client.post(
        f"/api/leads/{lead_id}/reserve",
        headers=headers,
        json={"minutes": 60, "consent": True, "idempotency": f"worker-{lead_id}"},
    )

    summaries = _drain_jobs(lead_id)
    assert summaries and summaries[-1]["ok"] is True, summaries
    assert len(provider.calls) == 1

    lead = db_service._service.get_lead_by_id(lead_id)
    assert lead["owner_phone"] == "+17185550111"
    assert lead["phone_verified"] == 1, "nome 1.0 + L2 = verificado"

    key = phone_cache.build_cache_key(lead_id, "MARIA SANTOS", address, "11201")
    cached = phone_cache.get(key)
    assert cached["phone"] == "+17185550111"
    assert cached["verified"] == 1


def test_no_results_refunds_phone_quota(user_and_client, monkeypatch):
    client, headers, user_id = user_and_client
    _reset_quota(user_id)
    provider = _NoPhone()
    monkeypatch.setattr(phone_jobs, "searchbug_service", provider)

    lead_id, _ = _make_lead(owner_name="MARIA SANTOS")
    r = client.post(
        f"/api/leads/{lead_id}/reserve",
        headers=headers,
        json={"minutes": 60, "consent": True, "idempotency": f"none-{lead_id}"},
    )
    assert r.status_code == 200
    assert _phone_used(user_id) == 1

    _drain_jobs(lead_id)
    assert _phone_used(user_id) == 0, "ausencia definitiva devolve a unidade"
    assert db_service._service.get_lead_by_id(lead_id)["owner_phone"] is None


def test_transport_error_retries_then_refunds(user_and_client, monkeypatch):
    client, headers, user_id = user_and_client
    _reset_quota(user_id)
    monkeypatch.setattr(phone_jobs, "searchbug_service", _TransportError())
    monkeypatch.setattr(phone_jobs, "MAX_ATTEMPTS", 1)

    lead_id, _ = _make_lead(owner_name="MARIA SANTOS")
    client.post(
        f"/api/leads/{lead_id}/reserve",
        headers=headers,
        json={"minutes": 60, "consent": True, "idempotency": f"trans-{lead_id}"},
    )
    _drain_jobs(lead_id)
    assert _phone_used(user_id) == 0


def test_reveal_phone_endpoint_is_in_progress_then_ready(user_and_client, monkeypatch):
    client, headers, user_id = user_and_client
    _reset_quota(user_id)
    monkeypatch.setattr(phone_jobs, "searchbug_service", _PhoneFound())

    lead_id, _ = _make_lead(owner_name="MARIA SANTOS")
    db_service._service.update_owner_resolution(
        lead_id,
        SimpleNamespace(
            parcel_key="4087860042",
            owner_kind="person",
            record_year=2025,
            match_method="bbl",
            confidence="high",
            source_dataset="data.cityofnewyork.us/64uk-42ks",
        ),
    )
    first = client.post(f"/api/leads/{lead_id}/reveal-phone", headers=headers)
    assert first.status_code == 200, first.text
    assert first.json()["state"] == "in_progress"
    assert first.json()["phone"] is None
    assert _phone_used(user_id) == 1

    _drain_jobs(lead_id)
    second = client.post(f"/api/leads/{lead_id}/reveal-phone", headers=headers)
    assert second.status_code == 200, second.text
    body = second.json()
    assert body["state"] == "ready"
    assert body["phone"] == "+17185550111"
    assert body["phone_verified"] is True


def test_existing_phone_never_calls_provider(user_and_client, monkeypatch):
    client, headers, user_id = user_and_client
    _reset_quota(user_id)
    provider = _PhoneFound()
    monkeypatch.setattr(phone_jobs, "searchbug_service", provider)

    lead_id, _ = _make_lead(owner_name="JOHN DOE", owner_phone="(718) 555-0700")
    r = client.post(
        f"/api/leads/{lead_id}/reserve",
        headers=headers,
        json={"minutes": 60, "consent": True, "idempotency": f"have-{lead_id}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["phone_state"] == "ready", body
    assert body["owner"]["phone"] == "(718) 555-0700"
    assert provider.calls == []
    assert _phone_used(user_id) == 1

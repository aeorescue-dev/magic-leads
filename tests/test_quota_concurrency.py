"""P0-C1B: cota atomica, orcamento de tentativas e fluxo sem consentimento.

Cobre:
  * 20 pedidos concorrentes em 0/10 -> exatamente 10 ganham;
  * `reveal_lead` concorrente em 20 leads -> no maximo 10 cobrados;
  * 30 tentativas/dia e 3/min por utilizador (sem cap global);
  * cota esgotada -> lookup pago saltado, lead entregue gratis;
  * consent=False -> reserva simples, 0 chamadas a Searchbug.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
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
from backend.services.db import db_service, get_connection
from backend.utils.time import utcnow

EMAIL = "pytest-quota-concurrency@magicleads.app"
_EXT = {"n": 0}


def _make_lead(owner_name=None, owner_phone=None) -> int:
    _EXT["n"] += 1
    payload = EnrichedLead(
        external_id=f"pytest-quota-{_EXT['n']}",
        source_type=SourceType.SERVICE_311,
        address=f"{_EXT['n']} QUOTA STREET",
        city="BROOKLYN",
        state="NY",
        zip_code="11201",
        lat=None,
        lng=None,
        county="KINGS",
        issue_category=IssueCategory.ROOF,
        issue_description="quota concurrency",
        urgency_level=UrgencyLevel.HIGH,
        owner_name=owner_name,
        owner_phone=owner_phone,
        owner_email=None,
        mailing_address=None,
        date_reported=datetime(2026, 1, 15, 12, 0, 0),
        image_url=None,
        source_url=None,
    )
    row = db_service._service.insert_lead_new(payload)
    assert row is not None
    return row["id"]


def _reset_quota(user_id: int, used: int = 0) -> None:
    conn = get_connection()
    try:
        conn.execute(
            """INSERT OR REPLACE INTO user_daily_stats
               (user_id, date, leads_used, leads_limit, reset_at)
               VALUES (?, ?, ?, 10, ?)""",
            (user_id, utcnow().date().isoformat(), used,
             db_service._service._utc_tomorrow_midnight().isoformat()),
        )
        conn.execute("DELETE FROM phone_attempts WHERE user_id = ?", (user_id,))
        conn.commit()
    finally:
        conn.close()


def _used(user_id: int) -> int:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT leads_used FROM user_daily_stats WHERE user_id = ? AND date = ?",
            (user_id, utcnow().date().isoformat()),
        ).fetchone()
        return int(row["leads_used"]) if row else 0
    finally:
        conn.close()


@pytest.fixture(scope="module")
def user():
    svc = db_service._service
    u = svc.get_user_by_email(EMAIL) or svc.create_user(
        EMAIL, "pytest-hash", "Pytest Quota", plan="pro",
        subscription_status="active",
    )
    assert u is not None
    svc.extend_access(u["id"], days=7)
    return u["id"]


@pytest.fixture
def client(user, monkeypatch):
    import uuid
    token = f"pytest-quota-token-{uuid.uuid4().hex}"
    db_service._service.create_user_session(user, _hash_token(token), "Pytest", None)
    monkeypatch.setattr(main_module.limiter, "enabled", False, raising=False)
    return TestClient(app), {"Authorization": f"Bearer {token}"}


class _CountingPhone:
    def __init__(self):
        self.calls = 0

    async def lookup_phone(self, *args, **kwargs):
        self.calls += 1

        class R:
            success = True
            phone = "+17185550199"
            verified = True
            name_match = 1.0
            error = None
            provider = "Searchbug"

        return R()


class _NoEnrich:
    async def enrich(self, *args, **kwargs):
        return None


def test_concurrent_quota_reservations_cap_at_ten(user):
    """20 threads em 0/10: exatamente 10 reservas atomicas."""
    _reset_quota(user, 0)
    svc = db_service._service

    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(lambda _: svc.reserve_daily_quota(user), range(20)))

    assert sum(1 for r in results if r) == 10, results
    assert _used(user) == 10


def test_concurrent_reveals_cap_at_ten(user):
    """20 leads distintos, 20 threads: no maximo 10 cobrados."""
    _reset_quota(user, 0)
    svc = db_service._service
    leads = [_make_lead(owner_name=f"OWNER {i}", owner_phone="(718) 555-0100") for i in range(20)]

    def _reveal(lead_id):
        return svc.reveal_lead(user, lead_id, charge_credit=True)

    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(_reveal, leads))

    charged = [r for r in results if r and not r.get("error")]
    rejected = [r for r in results if r and r.get("error") == "limit_reached"]
    assert len(charged) == 10, [r.get("error") for r in results]
    assert len(rejected) == 10
    assert _used(user) == 10


def test_attempt_budget_daily(user, monkeypatch):
    monkeypatch.setattr("backend.services.db.settings.PHONE_ATTEMPTS_PER_USER_DAY", 30, raising=False)
    monkeypatch.setattr("backend.services.db.settings.PHONE_ATTEMPTS_PER_USER_MINUTE", 10_000, raising=False)
    _reset_quota(user)
    svc = db_service._service

    results = [svc.reserve_phone_attempt(user) for _ in range(31)]

    assert all(r["ok"] for r in results[:30])
    assert results[30]["ok"] is False
    assert results[30]["reason"] == "daily_attempts"


def test_attempt_budget_burst(user, monkeypatch):
    monkeypatch.setattr("backend.services.db.settings.PHONE_ATTEMPTS_PER_USER_DAY", 30, raising=False)
    monkeypatch.setattr("backend.services.db.settings.PHONE_ATTEMPTS_PER_USER_MINUTE", 3, raising=False)
    _reset_quota(user)
    svc = db_service._service

    results = [svc.reserve_phone_attempt(user) for _ in range(4)]

    assert [r["ok"] for r in results] == [True, True, True, False]
    assert results[3]["reason"] == "burst"


def test_exhausted_quota_skips_paid_call_and_delivers_free(user, client, monkeypatch):
    """Cota 10/10 + lead cobravel: 200, sem telefone, 0 chamadas."""
    _reset_quota(user, 10)
    fake = _CountingPhone()
    monkeypatch.setattr(main_module, "searchbug_service", fake)
    monkeypatch.setattr(main_module, "owner_enrichment", _NoEnrich())
    http, headers = client

    lead_id = _make_lead(owner_name="75 PARK LLC", owner_phone=None)
    r = http.post(
        f"/api/leads/{lead_id}/reserve",
        headers=headers,
        json={"minutes": 60, "consent": True, "idempotency": f"q-exhausted-{lead_id}"},
    )

    assert r.status_code == 200, r.text
    assert r.json()["charged"] is False
    assert r.json()["owner"]["phone"] in (None, "")
    assert fake.calls == 0, "chamada paga feita com a cota esgotada"
    assert _used(user) == 10


def test_attempt_budget_blocks_endpoint_before_provider(user, client, monkeypatch):
    """30 tentativas hoje: 429 antes de qualquer chamada paga."""
    _reset_quota(user, 0)
    conn = get_connection()
    try:
        for _ in range(30):
            conn.execute("INSERT INTO phone_attempts (user_id) VALUES (?)", (user,))
        conn.commit()
    finally:
        conn.close()

    fake = _CountingPhone()
    monkeypatch.setattr(main_module, "searchbug_service", fake)
    monkeypatch.setattr(main_module, "owner_enrichment", _NoEnrich())
    http, headers = client

    lead_id = _make_lead(owner_name="JOE BUDGET", owner_phone=None)
    r = http.post(
        f"/api/leads/{lead_id}/reserve",
        headers=headers,
        json={"minutes": 60, "consent": True, "idempotency": f"q-budget-{lead_id}"},
    )

    assert r.status_code == 429, r.text
    assert "tentativas" in r.text.lower()
    assert fake.calls == 0


def test_no_consent_never_calls_provider(user, client, monkeypatch):
    """consent=False: reserva simples, 0 chamadas, cota +1."""
    _reset_quota(user, 0)
    fake = _CountingPhone()
    monkeypatch.setattr(main_module, "searchbug_service", fake)
    http, headers = client

    lead_id = _make_lead(owner_name="NO CONSENT", owner_phone=None)
    r = http.post(
        f"/api/leads/{lead_id}/reserve",
        headers=headers,
        json={"minutes": 60, "consent": False},
    )

    assert r.status_code == 200, r.text
    assert fake.calls == 0, "fluxo sem consentimento chamou a Searchbug"
    assert _used(user) == 1


def test_load_ten_users_ten_reveals_without_global_cap():
    """10 utilizadores x 10 revelacoes concorrentes: 100 sucessos, 0 locks.

    Prova que a capacidade escala com os utilizadores e que NAO existe um cap
    global: cada um dos 10 utilizadores termina em 10/10.
    """
    svc = db_service._service
    users = []
    for i in range(10):
        email = f"pytest-load-{i}@magicleads.app"
        u = svc.get_user_by_email(email) or svc.create_user(
            email, "x", f"Load {i}", plan="pro", subscription_status="active",
        )
        assert u is not None
        svc.extend_access(u["id"], days=7)
        users.append(u["id"])

    jobs = []
    for uid in users:
        _reset_quota(uid, 0)
        for _ in range(10):
            jobs.append(
                (uid, _make_lead(owner_name="LOAD OWNER", owner_phone="(718) 555-0111"))
            )

    def _reveal(job):
        uid, lead_id = job
        return svc.reveal_lead(uid, lead_id, charge_credit=True)

    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(_reveal, jobs))

    errors = [r.get("error") for r in results if not r or r.get("error")]
    assert not errors, errors
    for uid in users:
        assert _used(uid) == 10


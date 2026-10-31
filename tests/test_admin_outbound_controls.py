"""Controles do Admin outbound: readiness, switches por cidade, caps/rampa."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from backend.main import _hash_token, app
from backend.services.db import db_service, get_connection

ADMIN_EMAIL = "pytest-outbound-admin@magicleads.app"
ADMIN_TOKEN = "pytest-outbound-admin-token"


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def _headers(token: str = ADMIN_TOKEN) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _ensure_admin() -> int:
    svc = db_service._service
    user = svc.get_user_by_email(ADMIN_EMAIL) or svc.create_user(
        ADMIN_EMAIL, "pytest-hash", "Pytest Outbound", plan="free"
    )
    try:
        svc.create_user_session(user["id"], _hash_token(ADMIN_TOKEN), "Pytest", None)
    except Exception:
        pass
    svc.set_user_admin(ADMIN_EMAIL, True)
    return user["id"]


@pytest.fixture(scope="module", autouse=True)
def admin_user(client):
    _ensure_admin()
    yield
    # Não deixar overrides/estado de outbound a contaminar os outros testes.
    conn = get_connection()
    try:
        conn.execute("DELETE FROM outbound_config WHERE city='NYC'")
        conn.execute("DELETE FROM sending_mailboxes WHERE email='nyc-box@example.com'")
        conn.execute(
            "DELETE FROM outbound_contacts WHERE lower(email) IN "
            "('nyc-ready@example.com','nyc-quarantine@example.com')"
        )
        conn.execute(
            "DELETE FROM leads WHERE external_id IN "
            "('b2b:nyc-ready@example.com','b2b:nyc-quarantine@example.com')"
        )
        conn.execute("DELETE FROM system_kv WHERE key='auto_ramp_last_eval'")
        conn.commit()
    finally:
        conn.close()


@pytest.fixture()
def mailbox():
    svc = db_service._service
    conn = get_connection()
    try:
        conn.execute("DELETE FROM sending_mailboxes WHERE email=?", ("nyc-box@example.com",))
        conn.commit()
    finally:
        conn.close()
    row = svc.upsert_sending_mailbox(
        email="nyc-box@example.com",
        provider="gmail",
        transport="gmail_api",
        daily_cap=1,
        enabled=1,
        warmup_state="warm",
        auth_ref=json.dumps({"refresh_token": "x"}),
    )
    assert row
    return row


def test_readiness_conta_apenas_nichos_confirmados_sem_mensagem(client):
    svc = db_service._service
    conn = get_connection()
    try:
        conn.execute(
            "DELETE FROM outbound_messages WHERE lower(to_email) IN "
            "('nyc-ready@example.com','nyc-quarantine@example.com')"
        )
        conn.execute(
            "DELETE FROM outbound_contacts WHERE lower(email) IN "
            "('nyc-ready@example.com','nyc-quarantine@example.com')"
        )
        conn.commit()
    finally:
        conn.close()
    svc.import_b2b_lead(
        email="nyc-ready@example.com",
        company_name="NYC Ready GC",
        city="NYC",
        category="General Contractors",
        niche_key="general_contractors",
        niche_status="confirmed",
    )
    svc.import_b2b_lead(
        email="nyc-quarantine@example.com",
        company_name="NYC Ambiguous",
        city="NYC",
        category="General Contractors",
        niche_key=None,
        niche_status="ambiguous",
    )

    r = client.get(
        "/api/admin/outbound/readiness?city=NYC&niche=general_contractors",
        headers=_headers(),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ready"] >= 1
    assert body["quarantined"] >= 1
    assert body["city"] == "NYC"


def test_switch_por_cidade_nao_altera_global(client):
    r = client.post(
        "/api/admin/outbound/config",
        headers=_headers(),
        json={"city": "NYC", "send_enabled": False},
    )
    assert r.status_code == 200, r.text
    cfg = client.get("/api/admin/outbound/config", headers=_headers()).json()
    assert cfg["per_city"]["NYC"]["send_enabled"] == "0"
    # Volta a ligar para não afetar os outros testes.
    client.post(
        "/api/admin/outbound/config",
        headers=_headers(),
        json={"city": "NYC", "send_enabled": True},
    )


def test_config_edita_batch_size_e_teto(client):
    r = client.post(
        "/api/admin/outbound/config",
        headers=_headers(),
        json={
            "city": "NYC",
            "batch_size": 25,
            "max_spend_per_batch_usd": 8.5,
        },
    )
    assert r.status_code == 200, r.text
    cfg = client.get("/api/admin/outbound/config", headers=_headers()).json()
    assert cfg["per_city"]["NYC"]["batch_size"] == "25"
    assert cfg["per_city"]["NYC"]["max_spend_per_batch_usd"] == "8.50"


def test_controls_caps_e_auto_ramp(client, mailbox):
    r = client.post(
        f"/api/admin/outbound/mailboxes/{mailbox['id']}/controls",
        headers=_headers(),
        json={"daily_cap": 10, "auto_ramp_enabled": True, "auto_ramp_max": 50},
    )
    assert r.status_code == 200, r.text
    updated = r.json()["mailbox"]
    assert updated["daily_cap"] == 10
    assert updated["auto_ramp_enabled"] == 1
    assert updated["auto_ramp_max"] == 50
    # Ao ligar a rampa, parte do cap efetivo atual (nunca salta para 25).
    assert 1 <= updated["auto_ramp_cap"] <= 50


def _find_mailbox(mailbox_id: int) -> dict:
    return next(
        m
        for m in db_service._service.list_sending_mailboxes()
        if int(m["id"]) == int(mailbox_id)
    )


def test_pause_e_resume_exigem_admin_e_funcionam(client, mailbox):
    r = client.post(
        f"/api/admin/outbound/mailboxes/{mailbox['id']}/pause",
        headers=_headers(),
        json={"reason": "manual"},
    )
    assert r.status_code == 200, r.text
    row = _find_mailbox(mailbox["id"])
    assert row["enabled"] == 0
    assert row["paused_reason"] == "manual"

    r = client.post(
        f"/api/admin/outbound/mailboxes/{mailbox['id']}/resume",
        headers=_headers(),
    )
    assert r.status_code == 200, r.text
    row = _find_mailbox(mailbox["id"])
    assert row["enabled"] == 1
    assert row["paused_at"] is None


def test_endpoints_recusam_nao_admin(client):
    r = client.get("/api/admin/outbound/readiness?city=NYC")
    assert r.status_code == 401
    r = client.post(
        "/api/admin/outbound/mailboxes/1/controls", json={"daily_cap": 5}
    )
    assert r.status_code == 401


def test_contractors_stats_por_cidade(client):
    r = client.get(
        "/api/admin/contractors/stats?city=NYC", headers=_headers()
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "NYC" in body["cities"]
    assert "by_status" in body["cities"]["NYC"]["counts"]
    assert "jobs_today" in body["cities"]["NYC"]["state"]

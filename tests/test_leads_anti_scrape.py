"""A1: o feed e o detalhe do lead exigem conta (anti-raspagem)."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from backend.main import _hash_token, app
from backend.services.db import db_service, get_connection


def _reset():
    conn = get_connection()
    try:
        for table in ("user_sessions", "users", "leads"):
            conn.execute(f"DELETE FROM {table}")
        conn.commit()
    finally:
        conn.close()


def _user(uid_email: str | None = None) -> int:
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO users (email, password_hash, company_name, plan, "
            "subscription_status, plan_until, locale) "
            "VALUES (?, 'x', 'A1 Co', 'pro', 'active', ?, 'pt')",
            (
                uid_email or f"a1_{uuid.uuid4().hex[:8]}@test.com",
                (datetime.now(timezone.utc) + timedelta(days=5)).isoformat(),
            ),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def _session(uid: int, token: str):
    db_service._service.create_user_session(
        uid, _hash_token(token), "pytest", "127.0.0.1"
    )
    return {"Authorization": f"Bearer {token}"}


def _lead() -> int:
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO leads (external_id, source_type, address, city, state, "
            "issue_category, date_reported, case_status, signal_type, signal_status) "
            "VALUES (?, '311', ?, 'NYC', 'NY', 'Roof', ?, 'Open', 'open_request', 'open')",
            (
                f"a1-{uuid.uuid4().hex[:10]}",
                f"{uuid.uuid4().hex[:6]} ANTI SCRAPE ST",
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def test_feed_requires_account():
    _reset()
    client = TestClient(app)
    r = client.get("/api/leads?city=NYC")
    assert r.status_code == 401


def test_feed_works_with_session_and_caps_per_page():
    _reset()
    uid = _user()
    headers = _session(uid, "a1-token-feed")
    _lead()
    client = TestClient(app)

    r = client.get("/api/leads?city=NYC&per_page=500", headers=headers)
    assert r.status_code == 200
    data = r.json()
    assert data["per_page"] <= 200
    assert isinstance(data["leads"], list)


def test_invalid_session_does_not_read_feed():
    _reset()
    client = TestClient(app)
    r = client.get("/api/leads?city=NYC", headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401


def test_lead_detail_requires_account():
    _reset()
    lead_id = _lead()
    client = TestClient(app)
    r = client.get(f"/api/leads/{lead_id}")
    assert r.status_code == 401


def test_lead_detail_works_with_session():
    _reset()
    uid = _user()
    headers = _session(uid, "a1-token-detail")
    lead_id = _lead()
    client = TestClient(app)

    r = client.get(f"/api/leads/{lead_id}", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == str(lead_id)
    # Regra de ouro de IP mantém-se na rota autenticada.
    assert body["source"] is None
    assert body["department"] is None


def test_recent_sample_is_public_but_capped_and_masked():
    _reset()
    for _ in range(25):
        _lead()
    client = TestClient(app)

    r = client.get("/api/leads/recent?limit=500")
    assert r.status_code == 200
    data = r.json()
    assert data["per_page"] <= 20
    assert len(data["leads"]) <= 20
    for lead in data["leads"]:
        assert not lead.get("owner_phone")
        assert not lead.get("owner_name")


def test_today_and_search_require_account():
    _reset()
    _lead()
    client = TestClient(app)
    assert client.get("/api/leads/today?type=open_request").status_code == 401
    assert client.get("/api/leads/search?q=a").status_code == 401

    uid = _user()
    headers = _session(uid, "a1-token-today")
    assert client.get("/api/leads/today?type=open_request", headers=headers).status_code == 200
    assert client.get("/api/leads/search?q=a", headers=headers).status_code == 200


def test_recent_sample_respects_explicit_small_limit():
    _reset()
    for _ in range(5):
        _lead()
    client = TestClient(app)
    r = client.get("/api/leads/recent?limit=3")
    assert r.status_code == 200
    assert r.json()["per_page"] == 3
    assert len(r.json()["leads"]) <= 3

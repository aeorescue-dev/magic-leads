"""A2: TTL de sessão (idle timeout deslizante) e limpeza de expiradas."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from backend.main import _hash_token, app
from backend.services.db import db_service, get_connection


def _reset():
    conn = get_connection()
    try:
        for table in ("user_sessions", "users"):
            conn.execute(f"DELETE FROM {table}")
        conn.commit()
    finally:
        conn.close()


def _user() -> int:
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO users (email, password_hash, company_name, plan, "
            "subscription_status, plan_until, locale) "
            "VALUES (?, 'x', 'TTL Co', 'pro', 'active', ?, 'pt')",
            (
                f"ttl_{uuid.uuid4().hex[:8]}@test.com",
                (datetime.now(timezone.utc) + timedelta(days=5)).isoformat(),
            ),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def _create(uid: int, token: str) -> str:
    db_service._service.create_user_session(
        uid, _hash_token(token), "pytest", "127.0.0.1"
    )
    return token


def _row(token: str):
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM user_sessions WHERE token_hash = ?", (_hash_token(token),)
        ).fetchone()
    finally:
        conn.close()


def _force_expired(token: str):
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE user_sessions SET expires_at = datetime('now','-1 hour') "
            "WHERE token_hash = ?",
            (_hash_token(token),),
        )
        conn.commit()
    finally:
        conn.close()


def test_new_session_gets_ttl_from_config(monkeypatch):
    from backend.config import settings

    _reset()
    monkeypatch.setattr(settings, "SESSION_TTL_DAYS", 30, raising=False)
    uid = _user()
    token = "ttl-token-1"
    _create(uid, token)
    row = _row(token)
    assert row["expires_at"]
    expires = datetime.fromisoformat(row["expires_at"])
    delta = expires - datetime.now(timezone.utc).replace(tzinfo=None)
    # ~30 dias (tolerância de 1h para a execução do teste)
    assert timedelta(days=29, hours=23) < delta < timedelta(days=30, hours=1)


def test_expired_session_is_rejected_and_deleted():
    _reset()
    uid = _user()
    token = _create(uid, "ttl-token-2")
    _force_expired(token)

    assert db_service._service.validate_session(_hash_token(token))["status"] == "expired"
    assert db_service._service.validate_session(_hash_token(token))["status"] == "missing"
    assert _row(token) is None


def test_expired_session_returns_401_session_expired():
    _reset()
    uid = _user()
    token = _create(uid, "ttl-token-3")
    _force_expired(token)

    client = TestClient(app)
    r = client.get("/api/leads?city=NYC", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401
    assert r.json()["detail"]["error"] == "session_expired"


def test_valid_session_works_and_slides():
    _reset()
    uid = _user()
    token = _create(uid, "ttl-token-4")
    before = _row(token)["expires_at"]

    session = db_service._service.validate_session(_hash_token(token))
    assert session["status"] == "valid"
    assert session["user_id"] == uid
    after = _row(token)["expires_at"]
    assert after >= before  # renovada (idle timeout deslizante)


def test_missing_session_is_not_expired_code():
    _reset()
    client = TestClient(app)
    r = client.get(
        "/api/leads?city=NYC", headers={"Authorization": "Bearer inexistente"}
    )
    assert r.status_code == 401
    # Sessão inexistente continua a ser o código de evicção (compatibilidade).
    assert r.json()["detail"]["error"] == "session_expired_concurrent_login"


def test_prune_expired_sessions_only():
    _reset()
    uid = _user()
    alive = _create(uid, "ttl-alive")
    dead = _create(uid, "ttl-dead")
    _force_expired(dead)

    removed = db_service._service.prune_expired_sessions()
    assert removed >= 1
    assert _row(dead) is None
    assert _row(alive) is not None


def test_cookie_max_age_matches_ttl(monkeypatch):
    from backend import main as main_mod
    from backend.config import settings

    monkeypatch.setattr(settings, "SESSION_TTL_DAYS", 7, raising=False)
    monkeypatch.setattr(main_mod.settings, "SESSION_TTL_DAYS", 7, raising=False)

    _reset()
    client = TestClient(app)
    r = client.post(
        "/api/auth/register",
        json={
            "email": f"cookie_{uuid.uuid4().hex[:8]}@test.com",
            "password": "SenhaForte123!",
            "company_name": "Cookie Co",
        },
    )
    assert r.status_code in (200, 201)
    cookie = r.headers.get("set-cookie", "")
    assert "garimpador_token=" in cookie
    assert "Max-Age=604800" in cookie or "max-age=604800" in cookie


def test_admin_endpoints_also_reject_expired_session():
    _reset()
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO users (email, password_hash, company_name, plan, "
            "subscription_status, plan_until, locale, is_admin) "
            "VALUES (?, 'x', 'Admin Co', 'pro', 'active', ?, 'pt', 1)",
            (
                f"admin_{uuid.uuid4().hex[:8]}@test.com",
                (datetime.now(timezone.utc) + timedelta(days=5)).isoformat(),
            ),
        )
        uid = int(cur.lastrowid)
        conn.commit()
    finally:
        conn.close()

    token = _create(uid, "ttl-admin")
    client = TestClient(app)
    ok = client.get("/api/admin/overview", headers={"Authorization": f"Bearer {token}"})
    assert ok.status_code == 200

    _force_expired(token)
    expired = client.get(
        "/api/admin/overview", headers={"Authorization": f"Bearer {token}"}
    )
    assert expired.status_code == 401

"""Onboarding Wizard + gate A5 (402) + gestão de sessões no Admin.

Cobre o fluxo entregue no bloco:
  1. `/api/users/me/onboarding` e `/api/users/me/interests` (wizard);
  2. gate de assinatura A5 em contact/negotiate/convert (402, não 403);
  3. listagem/revogação de sessões ativas no painel admin.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from backend.main import _hash_token, app
from backend.services.db import db_service, get_connection

EMAIL = "pytest-onboarding@magicleads.app"
EXPIRED_EMAIL = "pytest-a5-expired@magicleads.app"
ADMIN_EMAIL = "pytest-sessions-admin@magicleads.app"
VICTIM_EMAIL = "pytest-sessions-victim@magicleads.app"

TOKEN = "pytest-onboarding-token"
EXPIRED_TOKEN = "pytest-a5-expired-token"
ADMIN_TOKEN = "pytest-sessions-admin-token"
VICTIM_TOKEN = "pytest-sessions-victim-token"


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def _user(email: str, token: str, *, active: bool = True, interests=None) -> int:
    svc = db_service._service
    user = svc.get_user_by_email(email) or svc.create_user(
        email, "pytest-hash", "Pytest Onboarding", plan="pro",
        subscription_status="active",
    )
    user_id = user["id"]
    try:
        svc.create_user_session(user_id, _hash_token(token), "Pytest Onboarding", None)
    except Exception:
        # Já existe (o fixture/parametrize volta a pedir o mesmo token).
        pass
    if active:
        svc.extend_access(user_id, days=7)
    if interests is not None:
        svc.set_user_interests(user_id, interests)
    return user_id


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ------------------------------------------------------------ onboarding


def test_onboarding_state_starts_incomplete_and_saves(client):
    user_id = _user(EMAIL, TOKEN)
    db_service._service.set_user_interests(user_id, [])  # base limpa

    r = client.get("/api/users/me/onboarding", headers=_headers(TOKEN))
    assert r.status_code == 200, r.text
    assert r.json()["completed"] is False

    # Sem categoria escolhida o wizard não pode concluir.
    r = client.put(
        "/api/users/me/interests", headers=_headers(TOKEN), json={"categories": []}
    )
    assert r.status_code == 400, r.text

    r = client.post(
        "/api/users/me/onboarding",
        headers=_headers(TOKEN),
        json={"categories": ["Roof", "Plumbing"], "cities": ["NYC", "Boston"]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["completed"] is True
    assert sorted(body["categories"]) == ["Plumbing", "Roof"]
    assert sorted(body["cities"] or []) == ["Boston", "NYC"]

    # O estado passa a "concluído" (o dashboard deixa de redireccionar).
    r = client.get("/api/users/me/onboarding", headers=_headers(TOKEN))
    assert r.status_code == 200
    assert r.json()["completed"] is True


def test_me_interests_saves_categories_and_cities(client):
    r = client.put(
        "/api/users/me/interests",
        headers=_headers(TOKEN),
        json={"categories": ["Paint"], "cities": ["Chicago"]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["categories"] == ["Paint"]
    assert body["cities"] == ["Chicago"]


def test_me_routes_require_auth(client):
    assert client.get("/api/users/me/onboarding").status_code == 401
    assert client.put("/api/users/me/interests", json={"categories": ["Roof"]}).status_code == 401


# ------------------------------------------------------------ A5 gate


def _expire(user_id: int) -> None:
    conn = get_connection()
    try:
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        conn.execute(
            "UPDATE users SET subscription_status = 'active', plan_until = ? WHERE id = ?",
            (past, user_id),
        )
        conn.commit()
    finally:
        conn.close()


@pytest.mark.parametrize(
    "method,path",
    [
        ("post", "/api/leads/999999/contact"),
        ("post", "/api/leads/999999/negotiate"),
        ("post", "/api/leads/999999/convert"),
    ],
)
def test_expired_account_gets_402_on_lifecycle(client, method, path):
    user_id = _user(EXPIRED_EMAIL, EXPIRED_TOKEN)
    _expire(user_id)

    r = getattr(client, method)(path, headers=_headers(EXPIRED_TOKEN), json={"channel": "sms"})
    assert r.status_code == 402, r.text
    detail = r.json()["detail"]
    assert detail["error"] == "subscription_required"
    assert detail["action"] == "REDIRECT_TO_CHECKOUT"


def test_active_account_is_not_blocked_by_gate(client):
    user_id = _user(EXPIRED_EMAIL, EXPIRED_TOKEN)
    db_service._service.extend_access(user_id, days=7)
    # Lead inexistente: o gate passa e o 404 vem da lógica de negócio,
    # nunca 402 (prova que não bloqueia quem paga).
    r = client.post(
        "/api/leads/999999/negotiate", headers=_headers(EXPIRED_TOKEN)
    )
    assert r.status_code != 402, r.text


# ------------------------------------------------------------ admin sessions


@pytest.fixture(scope="module")
def admin_ids(client):
    admin_id = _user(ADMIN_EMAIL, ADMIN_TOKEN)
    victim_id = _user(VICTIM_EMAIL, VICTIM_TOKEN)
    assert db_service._service.set_user_admin(ADMIN_EMAIL, True) is True
    # Sessão com rótulo conhecido para localizar na listagem.
    db_service._service.create_user_session(
        victim_id, _hash_token("pytest-sessions-victim-2"), "Pytest Revogável", "10.0.0.9"
    )
    return admin_id, victim_id


def test_admin_lists_active_sessions(client, admin_ids):
    r = client.get("/api/admin/sessions", headers=_headers(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    sessions = r.json()["sessions"]
    assert any(s["device_info"] == "Pytest Revogável" for s in sessions)


def test_non_admin_cannot_list_sessions(client):
    r = client.get("/api/admin/sessions", headers=_headers(VICTIM_TOKEN))
    assert r.status_code == 403, r.text


def test_admin_revokes_session_and_token_dies(client, admin_ids):
    _, victim_id = admin_ids
    r = client.get("/api/admin/sessions", headers=_headers(ADMIN_TOKEN))
    target = next(
        s for s in r.json()["sessions"]
        if s["user_id"] == victim_id and s["device_info"] == "Pytest Revogável"
    )

    r = client.delete(f"/api/admin/sessions/{target['id']}", headers=_headers(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    assert r.json()["revoked"] is True

    # A linha revogada desaparece da listagem.
    r = client.get("/api/admin/sessions", headers=_headers(ADMIN_TOKEN))
    assert all(s["id"] != target["id"] for s in r.json()["sessions"])

    # Revogar TODAS as sessões do utilizador mata o token em uso.
    r = client.delete(
        f"/api/admin/users/{victim_id}/sessions", headers=_headers(ADMIN_TOKEN)
    )
    assert r.status_code == 200, r.text
    assert r.json()["revoked_count"] >= 1

    r = client.get("/api/auth/me", headers=_headers(VICTIM_TOKEN))
    assert r.status_code == 401, r.text


def test_admin_revoke_unknown_session_is_404(client, admin_ids):
    r = client.delete("/api/admin/sessions/999999", headers=_headers(ADMIN_TOKEN))
    assert r.status_code == 404, r.text

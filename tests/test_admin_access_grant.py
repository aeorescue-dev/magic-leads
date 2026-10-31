"""Concessão manual de acesso (cortesia) — backend, auditoria e gate A5.

Cobre:
  * lookup por e-mail;
  * grant somando dias (nunca encurta) em conta expirada e ativa;
  * validação de dias/motivo/nota;
  * idempotência;
  * revogação segura (409 se a expiração mudou);
  * copy "Acesso ativo até" vs "Renova em";
  * o gate A5 aceita o utilizador concedido e volta a bloquear após revogar.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from backend.main import _hash_token, app
from backend.services.db import db_service, get_connection

ADMIN_EMAIL = "pytest-grant-admin@magicleads.app"
ADMIN_TOKEN = "pytest-grant-admin-token"
TARGET_EMAIL = "pytest-grant-target@magicleads.app"
TARGET_TOKEN = "pytest-grant-target-token"


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _ensure_user(email: str, token: str, *, admin: bool = False) -> int:
    svc = db_service._service
    user = svc.get_user_by_email(email) or svc.create_user(
        email, "pytest-hash", "Pytest Grant", plan="free"
    )
    try:
        svc.create_user_session(user["id"], _hash_token(token), "Pytest", None)
    except Exception:
        pass
    if admin:
        svc.set_user_admin(email, True)
    return user["id"]


@pytest.fixture(scope="module")
def users(client):
    admin_id = _ensure_user(ADMIN_EMAIL, ADMIN_TOKEN, admin=True)
    target_id = _ensure_user(TARGET_EMAIL, TARGET_TOKEN)
    return admin_id, target_id


def _expire(user_id: int) -> None:
    conn = get_connection()
    try:
        past = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        conn.execute(
            "UPDATE users SET subscription_status='expired', plan='free', plan_until=? WHERE id=?",
            (past, user_id),
        )
        conn.commit()
    finally:
        conn.close()


def _set_until(user_id: int, days_from_now: int) -> str:
    until = datetime.now(timezone.utc) + timedelta(days=days_from_now)
    value = until.replace(tzinfo=None).isoformat()
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE users SET subscription_status='active', plan='pro', plan_until=? WHERE id=?",
            (value, user_id),
        )
        conn.commit()
    finally:
        conn.close()
    return value


def _grant(client, email=TARGET_EMAIL, days=7, reason="support", note=None, key=None):
    body = {"email": email, "days": days, "reason": reason}
    if note:
        body["note"] = note
    if key:
        body["idempotency_key"] = key
    return client.post("/api/admin/access/grant", headers=_headers(ADMIN_TOKEN), json=body)


# ---------------------------------------------------------------- lookup


def test_lookup_requires_admin(client, users):
    assert client.get("/api/admin/users/lookup?email=x@y.com").status_code == 401
    r = client.get(
        "/api/admin/users/lookup?email=x@y.com", headers=_headers(TARGET_TOKEN)
    )
    assert r.status_code == 403


def test_lookup_returns_user_and_access(client, users):
    _expire(users[1])
    r = client.get(
        f"/api/admin/users/lookup?email={TARGET_EMAIL.upper()}",
        headers=_headers(ADMIN_TOKEN),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user"]["email"] == TARGET_EMAIL
    assert body["access"]["can_access"] is False


def test_lookup_unknown_email_is_404(client, users):
    r = client.get(
        "/api/admin/users/lookup?email=nope@magicleads.app",
        headers=_headers(ADMIN_TOKEN),
    )
    assert r.status_code == 404


# ---------------------------------------------------------------- grant


def test_grant_expired_account_activates_and_audits(client, users):
    admin_id, target_id = users
    _expire(target_id)
    r = _grant(client, days=7)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["after"]["subscription_status"] == "active"
    assert body["after"]["plan"] == "pro"
    assert body["audit_id"] > 0

    status = db_service._service.get_user_subscription_status(target_id)
    assert status["can_access"] is True
    assert status["access_source"] == "admin_grant"
    assert status["message"].startswith("Acesso ativo até")

    entries = client.get(
        "/api/admin/access/audit", headers=_headers(ADMIN_TOKEN)
    ).json()["entries"]
    row = next(e for e in entries if e["id"] == body["audit_id"])
    assert row["admin_user_id"] == admin_id
    assert row["target_email"] == TARGET_EMAIL
    assert row["days"] == 7
    assert row["reason"] == "support"
    assert row["reversible"] is True


def test_grant_sums_days_on_active_plan_without_shortening(client, users):
    _, target_id = users
    until = datetime.fromisoformat(_set_until(target_id, 20))
    r = _grant(client, days=7)
    assert r.status_code == 200, r.text
    after = datetime.fromisoformat(r.json()["after"]["plan_until"])
    assert after > until + timedelta(days=6)
    assert after < until + timedelta(days=8)


def test_grant_validation(client, users):
    assert _grant(client, days=0).status_code == 422
    assert _grant(client, days=400).status_code == 422
    assert _grant(client, reason="hacker").status_code == 400
    assert _grant(client, reason="other").status_code == 400
    assert _grant(client, reason="other", note="ticket 1").status_code == 200
    assert _grant(client, email="ghost@magicleads.app").status_code == 404


def test_grant_is_idempotent(client, users):
    _, target_id = users
    _expire(target_id)
    key = str(uuid.uuid4())
    first = _grant(client, days=3, key=key)
    assert first.status_code == 200
    second = _grant(client, days=3, key=key)
    assert second.status_code == 200
    assert second.json().get("duplicate") is True
    assert second.json()["audit_id"] == first.json()["audit_id"]

    # A expiração corresponde a UMA concessão de 3 dias, não duas (6).
    after = datetime.fromisoformat(first.json()["after"]["plan_until"])
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    assert timedelta(days=2) < after - now < timedelta(days=4)


def test_grant_to_admin_is_allowed_but_flags_alert(client, users):
    admin_id = users[0]
    _expire(admin_id)
    r = _grant(client, email=ADMIN_EMAIL, days=3)
    assert r.status_code == 200, r.text
    # O alerta de watchdog é gravado na tabela de auditoria de anomalias.
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT code FROM system_alerts WHERE code='ADMIN_ACCESS_GRANT' "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()
        assert row is not None
    finally:
        conn.close()


# ---------------------------------------------------------------- revoke


def test_revoke_restores_previous_state_and_blocks_double_revoke(client, users):
    _, target_id = users
    _expire(target_id)
    grant = _grant(client, days=7).json()

    r = client.post(
        "/api/admin/access/revoke",
        headers=_headers(ADMIN_TOKEN),
        json={"audit_id": grant["audit_id"], "reason": "engano"},
    )
    assert r.status_code == 200, r.text
    status = db_service._service.get_user_subscription_status(target_id)
    assert status["can_access"] is False

    again = client.post(
        "/api/admin/access/revoke",
        headers=_headers(ADMIN_TOKEN),
        json={"audit_id": grant["audit_id"]},
    )
    assert again.status_code == 409


def test_revoke_refuses_when_expiry_changed_since_grant(client, users):
    _, target_id = users
    _expire(target_id)
    grant = _grant(client, days=7).json()
    # Simula um pagamento posterior (Stripe) que estende a expiração.
    db_service._service.extend_access(target_id, days=7)

    r = client.post(
        "/api/admin/access/revoke",
        headers=_headers(ADMIN_TOKEN),
        json={"audit_id": grant["audit_id"]},
    )
    assert r.status_code == 409, r.text
    # O acesso pago não foi destruído.
    assert db_service._service.get_user_subscription_status(target_id)["can_access"] is True


# ---------------------------------------------------------------- gate A5


def test_granted_user_passes_a5_and_revoke_restores_402(client, users):
    _, target_id = users
    _expire(target_id)
    _grant(client, days=3)

    for path in (
        "/api/leads/999999/contact",
        "/api/leads/999999/negotiate",
        "/api/leads/999999/convert",
    ):
        r = client.post(
            path, headers=_headers(TARGET_TOKEN), json={"channel": "sms"}
        )
        assert r.status_code != 402, f"{path} devolveu 402 com acesso concedido"

    grant_id = client.get(
        "/api/admin/access/audit", headers=_headers(ADMIN_TOKEN)
    ).json()["entries"][0]["id"]
    assert client.post(
        "/api/admin/access/revoke",
        headers=_headers(ADMIN_TOKEN),
        json={"audit_id": grant_id},
    ).status_code == 200

    r = client.post(
        "/api/leads/999999/negotiate", headers=_headers(TARGET_TOKEN)
    )
    assert r.status_code == 402, r.text
    assert r.json()["detail"]["action"] == "REDIRECT_TO_CHECKOUT"


# ---------------------------------------------------------------- copy


def test_expiry_copy_falls_back_after_stripe_renewal(client, users):
    _, target_id = users
    _expire(target_id)
    _grant(client, days=7)
    assert db_service._service.get_user_subscription_status(target_id)[
        "message"
    ].startswith("Acesso ativo até")

    # Renovação posterior (Stripe) muda plan_until -> copy volta ao normal.
    db_service._service.extend_access(target_id, days=30)
    status = db_service._service.get_user_subscription_status(target_id)
    assert status["access_source"] == "subscription"
    assert status["message"].startswith("Plano ativo. Renova em")

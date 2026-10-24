"""Sprint 1 — "Parar de perder dinheiro" (backend).

Dois bugs que custam dinheiro em silencio:

1.4  Webhook Stripe: o evento era gravado ANTES de o acesso ser concedido.
     Se o `extend_access` falhasse, o retry do Stripe via o evento como
     "ja' processado" -> **o cliente pagava e nao recebia acesso**.

1.5  Mensagens presas em 'sending': o claim atomico acontece antes do envio; se
     o processo morresse a meio, a mensagem ficava em 'sending' PARA SEMPRE
     (credito de enriquecimento gasto, e-mail nunca enviado, sem aviso).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.services.db import db_service, get_connection

STRIPE_SECRET = "sk_test_fake_para_o_sprint1"
WEBHOOK_SECRET = "whsec_fake_para_o_sprint1"


# ---------------------------------------------------------------- 1.4 webhook


def _stripe_signature(payload: bytes, secret: str) -> str:
    """Assinatura Stripe v1 (HMAC-SHA256 hex do "<ts>.<payload>")."""
    import hashlib
    import hmac

    ts = int(datetime.now(timezone.utc).timestamp())
    signed = f"{ts}.{payload.decode('utf-8')}"
    sig = hmac.new(
        secret.encode("utf-8"), msg=signed.encode("utf-8"), digestmod=hashlib.sha256
    ).hexdigest()
    return f"t={ts},v1={sig}"


@pytest.fixture()
def stripe_env(monkeypatch):
    monkeypatch.setattr("backend.main.settings.STRIPE_API_KEY", STRIPE_SECRET, raising=False)
    monkeypatch.setattr(
        "backend.main.settings.STRIPE_WEBHOOK_SECRET", WEBHOOK_SECRET, raising=False
    )


def _completed_event(user_id: int, event_id: str = "evt_sprint1_1") -> dict:
    return {
        "id": event_id,
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_sprint1",
                "metadata": {"user_id": str(user_id)},
                "client_reference_id": str(user_id),
                "customer": "cus_test_sprint1",
            }
        },
    }


def _register_user(email: str = "sprint1-billing@magicleads.app") -> int:
    from backend.services.security import hash_password

    svc = db_service._service
    user = svc.create_user(email, hash_password("Sprint1Senha!"), "Sprint1 Co", plan="free")
    assert user is not None
    return user["id"]


def test_webhook_grants_access_when_event_is_new(stripe_env):
    """Caminho feliz: o acesso e' concedido e o evento fica como 'granted'."""
    user_id = _register_user()
    event = _completed_event(user_id)
    payload = json.dumps(event).encode("utf-8")
    sig = _stripe_signature(payload, WEBHOOK_SECRET)

    with TestClient(app) as client:
        r = client.post(
            "/api/stripe/webhook",
            content=payload,
            headers={
                "Stripe-Signature": sig,
                "Content-Type": "application/json",
            },
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("handled") is True, body

    row = db_service._service.get_stripe_event(event["id"])
    assert row is not None
    assert int(row["granted"]) == 1, "o evento deve ficar marcado como concedido"

    user = db_service._service.get_user_by_id(user_id)
    assert user["plan"] == "pro"
    assert user["plan_until"] is not None


def test_webhook_retries_grant_when_previous_attempt_failed(stripe_env, monkeypatch):
    """REGRESSAO DO BUG: o acesso tem de ser concedido no retry.

    Antes, o evento era gravado antes do `extend_access`; um crash a meio
    deixava o evento como "ja' processado" e o retry do Stripe nao concedia
    nada -> o cliente pagava e nao recebia acesso.
    """
    user_id = _register_user("sprint1-retry@magicleads.app")
    event = _completed_event(user_id, "evt_sprint1_retry")
    payload = json.dumps(event).encode("utf-8")
    sig = _stripe_signature(payload, WEBHOOK_SECRET)

    # Simula o estado deixado pela 1a tentativa: evento visto, sem efeito.
    db_service._service.record_stripe_event(
        event["id"], "checkout.session.completed", user_id, granted=0
    )
    row = db_service._service.get_stripe_event(event["id"])
    assert int(row["granted"]) == 0, "pre-condicao: o evento nao foi concedido"

    with TestClient(app) as client:
        r = client.post(
            "/api/stripe/webhook",
            content=payload,
            headers={
                "Stripe-Signature": sig,
                "Content-Type": "application/json",
            },
        )
    assert r.status_code == 200, r.text
    assert r.json().get("handled") is True, r.json()

    user = db_service._service.get_user_by_id(user_id)
    assert user["plan"] == "pro", "o retry tem de conceder o acesso"
    assert user["plan_until"] is not None

    row = db_service._service.get_stripe_event(event["id"])
    assert int(row["granted"]) == 1


def test_webhook_is_idempotent_after_grant(stripe_env):
    """Depois de concedido, o mesmo evento nao volta a estender o acesso."""
    user_id = _register_user("sprint1-idem@magicleads.app")
    event = _completed_event(user_id, "evt_sprint1_idem")
    payload = json.dumps(event).encode("utf-8")
    sig = _stripe_signature(payload, WEBHOOK_SECRET)

    with TestClient(app) as client:
        for _ in range(2):
            r = client.post(
                "/api/stripe/webhook",
                content=payload,
                headers={
                    "Stripe-Signature": sig,
                    "Content-Type": "application/json",
                },
            )
            assert r.status_code == 200, r.text
        second = r.json()
    assert second.get("idempotent") is True, second

    user = db_service._service.get_user_by_id(user_id)
    first_until = user["plan_until"]

    # Um terceiro pedido nao pode estender mais 7 dias.
    with TestClient(app) as client:
        r = client.post(
            "/api/stripe/webhook",
            content=payload,
            headers={"Stripe-Signature": sig, "Content-Type": "application/json"},
        )
    assert r.json().get("idempotent") is True
    user2 = db_service._service.get_user_by_id(user_id)
    assert user2["plan_until"] == first_until, "o acesso nao pode ser concedido duas vezes"


def test_webhook_without_user_id_is_ignored(stripe_env):
    """Evento sem user_id nao concede nada (fail-closed)."""
    event = {
        "id": "evt_sprint1_no_user",
        "type": "checkout.session.completed",
        "data": {"object": {"id": "cs_x", "metadata": {}}},
    }
    payload = json.dumps(event).encode("utf-8")
    sig = _stripe_signature(payload, WEBHOOK_SECRET)

    with TestClient(app) as client:
        r = client.post(
            "/api/stripe/webhook",
            content=payload,
            headers={"Stripe-Signature": sig, "Content-Type": "application/json"},
        )
    assert r.status_code == 200
    assert r.json().get("handled") is False


# ---------------------------------------------------------------- 1.5 reaper


def test_claim_sets_claimed_at():
    """O claim atomico regista `claimed_at` (para o reaper saber ha quanto tempo)."""
    conn = get_connection()
    try:
        conn.execute("DELETE FROM outbound_messages")
        cur = conn.execute(
            "INSERT INTO outbound_messages (batch_id, contact_id, city, channel, to_email, "
            "subject, body_hash, status) "
            "VALUES (NULL, NULL, 'BOSTON', 'email', 'reaper@test.local', 's', 'h', 'queued')"
        )
        mid = cur.lastrowid
        conn.commit()
    finally:
        conn.close()

    assert db_service._service.claim_outbound_message(mid) is True
    row = db_service._service.get_outbound_message(mid)
    assert row["status"] == "sending"
    assert row["claimed_at"] is not None, "sem claimed_at o reaper nao sabe a idade"

    # Segundo claim: ja' nao esta' 'queued' -> falso.
    assert db_service._service.claim_outbound_message(mid) is False


def test_reaper_fails_messages_stuck_in_sending():
    """Mensagens presas em 'sending' ha mais de X minutos -> 'failed'."""
    conn = get_connection()
    try:
        conn.execute("DELETE FROM outbound_messages")
        old = (
            datetime.now(timezone.utc) - timedelta(minutes=60)
        ).strftime("%Y-%m-%d %H:%M:%S")
        recent = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        cur = conn.execute(
            "INSERT INTO outbound_messages (batch_id, contact_id, city, channel, to_email, "
            "subject, body_hash, status, claimed_at, next_step_at) "
            "VALUES (NULL, NULL, 'BOSTON', 'email', 'old@test.local', 's', 'h', "
            "'sending', ?, '2030-01-01 00:00:00')",
            (old,),
        )
        old_id = cur.lastrowid
        cur = conn.execute(
            "INSERT INTO outbound_messages (batch_id, contact_id, city, channel, to_email, "
            "subject, body_hash, status, claimed_at) "
            "VALUES (NULL, NULL, 'BOSTON', 'email', 'recent@test.local', 's', 'h', "
            "'sending', ?)",
            (recent,),
        )
        recent_id = cur.lastrowid
        conn.commit()
    finally:
        conn.close()

    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=15)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    n = db_service._service.fail_stale_sending_outbound_messages(cutoff)
    assert n == 1, "so' a mensagem antiga deve ser limpa"

    old_row = db_service._service.get_outbound_message(old_id)
    assert old_row["status"] == "failed"
    assert "stale sending claim" in (old_row["error"] or "")
    # A sequencia continua agendada.
    assert old_row["next_step_at"] == "2030-01-01 00:00:00"

    recent_row = db_service._service.get_outbound_message(recent_id)
    assert recent_row["status"] == "sending", "uma mensagem em curso nao pode ser limpa"

    assert db_service._service.count_stale_sending_outbound_messages(cutoff) == 0


def test_reaper_does_not_touch_queued_messages():
    """O reaper so' toca em 'sending' — a fila normal fica intacta."""
    conn = get_connection()
    try:
        conn.execute("DELETE FROM outbound_messages")
        conn.execute(
            "INSERT INTO outbound_messages (batch_id, contact_id, city, channel, to_email, "
            "subject, body_hash, status) "
            "VALUES (NULL, NULL, 'BOSTON', 'email', 'queued@test.local', 's', 'h', 'queued')"
        )
        conn.commit()
    finally:
        conn.close()

    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=15)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    assert db_service._service.fail_stale_sending_outbound_messages(cutoff) == 0
    rows = db_service._service.list_queued_outbound_messages(limit=10)
    assert any(r["to_email"] == "queued@test.local" for r in rows)

"""B2: push por ofício, digest, onboarding e push de ciclo de vida."""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from backend.services import alert_planner, lifecycle_push
from backend.services.alert_planner import plan_and_dispatch
from backend.services.db import db_service, get_connection
from backend.services.push_service import push_service


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _daytime(monkeypatch):
    monkeypatch.setattr(alert_planner, "_is_quiet_hours", lambda now=None: False)
    monkeypatch.setattr(lifecycle_push, "_is_quiet_hours", lambda now=None: False)


def _reset():
    conn = get_connection()
    try:
        for table in (
            "alert_usage",
            "notifications",
            "user_interests",
            "lead_history",
            "leads",
            "users",
            "push_subscriptions",
            "push_deliveries",
        ):
            conn.execute(f"DELETE FROM {table}")
        conn.commit()
    finally:
        conn.close()


def _user(interests=("Roof",), *, push=True, digest=1, lifecycle=0, active=True) -> int:
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO users (email, password_hash, company_name, plan, "
            "subscription_status, plan_until, locale, push_enabled, "
            "digest_enabled, lifecycle_push_enabled) "
            "VALUES (?, 'x', 'B2 Co', 'pro', ?, ?, 'pt', ?, ?, ?)",
            (
                f"b2_{uuid.uuid4().hex[:10]}@test.com",
                "active" if active else "expired",
                (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()
                if active
                else (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
                1 if push else 0,
                digest,
                lifecycle,
            ),
        )
        uid = int(cur.lastrowid)
        for cat in interests:
            conn.execute(
                "INSERT INTO user_interests (user_id, category) VALUES (?, ?)",
                (uid, cat),
            )
        conn.commit()
        return uid
    finally:
        conn.close()


def _lead(category="Roof", *, city="NYC", source_type="311") -> dict:
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO leads (external_id, source_type, address, city, state, "
            "issue_category, date_reported, case_status) "
            "VALUES (?, ?, ?, ?, 'NY', ?, ?, 'Open')",
            (
                f"b2-{uuid.uuid4().hex[:10]}",
                source_type,
                f"{uuid.uuid4().hex[:6]} MAIN STREET",
                city,
                category,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()
        return {"id": int(cur.lastrowid)}
    finally:
        conn.close()


def _fake_push(calls):
    async def fake(user_id, payload, kind="custom", **kwargs):
        calls.append({"user_id": user_id, "payload": payload, "kind": kind, **kwargs})
        return 1

    return fake


# ---------------------------------------------------------------------------
# Push por ofício
# ---------------------------------------------------------------------------

def test_category_bell_off_keeps_inapp_skips_push(monkeypatch):
    _reset()
    uid = _user(("Roof", "Plumbing"))
    assert db_service._service.set_user_interest_push(uid, "Roof", False) is True

    calls = []
    monkeypatch.setattr(push_service, "send_to_user", _fake_push(calls))

    report = _run(plan_and_dispatch([_lead("Roof")]))

    assert report.created == 1
    assert report.cat_push_suppressed == 1
    assert report.pushed == 0
    assert calls == []

    # O in-app continua a existir.
    conn = get_connection()
    try:
        n = conn.execute(
            "SELECT COUNT(*) FROM notifications WHERE user_id = ? AND type = 'new_lead'",
            (uid,),
        ).fetchone()[0]
    finally:
        conn.close()
    assert n == 1


def test_editing_interests_preserves_bell_state():
    _reset()
    uid = _user(("Roof", "Plumbing"))
    db_service._service.set_user_interest_push(uid, "Roof", False)

    # Reconfigurar a selecao (Roof + Paint) nao pode religar o Roof.
    assert db_service._service.set_user_interests(uid, ["Roof", "Paint"]) is True
    settings = {
        s["category"]: s["push_enabled"]
        for s in db_service._service.get_user_interest_settings(uid)
    }
    assert settings == {"Roof": False, "Paint": True}


def test_category_bell_on_pushes(monkeypatch):
    _reset()
    _user(("Roof",))
    calls = []
    monkeypatch.setattr(push_service, "send_to_user", _fake_push(calls))

    report = _run(plan_and_dispatch([_lead("Roof")]))

    assert report.pushed == 1
    assert report.cat_push_suppressed == 0
    assert len(calls) == 1


# ---------------------------------------------------------------------------
# Digest
# ---------------------------------------------------------------------------

def test_digest_disabled_skips_digest_push(monkeypatch):
    _reset()
    # Sem interesses: nao ha alerta individual, o caminho e' o digest.
    _user((), digest=0)
    calls = []
    monkeypatch.setattr(push_service, "send_to_user", _fake_push(calls))

    report = _run(plan_and_dispatch([_lead("Roof")]))

    assert report.unconfigured_digest == 0
    assert [c["kind"] for c in calls] == []


def test_digest_enabled_sends_one_push(monkeypatch):
    _reset()
    uid = _user((), digest=1)
    _add_device(uid)
    calls = []
    monkeypatch.setattr(push_service, "send_to_user", _fake_push(calls))

    report = _run(plan_and_dispatch([_lead("Roof")]))

    assert report.unconfigured_digest == 1
    assert [c["kind"] for c in calls if c["kind"] == "digest"] == ["digest"]


def test_digest_does_not_duplicate_push_when_batch_runs(monkeypatch):
    _reset()
    uid = _user(("Roof",), digest=1)
    calls = []
    monkeypatch.setattr(push_service, "send_to_user", _fake_push(calls))

    report = _run(plan_and_dispatch([_lead("Roof")]))

    assert report.digest == 0
    assert len([c for c in calls if c["user_id"] == uid]) == 1


# ---------------------------------------------------------------------------
# Onboarding
# ---------------------------------------------------------------------------

def _add_device(uid: int, endpoint: str = None):
    db_service._service.add_push_subscription(
        uid, endpoint or f"https://push.example/{uuid.uuid4().hex[:8]}", "p", "a"
    )


def test_onboarding_only_for_users_without_interests(monkeypatch):
    _reset()
    no_interests = _user((), push=True)
    _add_device(no_interests)
    with_interests = _user(("Roof",), push=True)
    _add_device(with_interests)

    calls = []
    monkeypatch.setattr(push_service, "send_to_user", _fake_push(calls))

    sent = _run(alert_planner.dispatch_interests_onboarding())

    assert sent == 1
    assert [c["user_id"] for c in calls] == [no_interests]
    assert calls[0]["kind"] == "onboarding"
    assert "ofícios" in calls[0]["payload"]["title"]


def test_onboarding_is_sent_only_once(monkeypatch):
    _reset()
    uid = _user((), push=True)
    _add_device(uid)

    calls = []
    monkeypatch.setattr(push_service, "send_to_user", _fake_push(calls))

    assert _run(alert_planner.dispatch_interests_onboarding()) == 1
    assert _run(alert_planner.dispatch_interests_onboarding()) == 0
    assert len(calls) == 1


def test_onboarding_ignores_expired_subscription(monkeypatch):
    _reset()
    uid = _user((), push=True, active=False)
    _add_device(uid)

    calls = []
    monkeypatch.setattr(push_service, "send_to_user", _fake_push(calls))

    assert _run(alert_planner.dispatch_interests_onboarding()) == 0
    assert calls == []


def test_onboarding_respects_quiet_hours(monkeypatch):
    _reset()
    uid = _user((), push=True)
    _add_device(uid)
    monkeypatch.setattr(alert_planner, "_is_quiet_hours", lambda now=None: True)

    calls = []
    monkeypatch.setattr(push_service, "send_to_user", _fake_push(calls))

    assert _run(alert_planner.dispatch_interests_onboarding()) == 0
    assert calls == []


def test_onboarding_endpoint_for_no_interests_keeps_no_individual_alerts(monkeypatch):
    """Nicho estrito: o onboarding nao pode reabrir alertas individuais."""
    _reset()
    _user((), push=True)
    calls = []
    monkeypatch.setattr(push_service, "send_to_user", _fake_push(calls))

    report = _run(plan_and_dispatch([_lead("Roof")]))

    assert report.created == 0
    assert report.audience == 0


# ---------------------------------------------------------------------------
# Lifecycle push
# ---------------------------------------------------------------------------

def _lifecycle_notice(uid: int, ntype="reveal_followup", lead_id=1) -> int:
    row = db_service._service.add_notification_for_user(
        uid, ntype, "Aviso", "Mensagem", lead_id=lead_id
    )
    return int(row["id"])


def test_lifecycle_push_requires_opt_in(monkeypatch):
    _reset()
    uid = _user(("Roof",), lifecycle=0)
    _add_device(uid)
    _lifecycle_notice(uid)

    calls = []
    monkeypatch.setattr(push_service, "send_to_user", _fake_push(calls))

    assert _run(lifecycle_push.dispatch_lifecycle_pushes()) == 0
    assert calls == []


def test_lifecycle_push_sends_when_opted_in(monkeypatch):
    _reset()
    uid = _user(("Roof",), lifecycle=1)
    _add_device(uid)
    nid = _lifecycle_notice(uid)

    calls = []
    monkeypatch.setattr(push_service, "send_to_user", _fake_push(calls))

    assert _run(lifecycle_push.dispatch_lifecycle_pushes()) == 1
    assert calls[0]["kind"] == "lifecycle"
    assert calls[0]["payload"]["nid"] == nid
    assert calls[0]["payload"]["sig"]

    conn = get_connection()
    try:
        pushed = conn.execute(
            "SELECT pushed_at FROM notifications WHERE id = ?", (nid,)
        ).fetchone()["pushed_at"]
    finally:
        conn.close()
    assert pushed


def test_lifecycle_push_is_idempotent(monkeypatch):
    _reset()
    uid = _user(("Roof",), lifecycle=1)
    _add_device(uid)
    _lifecycle_notice(uid)

    calls = []
    monkeypatch.setattr(push_service, "send_to_user", _fake_push(calls))

    assert _run(lifecycle_push.dispatch_lifecycle_pushes()) == 1
    assert _run(lifecycle_push.dispatch_lifecycle_pushes()) == 0
    assert len(calls) == 1


def test_lifecycle_quiet_hours_only_allows_urgent(monkeypatch):
    _reset()
    uid = _user(("Roof",), lifecycle=1)
    _add_device(uid)
    _lifecycle_notice(uid, "reveal_followup", 1)
    urgent = _lifecycle_notice(uid, "reveal_urgent", 2)
    monkeypatch.setattr(lifecycle_push, "_is_quiet_hours", lambda now=None: True)

    calls = []
    monkeypatch.setattr(push_service, "send_to_user", _fake_push(calls))

    assert _run(lifecycle_push.dispatch_lifecycle_pushes()) == 1
    assert calls[0]["payload"]["nid"] == urgent
    assert calls[0]["urgency"] == "high"
    assert calls[0]["payload"]["requireInteraction"] is True


def test_lifecycle_skips_expired_user(monkeypatch):
    _reset()
    uid = _user(("Roof",), lifecycle=1, active=False)
    _add_device(uid)
    _lifecycle_notice(uid)

    calls = []
    monkeypatch.setattr(push_service, "send_to_user", _fake_push(calls))

    # A query filtra push_enabled/acesso via JOIN? Se nao filtrar, o envio
    # continua a ser barrado pelo proprio send_to_user; aqui garantimos que o
    # aviso nao e' consumido para um utilizador sem acesso.
    assert _run(lifecycle_push.dispatch_lifecycle_pushes()) == 0
    assert calls == []


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

def test_preferences_and_bell_endpoints(monkeypatch):
    from fastapi.testclient import TestClient

    from backend.main import app

    _reset()
    uid = _user(("Roof", "Plumbing"), lifecycle=0)
    client = TestClient(app)

    from backend.main import _get_current_user

    app.dependency_overrides[_get_current_user] = lambda: {
        "id": uid,
        "email": "b2@test.com",
        "subscription_status": "active",
        "plan_until": (datetime.now(timezone.utc) + timedelta(days=5)).isoformat(),
        "plan": "pro",
        "locale": "pt",
    }
    try:
        r = client.patch(
            f"/api/users/{uid}/interests/Roof/push", json={"enabled": False}
        )
        assert r.status_code == 200
        settings = {s["category"]: s["push_enabled"] for s in r.json()["settings"]}
        assert settings == {"Plumbing": True, "Roof": False}

        r = client.get(f"/api/users/{uid}/interests/push")
        assert r.status_code == 200
        assert len(r.json()["settings"]) == 2

        r = client.patch(
            f"/api/users/{uid}/push-preferences",
            json={"digest_enabled": False, "lifecycle_push_enabled": True},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["digest_enabled"] is False
        assert body["lifecycle_push_enabled"] is True

        r = client.patch(
            "/api/users/999999/interests/Roof/push", json={"enabled": True}
        )
        assert r.status_code in (403, 404)
    finally:
        app.dependency_overrides.clear()

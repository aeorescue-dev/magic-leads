"""B1: clique (HMAC), coalescência, min-gap e higiene de dispositivos."""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from backend.services import alert_planner
from backend.services.alert_planner import plan_and_dispatch
from backend.services.db import db_service, get_connection
from backend.services.push_click import sign_click, verify_click
from backend.services.push_service import push_service


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _daytime(monkeypatch):
    monkeypatch.setattr(alert_planner, "_is_quiet_hours", lambda now=None: False)


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


def _user(interests=("Roof",), *, push=True, gap=30) -> int:
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO users (email, password_hash, company_name, plan, "
            "subscription_status, plan_until, locale, push_enabled, push_min_gap_min) "
            "VALUES (?, 'x', 'B1 Co', 'pro', 'active', ?, 'pt', ?, ?)",
            (
                f"b1_{uuid.uuid4().hex[:10]}@test.com",
                (datetime.now(timezone.utc) + timedelta(days=5)).isoformat(),
                1 if push else 0,
                gap,
            ),
        )
        uid = int(cur.lastrowid)
        for cat in interests:
            conn.execute(
                "INSERT INTO user_interests (user_id, category) VALUES (?, ?)", (uid, cat)
            )
        conn.commit()
        return uid
    finally:
        conn.close()


def _lead(category="Roof", *, city="NYC", source_type="311", case_status="Open") -> dict:
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO leads (external_id, source_type, address, city, state, "
            "issue_category, date_reported, case_status) "
            "VALUES (?, ?, ?, ?, 'NY', ?, ?, ?)",
            (
                f"b1-{uuid.uuid4().hex[:10]}",
                source_type,
                f"{uuid.uuid4().hex[:6]} MAIN STREET",
                city,
                category,
                datetime.now(timezone.utc).isoformat(),
                case_status,
            ),
        )
        conn.commit()
        return {"id": int(cur.lastrowid)}
    finally:
        conn.close()


def _fake_push(calls, *, accepted=True):
    async def fake(user_id, payload, kind="custom", **kwargs):
        calls.append({"user_id": user_id, "payload": payload, "kind": kind, **kwargs})
        return 1 if accepted else 0

    return fake


# ---------------------------------------------------------------------------
# Clique HMAC
# ---------------------------------------------------------------------------

def test_click_signature_and_endpoint():
    from fastapi.testclient import TestClient

    from backend.main import app

    _reset()
    uid = _user()
    row = db_service._service.add_notification_for_user(
        uid, "new_lead", "t", "m"
    )
    nid = int(row["id"])
    assert verify_click(nid, sign_click(nid)) is True
    assert verify_click(nid, "deadbeef") is False

    client = TestClient(app)
    bad = client.get(f"/api/push/click?nid={nid}&sig=deadbeef")
    assert bad.status_code == 403

    ok = client.get(f"/api/push/click?nid={nid}&sig={sign_click(nid)}")
    assert ok.status_code == 200
    assert ok.json()["recorded"] is True

    conn = get_connection()
    try:
        clicked = conn.execute(
            "SELECT clicked_at FROM notifications WHERE id = ?", (nid,)
        ).fetchone()["clicked_at"]
    finally:
        conn.close()
    assert clicked


# ---------------------------------------------------------------------------
# Coalescência
# ---------------------------------------------------------------------------

def test_two_leads_become_one_batch_push(monkeypatch):
    _reset()
    uid = _user(("Roof", "Plumbing"))
    calls = []
    monkeypatch.setattr(push_service, "send_to_user", _fake_push(calls))

    report = _run(plan_and_dispatch([_lead("Roof"), _lead("Plumbing")]))

    assert report.created == 2
    assert report.pushed == 1
    assert report.batched == 1
    assert len(calls) == 1
    payload = calls[0]["payload"]
    assert "2 novas oportunidades" in payload["title"]
    assert payload["batch"] == 2
    assert payload["actions"][0]["title"] == "Ver oportunidades"
    assert payload["nid"] and payload["sig"]


def test_single_lead_stays_individual(monkeypatch):
    _reset()
    _user(("Roof",))
    calls = []
    monkeypatch.setattr(push_service, "send_to_user", _fake_push(calls))

    report = _run(plan_and_dispatch([_lead("Roof")]))

    assert report.pushed == 1
    assert report.batched == 0
    assert "Chamado aberto" in calls[0]["payload"]["title"]
    assert calls[0]["payload"]["actions"][0]["title"] == "Ver lead"


def test_quiet_batch_keeps_only_legal(monkeypatch):
    _reset()
    _user(("Roof", "Plumbing"))
    calls = []
    monkeypatch.setattr(push_service, "send_to_user", _fake_push(calls))
    monkeypatch.setattr(alert_planner, "_is_quiet_hours", lambda now=None: True)

    report = _run(plan_and_dispatch([
        _lead("Roof", source_type="311"),
        _lead("Plumbing", source_type="hpd_violation"),
    ]))

    assert len(calls) == 1
    assert "Obrigação legal" in calls[0]["payload"]["title"]
    assert report.quiet_suppressed == 1


# ---------------------------------------------------------------------------
# Min-gap
# ---------------------------------------------------------------------------

def test_min_gap_suppresses_push_but_keeps_inapp(monkeypatch):
    _reset()
    uid = _user(("Roof",), gap=30)
    db_service._service.add_notification_for_user(
        uid, "new_lead", "anterior", "anterior"
    )
    calls = []
    monkeypatch.setattr(push_service, "send_to_user", _fake_push(calls))

    report = _run(plan_and_dispatch([_lead("Roof")]))

    assert report.created == 1
    assert report.pushed == 0
    assert report.gap_suppressed == 1
    assert calls == []


# ---------------------------------------------------------------------------
# Higiene de dispositivos
# ---------------------------------------------------------------------------

def test_max_five_devices_and_progress_marks():
    _reset()
    uid = _user()
    for i in range(6):
        db_service._service.add_push_subscription(
            uid, f"https://push.example/{i}", "p", "a", "UA", f"Device {i}"
        )

    active = db_service._service.get_user_push_subscriptions(uid)
    assert len(active) == 5
    assert all(s["device_label"] for s in active)

    conn = get_connection()
    try:
        disabled = conn.execute(
            "SELECT COUNT(*) FROM push_subscriptions WHERE user_id = ? AND disabled_at IS NOT NULL",
            (uid,),
        ).fetchone()[0]
    finally:
        conn.close()
    assert disabled == 1


def test_prune_keeps_most_recent_device():
    _reset()
    uid = _user()
    db_service._service.add_push_subscription(uid, "https://push.example/old", "p", "a")
    db_service._service.add_push_subscription(uid, "https://push.example/new", "p", "a")

    conn = get_connection()
    try:
        conn.execute(
            "UPDATE push_subscriptions SET last_success_at = datetime('now','-100 days') "
            "WHERE endpoint = 'https://push.example/old'"
        )
        conn.commit()
    finally:
        conn.close()

    assert db_service._service.prune_push_subscriptions(90) == 1
    active = db_service._service.get_user_push_subscriptions(uid)
    assert [s["endpoint"] for s in active] == ["https://push.example/new"]


def test_mark_push_success_updates_device():
    _reset()
    uid = _user()
    endpoint = "https://push.example/ok"
    db_service._service.add_push_subscription(uid, endpoint, "p", "a")
    db_service._service.mark_push_success(endpoint)
    active = db_service._service.get_user_push_subscriptions(uid)
    assert active[0]["last_success_at"] is not None


# ---------------------------------------------------------------------------
# Broadcast respeita opt-out
# ---------------------------------------------------------------------------

def test_broadcast_respects_push_disabled(monkeypatch):
    _reset()
    uid = _user(push=False)
    db_service._service.add_push_subscription(uid, "https://push.example/off", "p", "a")

    calls = []

    async def fake_single(sub, payload, kind="custom", **kwargs):
        calls.append(sub["endpoint"])
        return True

    monkeypatch.setattr(push_service, "_configured", True)
    monkeypatch.setattr(push_service, "_send_single", fake_single)

    sent = _run(push_service.send_to_all({"title": "x", "body": "y"}))
    assert sent == 0
    assert calls == []


# ---------------------------------------------------------------------------
# Admin: cliques/CTR
# ---------------------------------------------------------------------------

def test_admin_push_metrics_has_clicks_and_ctr():
    _reset()
    uid = _user()
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO push_deliveries (outcome, attempts, user_id, kind, notification_id, clicked_at) "
            "VALUES ('accepted', 1, ?, 'lead_alert', 10, CURRENT_TIMESTAMP)",
            (uid,),
        )
        conn.execute(
            "INSERT INTO push_deliveries (outcome, attempts, user_id, kind, notification_id) "
            "VALUES ('accepted', 1, ?, 'lead_alert', 11)",
            (uid,),
        )
        conn.commit()
    finally:
        conn.close()

    metrics = db_service._service.admin_get_push_metrics(7, 10)
    assert metrics["totals"]["clicks"] == 1
    assert metrics["ctr"] is not None
    assert metrics["live_subscriptions"] >= 0

"""B3: A/B do copy do digest (atribuicao, render e medicao de CTR)."""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from backend.services import alert_planner
from backend.services.alert_planner import _digest_variant, plan_and_dispatch
from backend.services.db import db_service, get_connection
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


def _user(interests=()) -> int:
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO users (email, password_hash, company_name, plan, "
            "subscription_status, plan_until, locale, push_enabled) "
            "VALUES (?, 'x', 'B3 Co', 'pro', 'active', ?, 'pt', 1)",
            (
                f"b3_{uuid.uuid4().hex[:10]}@test.com",
                (datetime.now(timezone.utc) + timedelta(days=5)).isoformat(),
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


def _lead(category="Roof") -> dict:
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO leads (external_id, source_type, address, city, state, "
            "issue_category, date_reported, case_status) "
            "VALUES (?, '311', ?, 'NYC', 'NY', ?, ?, 'Open')",
            (
                f"b3-{uuid.uuid4().hex[:10]}",
                f"{uuid.uuid4().hex[:6]} AB STREET",
                category,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()
        return {"id": int(cur.lastrowid)}
    finally:
        conn.close()


def test_variant_is_stable_and_balanced():
    assert _digest_variant(1) == "b"
    assert _digest_variant(2) == "a"
    assert _digest_variant(101) == "b"
    assert _digest_variant(102) == "a"
    assert _digest_variant("abc") == "a"  # entrada invalida nunca rebenta

    buckets = [_digest_variant(i) for i in range(2, 102)]
    assert buckets.count("a") == 50
    assert buckets.count("b") == 50


def test_variant_b_uses_alternative_copy():
    _reset()
    uid = _user()
    row = db_service._service.upsert_daily_digest(uid, 3, locale="pt", variant="b")
    assert row["ab_variant"] == "b"
    assert row["msg_key"] == "digest_b"
    assert "oportunidades perto de si" in row["title"]
    assert "reservados primeiro" in row["message"]


def test_variant_a_is_the_neutral_default():
    _reset()
    uid = _user()
    row = db_service._service.upsert_daily_digest(uid, 3, locale="pt")
    assert row["ab_variant"] == "a"
    assert row["msg_key"] == "digest"
    assert "Resumo diário" in row["title"]


def test_variant_is_locked_on_first_digest_of_day():
    """Um segundo run com a variante oposta nao troca o braco medido."""
    _reset()
    uid = _user()
    first = db_service._service.upsert_daily_digest(uid, 2, locale="pt", variant="a")
    second = db_service._service.upsert_daily_digest(uid, 2, locale="pt", variant="b")
    assert second["id"] == first["id"]
    assert second["ab_variant"] == "a"
    assert second["msg_key"] == "digest"
    # O contador acumula: 2 + 2.
    import json

    assert json.loads(second["msg_params"])["n"] == 4


def test_planner_digest_records_variant(monkeypatch):
    _reset()
    # id par -> braco A; sem interesses para cair no digest.
    uid = _user()
    if uid % 2:  # pragma: no cover - garante o braco A
        uid = _user()
    db_service._service.add_push_subscription(
        uid, f"https://push.example/{uuid.uuid4().hex[:8]}", "p", "a"
    )
    calls = []

    async def fake(user_id, payload, kind="custom", **kwargs):
        calls.append({"user_id": user_id, "payload": payload, "kind": kind})
        return 1

    monkeypatch.setattr(push_service, "send_to_user", fake)
    _run(plan_and_dispatch([_lead("Roof")]))

    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT ab_variant, msg_key FROM notifications WHERE user_id = ? AND type='digest'",
            (uid,),
        ).fetchone()
    finally:
        conn.close()
    expected = "a" if uid % 2 == 0 else "b"
    assert row["ab_variant"] == expected
    assert row["msg_key"] == ("digest_b" if expected == "b" else "digest")
    assert calls and calls[0]["kind"] == "digest"


def _seed_digest(uid: int, variant: str, pushed: int, clicks: int):
    conn = get_connection()
    try:
        for i in range(pushed):
            conn.execute(
                "INSERT INTO notifications (user_id, type, title, message, msg_key, "
                "msg_params, ab_variant, pushed_at, clicked_at) "
                "VALUES (?, 'digest', 't', 'm', 'digest', '{}', ?, CURRENT_TIMESTAMP, "
                "CASE WHEN ? > 0 THEN CURRENT_TIMESTAMP ELSE NULL END)",
                (uid, variant, 1 if i < clicks else 0),
            )
        conn.commit()
    finally:
        conn.close()


def test_admin_ab_requires_minimum_sample():
    _reset()
    uid = _user()
    _seed_digest(uid, "a", pushed=10, clicks=5)
    _seed_digest(uid, "b", pushed=10, clicks=8)

    data = db_service._service.admin_get_digest_ab(30)
    by_variant = {a["variant"]: a for a in data["arms"]}
    assert by_variant["a"]["ctr"] == 0.5
    assert by_variant["b"]["ctr"] == 0.8
    assert all(not a["sample_ok"] for a in data["arms"])
    assert data["leader"] is None  # sem 30/braco nao se declara vencedor


def test_admin_ab_declares_leader_with_enough_samples():
    _reset()
    uid = _user()
    _seed_digest(uid, "a", pushed=40, clicks=8)   # 20%
    _seed_digest(uid, "b", pushed=40, clicks=18)  # 45%

    data = db_service._service.admin_get_digest_ab(30)
    assert data["leader"] == "b"
    assert {a["variant"]: a["sample_ok"] for a in data["arms"]} == {"a": True, "b": True}


def test_admin_ab_ignores_old_digests():
    _reset()
    uid = _user()
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO notifications (user_id, type, title, message, msg_key, "
            "msg_params, ab_variant, pushed_at, created_at) "
            "VALUES (?, 'digest', 't', 'm', 'digest', '{}', 'b', CURRENT_TIMESTAMP, "
            "datetime('now','-90 days'))",
            (uid,),
        )
        conn.commit()
    finally:
        conn.close()

    data = db_service._service.admin_get_digest_ab(30)
    assert data["arms"] == []

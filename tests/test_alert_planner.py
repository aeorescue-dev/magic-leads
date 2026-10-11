"""Alert Planner: teto diário, fair-equal, rotação e orçamento combinado.

Os testes de `select_fair` blindam a função pura (distribuição, rotação e
ordenação). Os testes end-to-end cobrem o teto, o digest do excedente, o
orçamento combinado (in-app + push contam 1) e o filtro de qualidade.
"""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

from backend.services.alert_planner import plan_and_dispatch, select_fair
from backend.services.db import db_service, get_connection
from backend.services.push_service import push_service


def _run(coro):
    return asyncio.run(coro)


def _future(days: int = 5) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _reset() -> None:
    conn = get_connection()
    try:
        for table in ("alert_usage", "notifications", "user_interests",
                      "system_alerts", "leads", "users"):
            conn.execute(f"DELETE FROM {table}")
        conn.commit()
    finally:
        conn.close()


def _user(interests=None, email=None) -> int:
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO users (email, password_hash, company_name, plan, "
            "subscription_status, plan_until) VALUES (?, ?, ?, ?, ?, ?)",
            (
                email or f"planner_{uuid.uuid4().hex[:10]}@test.com",
                "not-a-real-hash",
                "Test Co",
                "pro",
                "active",
                _future(),
            ),
        )
        uid = cur.lastrowid
        for cat in interests or []:
            conn.execute(
                "INSERT OR IGNORE INTO user_interests (user_id, category) VALUES (?, ?)",
                (uid, cat),
            )
        conn.commit()
        return uid
    finally:
        conn.close()


def _lead(category="Roof", city="NYC", date_reported=None,
          case_status="open", owner_name=None) -> dict:
    date_reported = date_reported or datetime.now(timezone.utc).isoformat()
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO leads (external_id, source_type, address, city, state, "
            "issue_category, date_reported, case_status, owner_name) "
            "VALUES (?, '311', ?, ?, 'NY', ?, ?, ?, ?)",
            (
                f"ext-{uuid.uuid4().hex[:10]}",
                f"{uuid.uuid4().hex[:6]} Test St",
                city,
                category,
                date_reported,
                case_status,
                owner_name,
            ),
        )
        conn.commit()
        return {
            "id": cur.lastrowid,
            "issue_category": category,
            "address": "1 Test St",
            "city": city,
            "date_reported": date_reported,
            "case_status": case_status,
            "owner_name": owner_name,
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# select_fair (função pura)
# ---------------------------------------------------------------------------

def test_select_fair_distributes_equally():
    cat_map = {"Roof": [{"id": 1}, {"id": 2}], "Paint": [{"id": 3}, {"id": 4}]}
    selected, overflow = select_fair(cat_map, 4, 0)
    assert len(selected) == 4
    assert overflow == 0
    cats = [c for c, _ in selected]
    assert cats.count("Roof") == 2 and cats.count("Paint") == 2


def test_select_fair_rotates_category_order():
    cat_map = {"Roof": [{"id": 1}], "Paint": [{"id": 2}]}
    s0, _ = select_fair(cat_map, 1, 0)
    s1, _ = select_fair(cat_map, 1, 1)
    assert s0[0][0] == "Paint"   # ordem alfabética com cursor 0
    assert s1[0][0] == "Roof"    # o cursor alterna o topo da fila


def test_select_fair_orders_by_freshness_then_open():
    cat_map = {"Roof": [
        {"id": 1, "date_reported": "2020-01-01", "case_status": "closed"},
        {"id": 2, "date_reported": "2026-01-01", "case_status": "open"},
        {"id": 3, "date_reported": "2026-01-01", "case_status": "closed"},
    ]}
    selected, _ = select_fair(cat_map, 1, 0)
    assert selected[0][1]["id"] == 2  # mais fresco e aberto primeiro


def test_select_fair_overflow_when_budget_smaller():
    cat_map = {"Roof": [{"id": 1}, {"id": 2}, {"id": 3}]}
    selected, overflow = select_fair(cat_map, 1, 0)
    assert len(selected) == 1
    assert overflow == 2


def test_select_fair_cursor_zero_keeps_freshness_order():
    cat_map = {"Roof": [
        {"id": 1, "date_reported": "2020-01-01"},
        {"id": 2, "date_reported": "2026-01-01"},
    ]}
    selected, _ = select_fair(cat_map, 1, 0)
    assert selected[0][1]["id"] == 2


# ---------------------------------------------------------------------------
# plan_and_dispatch (end-to-end)
# ---------------------------------------------------------------------------

def test_fair_distribution_across_categories():
    _reset()
    uid = _user(["Roof", "Paint"])
    l_roof = _lead("Roof", "NYC")
    l_paint = _lead("Paint", "NYC")

    report = _run(plan_and_dispatch([l_roof, l_paint]))
    assert report.created == 2
    assert report.audience == 1

    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT lead_id FROM notifications WHERE user_id = ? AND type = 'new_lead'",
            (uid,),
        ).fetchall()
    finally:
        conn.close()
    assert {r["lead_id"] for r in rows} == {l_roof["id"], l_paint["id"]}


def test_cap_exhausted_produces_digest_not_alert():
    _reset()
    uid = _user(["Roof"])
    db_service._service.increment_alert_usage(uid, "Roof", 6)  # teto esgotado

    report = _run(plan_and_dispatch([_lead("Roof", "NYC")]))
    assert report.created == 0
    assert report.audience == 1   # elegível existe (não é bloqueio de fluxo)

    conn = get_connection()
    try:
        n = conn.execute(
            "SELECT COUNT(*) AS c FROM notifications "
            "WHERE user_id = ? AND type = 'digest'",
            (uid,),
        ).fetchone()["c"]
    finally:
        conn.close()
    assert n == 1


def test_combined_budget_counts_once_with_push_disabled(monkeypatch):
    _reset()
    uid = _user(["Roof"])

    calls = []

    async def fake_push(user_id, payload, kind="custom"):
        calls.append(user_id)
        return 1

    monkeypatch.setattr(push_service, "send_to_user", fake_push)

    report = _run(plan_and_dispatch([_lead("Roof", "NYC")]))
    assert report.created == 1
    assert report.pushed == 0
    assert calls == []  # push desabilitado: só in-app

    usage = db_service._service.get_alert_usage_today(_today())
    assert usage[uid]["Roof"] == 1
    assert sum(usage[uid].values()) == 1  # push não somou uma segunda unidade


def test_push_sent_once_when_enabled(monkeypatch):
    _reset()
    uid = _user(["Roof"])
    db_service._service.set_user_push_enabled(uid, True)

    calls = []

    async def fake_push(user_id, payload, kind="custom"):
        calls.append((user_id, kind))
        return 1

    monkeypatch.setattr(push_service, "send_to_user", fake_push)

    report = _run(plan_and_dispatch([_lead("Roof", "NYC")]))
    assert report.created == 1
    assert report.pushed == 1
    assert calls == [(uid, "lead_alert")]


def test_cursor_advances_after_dispatch():
    _reset()
    uid = _user(["Roof"])
    _run(plan_and_dispatch([_lead("Roof", "NYC")]))
    assert db_service._service.get_alert_rotation_cursor(uid) == 1


def test_institutional_lead_is_skipped():
    _reset()
    _user(["Roof"])
    lead = _lead("Roof", "NYC", owner_name="NYC HOUSING AUTHORITY")
    report = _run(plan_and_dispatch([lead]))
    assert report.created == 0
    assert report.audience == 0

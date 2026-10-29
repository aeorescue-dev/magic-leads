"""Alert Engine v2: gate semântico, nicho estrito, quiet hours, distância e payload."""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from backend.services import alert_planner
from backend.services.alert_planner import (
    _build_push_payload,
    _distance_miles,
    _is_quiet_hours,
    plan_and_dispatch,
    select_fair,
)
from backend.services.db import db_service, get_connection
from backend.services.push_service import push_service


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _daytime(monkeypatch):
    """Por omissao os testes correm fora do silencio; os testes de quiet
    hours sobrepoem este patch explicitamente."""
    monkeypatch.setattr(alert_planner, "_is_quiet_hours", lambda now=None: False)


def _future(days: int = 5) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def _reset() -> None:
    conn = get_connection()
    try:
        for table in (
            "alert_usage",
            "notifications",
            "user_interests",
            "lead_history",
            "leads",
            "users",
            "searchbug_calls",
        ):
            conn.execute(f"DELETE FROM {table}")
        conn.commit()
    finally:
        conn.close()


def _user(interests=None, *, email=None, locale="pt", push_enabled=False,
          base=None, base_source="gps", show_address=True) -> int:
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO users (email, password_hash, company_name, plan, "
            "subscription_status, plan_until, locale, push_enabled, show_address_in_push, "
            "base_lat, base_lng, base_source, base_label) "
            "VALUES (?, 'x', 'Test Co', 'pro', 'active', ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                email or f"v2_{uuid.uuid4().hex[:10]}@test.com",
                _future(),
                locale,
                1 if push_enabled else 0,
                1 if show_address else 0,
                base[0] if base else None,
                base[1] if base else None,
                base_source if base else None,
                "Base" if base else None,
            ),
        )
        uid = int(cur.lastrowid)
        for cat in interests or []:
            conn.execute(
                "INSERT OR IGNORE INTO user_interests (user_id, category) VALUES (?, ?)",
                (uid, cat),
            )
        conn.commit()
        return uid
    finally:
        conn.close()


def _lead(
    category="Roof",
    city="NYC",
    *,
    source_type="311",
    case_status="Open",
    date_reported=None,
    owner_name=None,
    lat=None,
    lng=None,
    repeat_365=None,
) -> dict:
    date_reported = date_reported or datetime.now(timezone.utc).isoformat()
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO leads (external_id, source_type, address, city, state, "
            "issue_category, date_reported, case_status, owner_name, lat, lng) "
            "VALUES (?, ?, ?, ?, 'NY', ?, ?, ?, ?, ?, ?)",
            (
                f"ext-{uuid.uuid4().hex[:10]}",
                source_type,
                f"{uuid.uuid4().hex[:6]} MAIN STREET",
                city,
                category,
                date_reported,
                case_status,
                owner_name,
                lat,
                lng,
            ),
        )
        lead_id = int(cur.lastrowid)
        if repeat_365 is not None:
            conn.execute(
                "INSERT INTO lead_history (lead_id, repeat_365, open_cases, oldest_open_days) "
                "VALUES (?, ?, 1, 3)",
                (lead_id, repeat_365),
            )
        conn.commit()
        return {"id": lead_id}
    finally:
        conn.close()


def _notifications(uid, ntype="new_lead"):
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM notifications WHERE user_id = ? AND type = ?",
            (uid, ntype),
        ).fetchall()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Gate semântico
# ---------------------------------------------------------------------------

def test_gate_skips_closed_institutional_and_stale():
    _reset()
    _user(["Roof"])
    fresh = _lead()
    closed = _lead(case_status="Completed")
    institutional = _lead(owner_name="NYC HOUSING AUTHORITY")
    stale = _lead(date_reported=(datetime.now(timezone.utc) - timedelta(days=3)).isoformat())

    report = _run(plan_and_dispatch([fresh, closed, institutional, stale]))

    assert report.candidates == 1
    assert report.created == 1


def test_gate_allows_old_lead_when_recurring():
    _reset()
    _user(["Roof"])
    old_recurring = _lead(
        date_reported=(datetime.now(timezone.utc) - timedelta(days=10)).isoformat(),
        repeat_365=4,
    )

    report = _run(plan_and_dispatch([old_recurring]))

    assert report.candidates == 1
    assert report.created == 1


def test_legal_obligation_passes_gate():
    _reset()
    _user(["Roof"])
    legal = _lead(source_type="hpd_violation", case_status="Open")

    report = _run(plan_and_dispatch([legal]))

    assert report.candidates == 1
    assert report.created == 1


# ---------------------------------------------------------------------------
# Nicho estrito
# ---------------------------------------------------------------------------

def test_user_without_interests_gets_no_individual_alert():
    _reset()
    uid = _user([])  # nunca configurou
    report = _run(plan_and_dispatch([_lead()]))

    assert report.created == 0
    assert report.audience == 0
    assert _notifications(uid) == []


def test_user_with_other_interest_gets_no_cross_category_alert():
    _reset()
    uid = _user(["Paint"])
    report = _run(plan_and_dispatch([_lead("Rodent")]))

    assert report.created == 0
    assert _notifications(uid) == []


# ---------------------------------------------------------------------------
# Quiet hours
# ---------------------------------------------------------------------------

def test_quiet_hours_window_ny():
    # 2026-10-29 e' EDT (UTC-4): 01:00Z = 21:00 NY; 12:00Z = 08:00 NY.
    assert _is_quiet_hours(datetime(2026, 10, 29, 0, 59, tzinfo=timezone.utc)) is False
    assert _is_quiet_hours(datetime(2026, 10, 29, 1, 0, tzinfo=timezone.utc)) is True
    assert _is_quiet_hours(datetime(2026, 10, 29, 11, 59, tzinfo=timezone.utc)) is True
    assert _is_quiet_hours(datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)) is False


def test_quiet_suppresses_311_push_but_not_legal(monkeypatch):
    _reset()
    uid = _user(["Roof", "Plumbing"], push_enabled=True)
    monkeypatch.setattr(alert_planner, "_is_quiet_hours", lambda now=None: True)

    sent = []

    async def fake_push(user_id, payload, kind="custom", **kwargs):
        sent.append((payload["signalType"], kwargs.get("urgency"), kwargs.get("ttl")))
        return 1

    monkeypatch.setattr(push_service, "send_to_user", fake_push)

    _run(plan_and_dispatch([
        _lead("Roof", source_type="311"),
        _lead("Plumbing", source_type="hpd_violation"),
    ]))

    assert [s[0] for s in sent] == ["legal_obligation"]
    assert sent[0][1] == "high"
    assert sent[0][2] == 14400


def test_quiet_skips_digest(monkeypatch):
    _reset()
    uid = _user(["Roof"], push_enabled=True)
    db_service._service.increment_alert_usage(uid, "Roof", 6)
    monkeypatch.setattr(alert_planner, "_is_quiet_hours", lambda now=None: True)

    report = _run(plan_and_dispatch([_lead("Roof")]))

    assert report.created == 0
    assert report.digest == 0
    assert _notifications(uid, "digest") == []


# ---------------------------------------------------------------------------
# Distância: informa e ordena, nunca filtra
# ---------------------------------------------------------------------------

def test_distance_orders_near_first_but_keeps_far_lead():
    near = {"id": 1, "date_reported": "2026-10-29T10:00:00", "lat": 40.70, "lng": -73.90}
    far = {"id": 2, "date_reported": "2026-10-29T10:00:00", "lat": 41.30, "lng": -74.20}
    base = (40.71, -73.95)

    selected, overflow = select_fair({"Roof": [far, near]}, 2, 0, base=base)

    assert overflow == 0
    assert [ld["id"] for _, ld in selected] == [1, 2]

    # Um lead a ~28 mi continua elegivel: nunca ha filtro por raio.
    assert _distance_miles(base, far) > 20


def test_distance_missing_coords_is_none():
    assert _distance_miles((40.71, -73.95), {"lat": None, "lng": None}) is None
    assert _distance_miles(None, {"lat": 40.0, "lng": -73.0}) is None


# ---------------------------------------------------------------------------
# Payload v2
# ---------------------------------------------------------------------------

def test_payload_has_labels_distance_actions_and_confidence():
    lead = {
        "id": 7,
        "external_id": "ext-7",
        "address": "4112 W NORTH AVE",
        "city": "Chicago",
        "date_reported": "2026-10-27T12:00:00",
        "oldest_open_days": 12,
        "repeat_365": 3,
        "phone_verified": 0,
        "lat": 41.9,
        "lng": -87.7,
    }
    payload = _build_push_payload(
        lead, "Roof", "legal_obligation", "pt", 2.3, True, 72, True
    )

    assert "Obrigação legal" in payload["title"]
    assert "Telhado" in payload["title"]
    assert "4112 W NORTH AVE" in payload["body"]
    assert "2,3 mi" in payload["body"]
    assert "72%" in payload["body"]
    assert [a["action"] for a in payload["actions"]] == ["open", "dismiss"]
    assert payload["occurrence"] == "ext-7"
    assert "occ_7_ext-7" == payload["tag"]
    assert payload["requireInteraction"] is True


def test_payload_hides_address_when_privacy_off():
    lead = {
        "id": 8,
        "external_id": "ext-8",
        "address": "500 SECRET STREET",
        "city": "NYC",
        "date_reported": "2026-10-28T12:00:00",
        "phone_verified": 0,
    }
    payload = _build_push_payload(lead, "Paint", "open_request", "en", None, False, None, False)

    assert "SECRET" not in payload["body"]
    assert "near you" in payload["body"]
    assert "phone on request" in payload["body"]
    assert payload["requireInteraction"] is False


# ---------------------------------------------------------------------------
# Base / privacidade (DB)
# ---------------------------------------------------------------------------

def test_base_location_and_privacy_roundtrip():
    _reset()
    uid = _user(["Roof"])

    assert db_service._service.set_user_base_location(uid, 40.7128, -74.006, "gps", "Casa")
    user = db_service._service.get_user_by_id(uid)
    assert user["base_lat"] == 40.713
    assert user["base_source"] == "gps"

    assert db_service._service.set_show_address_in_push(uid, False)
    assert db_service._service.get_user_by_id(uid)["show_address_in_push"] == 0

    assert db_service._service.clear_user_base_location(uid)
    assert db_service._service.get_user_by_id(uid)["base_lat"] is None


def test_base_location_and_privacy_api():
    from fastapi.testclient import TestClient

    from backend.main import _hash_token, app

    _reset()
    uid = _user(["Roof"])
    token = "v2-base-token"
    db_service._service.create_user_session(uid, _hash_token(token), "Pytest", None)
    headers = {"Authorization": f"Bearer {token}"}
    client = TestClient(app)

    put = client.put(
        f"/api/users/{uid}/base-location",
        json={"lat": 40.71284, "lng": -74.00601, "source": "gps", "label": "Casa"},
        headers=headers,
    )
    assert put.status_code == 200, put.text
    assert put.json()["base_lat"] == 40.713
    assert put.json()["base_source"] == "gps"

    patch = client.patch(
        f"/api/users/{uid}/push-preferences",
        json={"show_address_in_push": False},
        headers=headers,
    )
    assert patch.status_code == 200, patch.text
    assert patch.json()["show_address_in_push"] is False

    me = client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["base_label"] == "Casa"
    assert me.json()["show_address_in_push"] is False

    delete = client.delete(f"/api/users/{uid}/base-location", headers=headers)
    assert delete.status_code == 200
    assert delete.json()["base_lat"] is None

"""Fundação de dados do Alert Planner.

Cobre o orçamento diário (alert_usage), o cursor de rotação, o seeding
idempotente a partir de notificações já enviadas e o digest localizado.
"""

import json
import uuid
from datetime import datetime, timezone

from backend.config import settings
from backend.services.db import db_service, get_connection
from backend.services.translations import DEFAULT_LOCALE, render


def _mk_user() -> int:
    email = f"alert_{uuid.uuid4().hex[:10]}@test.com"
    return db_service._service.create_user(email, "x", "Test Co")["id"]


def _mk_lead(category: str = "pothole") -> int:
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO leads (external_id, source_type, address, city, state, issue_category, date_reported) "
            "VALUES (?, '311', ?, 'Springfield', 'IL', ?, ?)",
            (uuid.uuid4().hex, f"{uuid.uuid4().hex[:8]} Main St", category, "2026-01-01"),
        )
        conn.commit()
        return conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    finally:
        conn.close()


def test_increment_alert_usage_upsert_and_day_isolation():
    uid = _mk_user()
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    db_service._service.increment_alert_usage(uid, "pothole")
    db_service._service.increment_alert_usage(uid, "pothole")
    db_service._service.increment_alert_usage(uid, "graffiti")

    usage = db_service._service.get_alert_usage_today(day)
    assert usage[uid]["pothole"] == 2
    assert usage[uid]["graffiti"] == 1
    # outro dia não contamina
    assert uid not in db_service._service.get_alert_usage_today("2000-01-01")


def test_seed_is_idempotent_and_counts_existing_alerts():
    uid = _mk_user()
    # dia sintético e isolado: o guard de idempotência é global por dia
    day = "2020-05-05"
    lid1 = _mk_lead("pothole")
    lid2 = _mk_lead("pothole")
    conn = get_connection()
    try:
        for lid in (lid1, lid2):
            conn.execute(
                "INSERT INTO notifications (user_id, type, title, message, lead_id, created_at) "
                "VALUES (?, 'new_lead', 't', 'm', ?, ?)",
                (uid, lid, f"{day} 10:00:00"),
            )
        conn.commit()
    finally:
        conn.close()

    db_service._service.seed_alert_usage_from_notifications(day)
    usage = db_service._service.get_alert_usage_today(day)
    assert usage[uid]["pothole"] == 2

    # segunda chamada não semeia de novo (idempotente)
    db_service._service.seed_alert_usage_from_notifications(day)
    usage2 = db_service._service.get_alert_usage_today(day)
    assert usage2[uid]["pothole"] == 2


def test_rotation_cursor_defaults_zero_and_advances():
    uid = _mk_user()
    assert db_service._service.get_alert_rotation_cursor(uid) == 0
    assert db_service._service.advance_alert_rotation_cursor(uid) == 1
    assert db_service._service.advance_alert_rotation_cursor(uid, 2) == 3
    assert db_service._service.get_alert_rotation_cursor(uid) == 3


def test_digest_is_localized_and_accumulates():
    uid = _mk_user()
    limit = settings.PUSH_DAILY_LIMIT
    expected = render("digest", DEFAULT_LOCALE, n=3, limit=limit)

    first = db_service._service.upsert_daily_digest(uid, 3)
    assert first["type"] == "digest"
    assert first["msg_key"] == "digest"
    assert first["title"] == expected["title"]

    second = db_service._service.upsert_daily_digest(uid, 2)
    params = json.loads(second["msg_params"])
    assert params["n"] == 5
    assert params["limit"] == limit


def test_render_returns_localized_pair():
    pt = render("digest", "pt", n=4, limit=6)
    assert pt and "4" in pt["message"] and "6" in pt["message"]
    es = render("digest", "es", n=1, limit=6)
    assert es and "1" in es["message"]
    assert render("does_not_exist", "en") is None

"""Fila intercalada 50/50 por origem do e-mail (KPI do OSINT)."""
from __future__ import annotations

from backend.services.db import db_service, get_connection


def _clean():
    conn = get_connection()
    try:
        conn.execute("DELETE FROM outbound_messages")
        conn.execute("DELETE FROM outbound_contacts")
        conn.commit()
    finally:
        conn.close()


def _seed(source: str, email: str, queued: bool = True):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO outbound_contacts (email, city, email_source, email_status) "
            "VALUES (?, 'NYC', ?, 'valid')",
            (email, source),
        )
        cid = conn.execute(
            "SELECT id FROM outbound_contacts WHERE email=?", (email,)
        ).fetchone()["id"]
        conn.execute(
            "INSERT INTO outbound_messages (contact_id, city, to_email, subject, "
            "body_hash, status, sent_at) VALUES (?, 'NYC', ?, 's', 'h', ?, "
            "CASE WHEN ? THEN NULL ELSE CURRENT_TIMESTAMP END)",
            (cid, email, "queued" if queued else "sent", 1 if queued else 0),
        )
        conn.commit()
    finally:
        conn.close()


def test_fila_intercala_origens_quando_ha_as_duas():
    _clean()
    _seed("owner_osint", "a@balance-test.com")
    _seed("owner_osint", "b@balance-test.com")
    _seed("smtp_pattern", "c@balance-test.com")
    _seed("smtp_pattern", "d@balance-test.com")
    order = [
        m["email_source"]
        for m in db_service._service.list_queued_outbound_messages_balanced(10)
    ]
    assert order == ["owner_osint", "smtp_pattern", "owner_osint", "smtp_pattern"]
    _clean()


def test_sem_as_duas_origens_mantem_fifo():
    _clean()
    _seed("smtp_pattern", "e@balance-test.com")
    _seed("smtp_pattern", "f@balance-test.com")
    rows = db_service._service.list_queued_outbound_messages_balanced(10)
    assert [m["to_email"] for m in rows] == [
        "e@balance-test.com", "f@balance-test.com",
    ]
    _clean()

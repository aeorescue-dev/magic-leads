"""Metricas outbound: envios, falhas, bounce, respostas e taxa positiva."""
from __future__ import annotations

from fastapi.testclient import TestClient

from backend.main import app
from backend.services.db import db_service, get_connection

MAILBOX = "metrics-test@example.com"


def _clean():
    conn = get_connection()
    try:
        conn.execute("DELETE FROM outbound_messages WHERE to_email LIKE '%@metrics-test.com'")
        conn.execute("DELETE FROM outbound_contacts WHERE email LIKE '%@metrics-test.com'")
        conn.execute("DELETE FROM mailbox_bounce_events WHERE email LIKE '%@metrics-test.com'")
        conn.execute("DELETE FROM sending_mailboxes WHERE email=?", (MAILBOX,))
        conn.commit()
    finally:
        conn.close()


def test_endpoint_exige_admin():
    client = TestClient(app)
    assert client.get("/api/admin/outbound/metrics").status_code in (401, 403)
    assert client.post(
        "/api/admin/outbound/reply-sentiment?contact_id=1&sentiment=positive"
    ).status_code in (401, 403)


def test_metricas_por_caixa_e_totais():
    _clean()
    svc = db_service._service
    svc.upsert_sending_mailbox(
        email=MAILBOX, provider="gmail", transport="gmail_api", daily_cap=5, enabled=1
    )
    box = [m for m in svc.list_sending_mailboxes(enabled_only=False) if m["email"] == MAILBOX][0]
    conn = get_connection()
    try:
        for i in range(4):
            conn.execute(
                "INSERT INTO outbound_messages (mailbox_id, city, to_email, subject, "
                "status, sent_at) VALUES (?, 'NYC', ?, 's', 'sent', CURRENT_TIMESTAMP)",
                (box["id"], f"sent{i}@metrics-test.com"),
            )
        conn.execute(
            "INSERT INTO outbound_messages (mailbox_id, city, to_email, subject, status) "
            "VALUES (?, 'NYC', 'fail@metrics-test.com', 's', 'failed')",
            (box["id"],),
        )
        conn.execute(
            "INSERT INTO mailbox_bounce_events (mailbox_id, email, kind) VALUES (?, ?, 'bounce')",
            (box["id"], "sent0@metrics-test.com"),
        )
        conn.execute(
            "INSERT INTO outbound_contacts (email, city, email_source, replied_at, reply_sentiment) "
            "VALUES ('sent0@metrics-test.com', 'NYC', 'smtp_pattern', CURRENT_TIMESTAMP, 'positive')"
        )
        conn.execute(
            "INSERT INTO outbound_contacts (email, city, email_source, replied_at) "
            "VALUES ('sent1@metrics-test.com', 'NYC', 'smtp_pattern', CURRENT_TIMESTAMP)"
        )
        c0 = conn.execute(
            "SELECT id FROM outbound_contacts WHERE email='sent0@metrics-test.com'"
        ).fetchone()["id"]
        c1 = conn.execute(
            "SELECT id FROM outbound_contacts WHERE email='sent1@metrics-test.com'"
        ).fetchone()["id"]
        conn.execute(
            "UPDATE outbound_messages SET contact_id=? WHERE to_email='sent0@metrics-test.com'",
            (c0,),
        )
        conn.execute(
            "UPDATE outbound_messages SET contact_id=? WHERE to_email='sent1@metrics-test.com'",
            (c1,),
        )
        conn.commit()
        contact_id = c0
    finally:
        conn.close()

    data = svc.outbound_metrics(30)
    row = next(m for m in data["mailboxes"] if m["email"] == MAILBOX)
    assert row["sent"] == 4
    assert row["failed"] == 1
    assert row["bounced"] == 1
    assert row["replies"] == 2
    assert row["positive"] == 1
    assert row["bounce_rate"] == 0.25
    assert row["reply_rate"] == 0.5
    assert row["positive_rate"] == 0.25

    assert data["totals"]["sent"] >= 4
    assert data["totals"]["replies"] >= 2
    assert data["totals"]["positive"] >= 1

    # Origem do e-mail: o KPI que mede o impacto do OSINT do dono.
    by_source = {row["source"]: row for row in data["by_email_source"]}
    assert "smtp_pattern" in by_source
    assert by_source["smtp_pattern"]["contacts"] >= 2
    assert by_source["smtp_pattern"]["replies"] >= 2

    # Classificacao manual da resposta (KPI de positivas).
    assert svc.set_contact_reply_sentiment(contact_id, "positive") is True
    assert svc.set_contact_reply_sentiment(contact_id, "bogus") is True
    conn = get_connection()
    try:
        value = conn.execute(
            "SELECT reply_sentiment FROM outbound_contacts WHERE id=?", (contact_id,)
        ).fetchone()["reply_sentiment"]
    finally:
        conn.close()
    assert value is None  # valor invalido limpa, nunca grava lixo

    _clean()

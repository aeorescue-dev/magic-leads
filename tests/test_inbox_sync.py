"""Testes do inbox sync (parsers) e do alerta proativo.

Nao tocam na rede: classificam payloads Gmail sinteticos, reproduzindo os
formatos reais de bounce (DSN), reclamacao (ARF) e resposta.
"""
from __future__ import annotations

import base64

from backend.services import inbox_sync as ib


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode()


def _payload(headers: dict[str, str], body: str = "") -> dict:
    return {
        "headers": [{"name": k, "value": v} for k, v in headers.items()],
        "body": {"data": _b64(body)} if body else {},
        "parts": [],
    }


BOUNCE_HEADERS = {
    "From": "Mail Delivery Subsystem <mailer-daemon@googlemail.com>",
    "Subject": "Delivery Status Notification (Failure)",
    "Content-Type": 'multipart/report; report-type=delivery-status',
}

BOUNCE_BODY = """
Reporting-MTA: dns; googlemail.com
Final-Recipient: rfc822; info@skender.com
Action: failed
Status: 5.1.1
Diagnostic-Code: smtp; 550 5.1.1 user unknown
"""

COMPLAINT_HEADERS = {
    "From": "complainant@example.com",
    "Subject": "Spam report",
    "Content-Type": "message/feedback-report",
}

COMPLAINT_BODY = """
Feedback-Type: abuse
Original-Rcpt-To: rfc822; sales@deljoheating.com
"""


def test_parse_report_recipients_dsn():
    got = ib.parse_report_recipients(BOUNCE_BODY)
    assert "info@skender.com" in got


def test_parse_report_recipients_arf():
    got = ib.parse_report_recipients(COMPLAINT_BODY)
    assert "sales@deljoheating.com" in got


def test_classify_bounce():
    kind, detail = ib.classify_message(_payload(BOUNCE_HEADERS, BOUNCE_BODY), set())
    assert kind == "bounce"
    assert "info@skender.com" in detail


def test_classify_complaint():
    kind, detail = ib.classify_message(_payload(COMPLAINT_HEADERS, COMPLAINT_BODY), set())
    assert kind == "complaint"
    assert "sales@deljoheating.com" in detail


def test_classify_reply_from_known_contact():
    payload = _payload(
        {"From": "Ray Sullivan <sales@blackdiamondplumbing.com>", "Subject": "Re: ..."}
    )
    kind, detail = ib.classify_message(payload, {"sales@blackdiamondplumbing.com"})
    assert kind == "reply"
    assert detail == "sales@blackdiamondplumbing.com"


def test_classify_ignores_unknown_sender():
    payload = _payload({"From": "newsletter@example.org", "Subject": "Promo"})
    kind, _ = ib.classify_message(payload, {"sales@blackdiamondplumbing.com"})
    assert kind == "other"


def test_classify_does_not_treat_own_bounce_text_as_reply():
    # Um bounce cujo corpo menciona o nosso contacto tem de ser bounce, nao reply.
    kind, _ = ib.classify_message(
        _payload(BOUNCE_HEADERS, BOUNCE_BODY), {"info@skender.com"}
    )
    assert kind == "bounce"


def test_processed_message_registry_is_idempotent():
    message_id = "pytest-inbox-msg-001"
    con = ib.get_connection()
    try:
        con.execute(
            "DELETE FROM inbox_processed_messages WHERE message_id=?", (message_id,)
        )
        con.commit()
    finally:
        con.close()

    assert ib._is_processed(message_id) is False
    ib._mark_processed(message_id)
    assert ib._is_processed(message_id) is True
    ib._mark_processed(message_id)  # não rebenta nem duplica

    con = ib.get_connection()
    try:
        count = con.execute(
            "SELECT COUNT(*) FROM inbox_processed_messages WHERE message_id=?",
            (message_id,),
        ).fetchone()[0]
        con.execute(
            "DELETE FROM inbox_processed_messages WHERE message_id=?", (message_id,)
        )
        con.commit()
    finally:
        con.close()
    assert count == 1

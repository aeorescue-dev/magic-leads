"""SMS Telnyx: freeze, campanha pendente, envio, STOP/START e tecla 1."""
from __future__ import annotations

import sqlite3

from backend.config import settings
from backend.services import telnyx_sms
from backend.services import telnyx_voice as tv


def _configure(monkeypatch):
    monkeypatch.setattr(settings, "TELNYX_API_KEY", "test-key")
    monkeypatch.setattr(settings, "TELNYX_SMS_FROM_NUMBER", "+19739137808")
    monkeypatch.setattr(settings, "TELNYX_MESSAGING_PROFILE_ID", "profile-1")
    monkeypatch.setattr(settings, "TELNYX_SMS_CAMPAIGN_ID", "campaign-1")


def test_send_blocked_when_frozen(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(settings, "VOICE_FREEZE", True)
    called = []
    monkeypatch.setattr(
        telnyx_sms.httpx, "post", lambda *a, **k: called.append(1)
    )
    out = telnyx_sms.send_sms("+15551234567", "hello", trigger="test")
    assert out["ok"] is False
    assert out["reason"] == "frozen"
    assert called == []


def test_send_blocked_while_campaign_pending(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(settings, "VOICE_FREEZE", False)
    monkeypatch.setattr(telnyx_sms, "is_suppressed", lambda phone: False)
    monkeypatch.setattr(telnyx_sms, "campaign_ready", lambda: False)
    monkeypatch.setattr(telnyx_sms, "campaign_status", lambda force=False: "TCR_PENDING")
    out = telnyx_sms.send_sms("+15551234567", "hello", trigger="test")
    assert out["ok"] is False
    assert out["reason"] == "campaign_pending"


def test_send_sms_success_records_message(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(settings, "VOICE_FREEZE", False)
    monkeypatch.setattr(telnyx_sms, "is_suppressed", lambda phone: False)
    monkeypatch.setattr(telnyx_sms, "campaign_ready", lambda: True)

    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {"data": {"id": "msg-1", "status": "queued"}}

    monkeypatch.setattr(telnyx_sms.httpx, "post", lambda *a, **k: Response())
    out = telnyx_sms.send_sms("+1 (555) 123-4567", "link", trigger="test")
    assert out == {"ok": True, "id": "msg-1", "status": "queued"}

    conn = sqlite3.connect(telnyx_sms.b2b_voice.db_path())
    try:
        row = conn.execute(
            "SELECT phone, status, provider_id, trigger FROM sms_messages "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    assert row == ("+15551234567", "queued", "msg-1", "test")


def test_inbound_stop_and_start_toggle_suppression():
    stop = telnyx_sms.handle_inbound(
        {
            "data": {
                "event_type": "message.received",
                "id": "in-1",
                "payload": {
                    "from": {"phone_number": "+15551234567"},
                    "text": "STOP",
                },
            }
        }
    )
    assert stop["action"] == "opt_out"
    assert telnyx_sms.is_suppressed("+15551234567") is True

    start = telnyx_sms.handle_inbound(
        {
            "data": {
                "event_type": "message.received",
                "id": "in-2",
                "payload": {
                    "from": {"phone_number": "+15551234567"},
                    "text": "START",
                },
            }
        }
    )
    assert start["action"] == "opt_in"
    assert telnyx_sms.is_suppressed("+15551234567") is False


def test_dtmf_one_sends_sms(monkeypatch):
    sent = {}

    def fake_send(phone, body, trigger="manual", **kwargs):
        sent["phone"] = phone
        sent["trigger"] = trigger
        return {"ok": True, "id": "sms-1"}

    monkeypatch.setattr(telnyx_sms, "send_sms", fake_send)
    monkeypatch.setattr(
        tv.b2b_voice,
        "get_voice_call",
        lambda vid: {
            "id": vid,
            "phone": "+15551234567",
            "campaign_id": "test_call",
            "provider_call_id": "cc-1",
        },
    )
    monkeypatch.setattr(tv.b2b_voice, "update_voice_call", lambda *a, **k: None)
    monkeypatch.setattr(tv, "stop_assistant_for_fallback", lambda cid: {"ok": True})
    monkeypatch.setattr(tv, "_call_action", lambda *a, **k: {"ok": True})

    payload = {
        "data": {
            "event_type": "call.dtmf.received",
            "payload": {
                "call_control_id": "cc-1",
                "dtmf_digit": "1",
                "client_state": tv._encode_state({"voice_call_id": 999}),
            },
        }
    }
    out = tv.handle_webhook(payload)
    assert out["action"] == "sms_link"
    assert sent == {"phone": "+15551234567", "trigger": "dtmf_1"}

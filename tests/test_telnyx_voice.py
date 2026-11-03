"""Adaptador Telnyx Fase 2A: dry-run, webhook DTMF 1 e vitrine."""
from __future__ import annotations

import base64
import json
from datetime import datetime, timezone

import pytest

from backend.services import b2b_voice as voice
from backend.services import showcase, telnyx_voice
from backend.services.db import get_connection

NOW = datetime(2026, 11, 2, 16, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.setattr(telnyx_voice.settings, "TELNYX_API_KEY", "")
    monkeypatch.setattr(telnyx_voice.settings, "TELNYX_CONNECTION_ID", "")
    monkeypatch.setattr(telnyx_voice.settings, "TELNYX_FROM_NUMBER", "")
    monkeypatch.setattr(telnyx_voice.settings, "TELNYX_WEBHOOK_SECRET", "pytest-secret")
    monkeypatch.setattr(telnyx_voice.settings, "DEBUG", False)
    monkeypatch.setattr(showcase.settings, "SHOWCASE_MIN_ITEMS", 3)
    monkeypatch.setattr(showcase.settings, "SHOWCASE_WINDOW_DAYS", 30)
    monkeypatch.setenv("VOICE_NOW_ISO", NOW.isoformat())
    voice.init()
    conn = voice.get_conn()
    try:
        for table in (
            "voice_calls",
            "call_attempts",
            "voice_suppressions",
            "dnc_checks",
            "prospect_companies",
            "prospect_sources",
        ):
            conn.execute(f"DELETE FROM {table}")
        conn.commit()
    finally:
        conn.close()
    showcase.init()
    conn = showcase.get_conn()
    try:
        for table in (
            "showcase_checkouts",
            "showcase_visits",
            "showcase_links",
            "showcase_items",
            "showcase_pages",
            "market_inventory",
        ):
            conn.execute(f"DELETE FROM {table}")
        conn.commit()
    finally:
        conn.close()
    leads = get_connection()
    try:
        leads.execute("DELETE FROM leads WHERE external_id LIKE 'pytest-telnyx-%'")
        leads.commit()
    finally:
        leads.close()
    showcase._CACHE.clear()
    yield


def _seed_company() -> dict:
    csv_text = (
        "company_name,contact_name,phone,email,city,state,license_status,trade,"
        "permit_count\n"
        "Telnyx Roofing,Jane Doe,+16175550123,jane@example.com,Boston,MA,active,Roofing,8\n"
    )
    voice.import_licenses_csv(csv_text, source_name="pytest")
    voice.check_dnc("+16175550123", listed=False, source="pytest")
    conn = voice.get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM prospect_companies WHERE phone='+16175550123'"
        ).fetchone()
        return dict(row)
    finally:
        conn.close()


def _seed_showcase() -> None:
    conn = get_connection()
    try:
        for idx in range(3):
            conn.execute(
                """
                INSERT INTO leads
                  (external_id, source_type, address, city, state, zip_code,
                   issue_category, date_reported, signal_type, signal_status,
                   owner_name, is_junk)
                VALUES (?, 'pytest', ?, 'Boston', 'MA', '02118', 'Roof', ?,
                        'open_request', 'open', 'Owner Leak', 0)
                """,
                (
                    f"pytest-telnyx-{idx}",
                    f"{200 + idx} Test Street",
                    NOW.isoformat(),
                ),
            )
        conn.commit()
    finally:
        conn.close()
    showcase.build_pages()


def test_create_call_dry_run_sem_chaves():
    company = _seed_company()
    result = telnyx_voice.create_call(company, campaign_id="pilot")
    assert result["ok"] is True
    assert result["dry_run"] is True
    call = voice.get_voice_call(result["voice_call_id"])
    assert call is not None
    assert call["status"] == "dry_run"
    assert call["provider"] == "telnyx"


def test_webhook_dtmf_1_marca_intent_sem_duplicar_email():
    company = _seed_company()
    _seed_showcase()
    created = telnyx_voice.create_call(company, campaign_id="pilot")
    call_id = created["voice_call_id"]
    state = base64.b64encode(
        json.dumps({"voice_call_id": call_id, "company_id": company["id"]}).encode()
    ).decode()
    payload = {
        "data": {
            "event_type": "call.dtmf.received",
            "payload": {
                "client_state": state,
                "dtmf_digit": "1",
            },
        }
    }
    result = telnyx_voice.handle_webhook(payload)
    assert result["ok"] is True
    assert result["action"] == "dtmf_yes"
    assert result["digit"] == "1"

    call = voice.get_voice_call(call_id)
    assert call["intent"] == "showcase"
    # O envio fica a cargo da tool capture_email (o assistant pergunta o email).
    assert call["showcase_link_id"] is None


def test_webhook_secret_fail_closed_e_valida():
    assert telnyx_voice.verify_secret("pytest-secret") is True
    assert telnyx_voice.verify_secret("wrong") is False
    telnyx_voice.settings.TELNYX_WEBHOOK_SECRET = ""
    assert telnyx_voice.verify_secret("anything") is False


def test_staging_mode_forca_dry_run(monkeypatch):
    monkeypatch.setattr(telnyx_voice.settings, "VOICE_STAGING_MODE", True)
    monkeypatch.setattr(telnyx_voice.settings, "TELNYX_API_KEY", "sk_test_dummy")
    monkeypatch.setattr(telnyx_voice.settings, "TELNYX_CONNECTION_ID", "conn")
    monkeypatch.setattr(telnyx_voice.settings, "TELNYX_FROM_NUMBER", "+16175550000")
    assert telnyx_voice.configured() is False


def test_webhook_instrumenta_answered_e_hangup():
    company = _seed_company()
    created = telnyx_voice.create_call(company)
    call_id = created["voice_call_id"]
    state = base64.b64encode(
        json.dumps({"voice_call_id": call_id, "company_id": company["id"]}).encode()
    ).decode()

    def event(event_type: str, body: dict):
        return {
            "data": {
                "event_type": event_type,
                "payload": {"client_state": state, **body},
            }
        }

    answered = telnyx_voice.handle_webhook(event("call.answered", {}))
    assert answered["ok"] is True
    hangup = telnyx_voice.handle_webhook(
        event(
            "call.hangup",
            {"duration_millis": 65000, "hangup_cause": "normal_clearing"},
        )
    )
    assert hangup["ok"] is True
    call = voice.get_voice_call(call_id)
    assert call["answered_at"] is not None
    assert call["duration_seconds"] == 65
    assert call["listen_seconds"] == 65
    assert call["hangup_cause"] == "normal_clearing"
    assert call["cost_cents"] == 4


def test_email_fallback_cidade_usa_escopo_neutro(monkeypatch):
    """Dallas roofing sem página exata: email não pode dizer 'Roofing 3864'."""
    conn = get_connection()
    try:
        conn.execute("DELETE FROM leads WHERE external_id LIKE 'pytest-telnyx-dallas-%'")
        for idx in range(3):
            conn.execute(
                """
                INSERT INTO leads
                  (external_id, source_type, address, city, state, zip_code,
                   issue_category, date_reported, signal_type, signal_status,
                   owner_name, is_junk)
                VALUES (?, 'pytest', ?, 'Dallas', 'TX', '75201', 'Structure', ?,
                        'open_request', 'open', 'Dallas Owner', 0)
                """,
                (
                    f"pytest-telnyx-dallas-{idx}",
                    f"{600 + idx} Dallas Ave",
                    NOW.isoformat(),
                ),
            )
        conn.commit()
    finally:
        conn.close()
    showcase.build_pages()
    csv_text = (
        "company_name,contact_name,phone,email,city,state,license_status,trade,"
        "permit_count\n"
        "Dallas Roofing,Ana,+12145550188,ana@example.com,Dallas,TX,active,Roofing,4\n"
    )
    voice.import_licenses_csv(csv_text, source_name="pytest")
    voice.check_dnc("+12145550188", listed=False, source="pytest")
    conn = voice.get_conn()
    try:
        company = dict(
            conn.execute(
                "SELECT * FROM prospect_companies WHERE phone='+12145550188'"
            ).fetchone()
        )
    finally:
        conn.close()
    created = telnyx_voice.create_call(company)
    captured: dict = {}

    def fake_email(**kwargs):
        captured.update(kwargs)
        return {"sent": False, "dry_run": True}

    monkeypatch.setattr(showcase, "send_showcase_email", fake_email)
    result = telnyx_voice.send_showcase_for_call(
        created["voice_call_id"], "Dallas", "roofing"
    )
    assert result["ok"] is True
    assert captured["scope_label"] == "active property"
    assert captured["city"] == "Dallas"
    assert captured["trade_code"] == "roofing"


def _registered_call(company: dict, provider_id: str = "v3:tool-call") -> dict:
    created = telnyx_voice.create_call(company, campaign_id="pilot")
    voice.update_voice_call(
        created["voice_call_id"], provider_call_id=provider_id, status="in_call"
    )
    return voice.get_voice_call(created["voice_call_id"]) or {}


def test_tool_capture_email_guarda_e_envia(monkeypatch):
    company = _seed_company()
    _seed_showcase()
    call = _registered_call(company)
    result = telnyx_voice.handle_tool_call(
        "capture_email", {"email": "boss@newmail.com"}, "v3:tool-call"
    )
    assert result["ok"] is True
    assert result["email"] == "boss@newmail.com"
    updated = voice.get_company(company["id"])
    assert updated["email"] == "boss@newmail.com"
    current = voice.get_voice_call(call["id"])
    assert current["status"] == "showcase_sent"
    assert current["showcase_link_id"]


def test_tool_send_showcase_sem_email_pede_email():
    company = _seed_company()
    _seed_showcase()
    conn = voice.get_conn()
    try:
        conn.execute(
            "UPDATE prospect_companies SET email='' WHERE id=?", (company["id"],)
        )
        conn.commit()
    finally:
        conn.close()
    _registered_call(company)
    result = telnyx_voice.handle_tool_call(
        "send_showcase_link", {}, "v3:tool-call"
    )
    assert result["ok"] is False
    assert result["reason"] == "email_required"


def test_tool_remove_from_list_suprime_numero():
    company = _seed_company()
    _registered_call(company)
    result = telnyx_voice.handle_tool_call(
        "remove_from_list", {}, "v3:tool-call"
    )
    assert result["ok"] is True
    updated = voice.get_company(company["id"])
    assert updated["status"] == "do_not_call"
    conn = voice.get_conn()
    try:
        row = conn.execute(
            "SELECT 1 FROM voice_suppressions WHERE value=?",
            (company["phone"],),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None


def test_tool_chamada_desconhecida_falha():
    result = telnyx_voice.handle_tool_call("capture_email", {}, "v3:unknown")
    assert result["ok"] is False
    assert result["error"] == "call_not_found"


def test_assinatura_ed25519_valida_e_rejeita_tamper(monkeypatch):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
    )

    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    monkeypatch.setattr(
        telnyx_voice.settings,
        "TELNYX_PUBLIC_KEY",
        base64.b64encode(public).decode(),
    )
    body = b'{"data":{"event_type":"call.answered"}}'
    timestamp = str(int(__import__("time").time()))
    signature = base64.b64encode(
        private.sign(timestamp.encode() + b"|" + body)
    ).decode()
    assert telnyx_voice.verify_signature(signature, timestamp, body) is True
    assert telnyx_voice.verify_signature(signature, timestamp, body + b" ") is False
    bad_ts = str(int(timestamp) - 3600)
    old_sig = base64.b64encode(private.sign(bad_ts.encode() + b"|" + body)).decode()
    assert telnyx_voice.verify_signature(old_sig, bad_ts, body) is False


def test_answered_envia_script_renderizado_ao_assistant(monkeypatch):
    company = _seed_company()
    _seed_showcase()
    created = telnyx_voice.create_call(company)
    call_id = created["voice_call_id"]
    voice.update_voice_call(
        call_id,
        assistant_id="assistant-123",
        provider_call_id="v3:answered",
    )
    monkeypatch.setattr(telnyx_voice.settings, "VOICE_STAGING_MODE", False)
    monkeypatch.setattr(telnyx_voice.settings, "TELNYX_API_KEY", "key")
    monkeypatch.setattr(telnyx_voice.settings, "TELNYX_CONNECTION_ID", "conn")
    monkeypatch.setattr(telnyx_voice.settings, "TELNYX_FROM_NUMBER", "+16175550000")
    captured: dict = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = json

        class Resp:
            status_code = 200
            content = b"{}"

            def json(self):
                return {}

        return Resp()

    monkeypatch.setattr(telnyx_voice.httpx, "post", fake_post)
    state = base64.b64encode(
        json.dumps({"voice_call_id": call_id, "company_id": company["id"]}).encode()
    ).decode()
    result = telnyx_voice.handle_webhook(
        {
            "data": {
                "event_type": "call.answered",
                "payload": {
                    "client_state": state,
                    "call_control_id": "v3:answered",
                },
            }
        }
    )
    assert result["assistant_started"] is True
    sent = captured["json"]["assistant"]
    assert sent["id"] == "assistant-123"
    assert "Telnyx Roofing" in sent["instructions"]
    assert "active roofing opportunities in Boston this week" in sent[
        "instructions"
    ]
    assert sent["greeting"].startswith("Hi Telnyx Roofing")
    assert sent["voice_settings"]["voice"] == "Telnyx.Ultra.Callie"


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


def test_webhook_dtmf_1_gera_link_e_email_dry_run():
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
    assert result["action"] == "showcase"
    assert result["showcase"]["ok"] is True
    assert result["showcase"]["link"]["url"].endswith(
        "/r/" + result["showcase"]["link"]["token"]
    )
    assert result["showcase"]["email"]["sent"] is False
    assert result["showcase"]["email"].get("dry_run") is True

    call = voice.get_voice_call(call_id)
    assert call["intent"] == "showcase"
    assert call["showcase_link_id"] == result["showcase"]["link"]["link_id"]


def test_webhook_secret_fail_closed_e_valida():
    assert telnyx_voice.verify_secret("pytest-secret") is True
    assert telnyx_voice.verify_secret("wrong") is False
    telnyx_voice.settings.TELNYX_WEBHOOK_SECRET = ""
    assert telnyx_voice.verify_secret("anything") is False

"""Adaptador Telnyx Fase 2A: dry-run, webhook DTMF 1 e vitrine."""
from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone

import pytest

from backend.services import b2b_voice as voice
from backend.services import showcase, telnyx_voice, voice_scripts
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
        for idx in range(5):
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


def test_webhook_dtmf_1_regete_website_sem_email():
    company = _seed_company()
    _seed_showcase()
    created = telnyx_voice.create_call(company, campaign_id="pilot")
    call_id = created["voice_call_id"]
    state = base64.b64encode(
        json.dumps({"voice_call_id": call_id, "company_id": company["id"]}).encode()
    ).decode()
    actions: list[tuple[str, dict]] = []

    def fake_action(call_control_id, action, payload):
        actions.append((action, payload))
        return {"ok": True}

    original = telnyx_voice._call_action
    telnyx_voice._call_action = fake_action
    try:
        result = telnyx_voice.handle_webhook(
            {
                "data": {
                    "event_type": "call.dtmf.received",
                    "payload": {
                        "client_state": state,
                        "dtmf_digit": "1",
                        "call_control_id": "v3:test-dtmf1",
                    },
                }
            }
        )
    finally:
        telnyx_voice._call_action = original
    assert result["ok"] is True
    assert result["action"] == "website_reminder"
    assert [action for action, _ in actions] == ["ai_assistant_stop", "speak"]
    call = voice.get_voice_call(call_id)
    assert call["intent"] == "website_reminder"
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


def test_hangup_sem_duracao_usa_answered_at():
    company = _seed_company()
    created = telnyx_voice.create_call(company)
    call_id = created["voice_call_id"]
    answered = (datetime.now(timezone.utc) - timedelta(seconds=45)).isoformat()
    voice.update_voice_call(call_id, status="in_call", answered_at=answered)
    state = base64.b64encode(
        json.dumps({"voice_call_id": call_id, "company_id": company["id"]}).encode()
    ).decode()
    telnyx_voice.handle_webhook(
        {
            "data": {
                "event_type": "call.hangup",
                "payload": {"client_state": state},
            }
        }
    )
    call = voice.get_voice_call(call_id)
    assert 40 <= call["duration_seconds"] <= 60
    assert call["listen_seconds"] >= 40
    assert call["cost_cents"] > 0


def test_static_mode_usa_gather_using_audio_quando_cache_pronto(monkeypatch, tmp_path):
    company = _seed_company()
    _seed_showcase()
    created = telnyx_voice.create_call(company, campaign_id="test_call", dry_run=True)
    call_id = created["voice_call_id"]
    voice.update_voice_call(call_id, status="assistant_pending")
    monkeypatch.setattr(telnyx_voice.settings, "VOICE_SCRIPT_MODE", "static")
    monkeypatch.setattr(telnyx_voice, "configured", lambda: True)
    monkeypatch.setattr(
        telnyx_voice.settings, "VOICE_TTS_CACHE_ENABLED", True, raising=False
    )
    monkeypatch.setattr(
        telnyx_voice.settings, "VOICE_TTS_CACHE_DIR", str(tmp_path), raising=False
    )
    monkeypatch.setattr(
        telnyx_voice.settings,
        "VOICE_TTS_CACHE_BASE_URL",
        "https://example.test",
        raising=False,
    )
    monkeypatch.setattr(
        telnyx_voice.settings, "VOICE_TTS_VOICE", "voice.test", raising=False
    )
    telnyx_voice.voice_audio_cache.init()
    text = "Hi. This is an automated message."
    cache_hash = telnyx_voice.voice_audio_cache.key(text)
    path = telnyx_voice.voice_audio_cache.path_for(cache_hash)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"ID3" + b"\x00" * 200)
    actions: list[tuple[str, dict]] = []

    def fake_action(call_control_id, action, payload):
        actions.append((action, payload))
        return {"ok": True}

    monkeypatch.setattr(telnyx_voice, "_call_action", fake_action)
    result = telnyx_voice._start_static_script_for_call(
        call_id,
        "v3:static-cache",
        {
            "voice_call_id": call_id,
            "company_id": company["id"],
            "tts_url": telnyx_voice.voice_audio_cache.public_url(cache_hash),
            "tts_hash": cache_hash,
        },
    )
    assert result["ok"] is True
    assert [action for action, _ in actions] == ["gather_using_audio"]
    payload = actions[0][1]
    assert payload["audio_url"].endswith(f"/api/voice/tts/{cache_hash}.mp3")
    assert payload["valid_digits"] == "2"
    assert payload["maximum_tries"] == 1
    assert voice.get_voice_call(call_id)["status"] == "in_call"


def test_static_mode_faz_fallback_para_speak_se_audio_falhar(monkeypatch, tmp_path):
    company = _seed_company()
    _seed_showcase()
    created = telnyx_voice.create_call(company, campaign_id="test_call", dry_run=True)
    call_id = created["voice_call_id"]
    voice.update_voice_call(call_id, status="assistant_pending")
    monkeypatch.setattr(telnyx_voice.settings, "VOICE_SCRIPT_MODE", "static")
    monkeypatch.setattr(telnyx_voice, "configured", lambda: True)
    monkeypatch.setattr(
        telnyx_voice.settings, "VOICE_TTS_CACHE_ENABLED", True, raising=False
    )
    monkeypatch.setattr(
        telnyx_voice.settings, "VOICE_TTS_CACHE_DIR", str(tmp_path), raising=False
    )
    monkeypatch.setattr(
        telnyx_voice.settings, "VOICE_TTS_VOICE", "voice.test", raising=False
    )
    telnyx_voice.voice_audio_cache.init()
    cache_hash = telnyx_voice.voice_audio_cache.key("text")
    path = telnyx_voice.voice_audio_cache.path_for(cache_hash)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"ID3" + b"\x00" * 200)
    actions: list[str] = []

    def fake_action(call_control_id, action, payload):
        actions.append(action)
        return {"ok": action == "gather_using_speak"}

    monkeypatch.setattr(telnyx_voice, "_call_action", fake_action)
    result = telnyx_voice._start_static_script_for_call(
        call_id,
        "v3:static-cache",
        {
            "voice_call_id": call_id,
            "company_id": company["id"],
            "tts_url": "https://example.test/audio.mp3",
            "tts_hash": cache_hash,
        },
    )
    assert result["ok"] is True
    assert actions == ["gather_using_audio", "gather_using_speak"]


def test_create_call_adiciona_tts_url_ao_client_state(monkeypatch, tmp_path):
    company = _seed_company()
    _seed_showcase()
    voice_scripts.init()
    voice_scripts.approve_all()
    monkeypatch.setattr(telnyx_voice.settings, "TELNYX_API_KEY", "KEY")
    monkeypatch.setattr(telnyx_voice.settings, "TELNYX_CONNECTION_ID", "conn")
    monkeypatch.setattr(
        telnyx_voice.settings, "TELNYX_FROM_NUMBER", "+15550000000"
    )
    monkeypatch.setattr(telnyx_voice, "configured", lambda: True)
    monkeypatch.setattr(telnyx_voice.settings, "VOICE_SCRIPT_MODE", "static")
    monkeypatch.setattr(
        telnyx_voice.settings, "VOICE_TTS_CACHE_ENABLED", True, raising=False
    )
    monkeypatch.setattr(
        telnyx_voice.settings, "VOICE_TTS_CACHE_DIR", str(tmp_path), raising=False
    )
    monkeypatch.setattr(
        telnyx_voice.settings, "VOICE_TTS_VOICE", "voice.test", raising=False
    )
    telnyx_voice.voice_audio_cache.init()
    monkeypatch.setattr(
        telnyx_voice.voice_audio_cache,
        "get_or_create",
        lambda text: {
            "ok": True,
            "hash": "a" * 64,
            "url": "https://example.test/audio.mp3",
            "chars": len(text),
            "hit": False,
        },
    )
    captured: dict = {}

    class FakeResp:
        status_code = 200
        content = b'{"data":{"call_control_id":"v3:test"}}'

        def json(self):
            return {"data": {"call_control_id": "v3:test"}}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["json"] = json
        return FakeResp()

    monkeypatch.setattr(telnyx_voice.httpx, "post", fake_post)
    result = telnyx_voice.create_call(company, campaign_id="14")
    assert result["ok"] is True, result
    state = json.loads(base64.b64decode(captured["json"]["client_state"]))
    assert state["tts_url"] == "https://example.test/audio.mp3"
    assert state["tts_hash"] == "a" * 64


def test_static_mode_usa_gather_using_speak_sem_ai(monkeypatch):
    company = _seed_company()
    _seed_showcase()
    created = telnyx_voice.create_call(company, campaign_id="test_call", dry_run=True)
    call_id = created["voice_call_id"]
    voice.update_voice_call(call_id, status="assistant_pending")
    monkeypatch.setattr(telnyx_voice.settings, "VOICE_SCRIPT_MODE", "static")
    monkeypatch.setattr(telnyx_voice, "configured", lambda: True)
    actions: list[tuple[str, dict]] = []

    def fake_action(call_control_id, action, payload):
        actions.append((action, payload))
        return {"ok": True}

    monkeypatch.setattr(telnyx_voice, "_call_action", fake_action)
    result = telnyx_voice._start_static_script_for_call(
        call_id,
        "v3:static",
        {"voice_call_id": call_id, "company_id": company["id"]},
    )
    assert result["ok"] is True
    assert [action for action, _ in actions] == ["gather_using_speak"]
    payload = actions[0][1]
    assert "magicleads.app" in payload["payload"]
    assert payload["valid_digits"] == "2"
    assert payload["maximum_tries"] == 1
    assert voice.get_voice_call(call_id)["status"] == "in_call"


def test_gather_ended_2_faz_opt_out_real(monkeypatch):
    company = _seed_company()
    created = telnyx_voice.create_call(company, campaign_id="test_call", dry_run=True)
    call_id = created["voice_call_id"]
    state = base64.b64encode(
        json.dumps({"voice_call_id": call_id, "company_id": company["id"]}).encode()
    ).decode()
    actions: list[tuple[str, dict]] = []

    def fake_action(call_control_id, action, payload):
        actions.append((action, payload))
        return {"ok": True}

    monkeypatch.setattr(telnyx_voice, "_call_action", fake_action)
    result = telnyx_voice.handle_webhook(
        {
            "data": {
                "event_type": "call.gather.ended",
                "payload": {
                    "client_state": state,
                    "digits": "2",
                    "call_control_id": "v3:gather-2",
                },
            }
        }
    )
    assert result["action"] == "gather_opt_out"
    assert actions and actions[0][0] == "speak"
    assert "removed from our list" in actions[0][1]["payload"]
    conn = voice.get_conn()
    try:
        suppressed = conn.execute(
            "SELECT COUNT(*) FROM voice_suppressions WHERE value=?",
            (company["phone"],),
        ).fetchone()[0]
    finally:
        conn.close()
    assert suppressed == 1


def test_opt_out_de_test_call_usa_phone_do_voice_call():
    phone = "+16175550988"
    voice.check_dnc(phone, listed=False, source="pytest")
    created = telnyx_voice.create_call(
        {
            "id": 0,
            "company_name": "",
            "phone": phone,
            "city": "Boston",
            "state": "MA",
            "trade": "roofing",
        },
        campaign_id="test_call",
        dry_run=True,
    )
    telnyx_voice.opt_out_voice_call(created["voice_call_id"])
    conn = voice.get_conn()
    try:
        suppressed = conn.execute(
            "SELECT COUNT(*) FROM voice_suppressions WHERE value=?",
            (phone,),
        ).fetchone()[0]
    finally:
        conn.close()
    assert suppressed == 1


def test_webhook_dtmf_2_faz_opt_out_real_e_confirma():
    company = _seed_company()
    created = telnyx_voice.create_call(company)
    call_id = created["voice_call_id"]
    state = base64.b64encode(
        json.dumps({"voice_call_id": call_id, "company_id": company["id"]}).encode()
    ).decode()
    actions: list[tuple[str, dict]] = []

    def fake_action(call_control_id, action, payload):
        actions.append((action, payload))
        return {"ok": True}

    original = telnyx_voice._call_action
    telnyx_voice._call_action = fake_action
    try:
        result = telnyx_voice.handle_webhook(
            {
                "data": {
                    "event_type": "call.dtmf.received",
                    "payload": {
                        "client_state": state,
                        "dtmf_digit": "2",
                        "call_control_id": "v3:test-dtmf2",
                    },
                }
            }
        )
    finally:
        telnyx_voice._call_action = original
    assert result["action"] == "opt_out"
    assert result["opt_out"]["suppressed"] is True
    assert [action for action, _ in actions] == ["ai_assistant_stop", "speak"]
    assert "removed from our list" in actions[1][1]["payload"]
    call = voice.get_voice_call(call_id)
    assert call["intent"] == "opt_out"
    assert call["showcase_link_id"] is None
    conn = voice.get_conn()
    try:
        row = conn.execute(
            "SELECT status FROM prospect_companies WHERE id=?",
            (company["id"],),
        ).fetchone()
        suppressed = conn.execute(
            "SELECT COUNT(*) FROM voice_suppressions WHERE value=?",
            (company["phone"],),
        ).fetchone()[0]
    finally:
        conn.close()
    assert row["status"] == "do_not_call"
    assert suppressed == 1


def test_webhook_playback_ended_desliga_chamada():
    company = _seed_company()
    created = telnyx_voice.create_call(company)
    call_id = created["voice_call_id"]
    state = base64.b64encode(
        json.dumps({"voice_call_id": call_id, "company_id": company["id"]}).encode()
    ).decode()
    calls: list[tuple[str, dict]] = []

    def fake_action(call_control_id, action, payload):
        calls.append((action, payload))
        return {"ok": True}

    original = telnyx_voice._call_action
    telnyx_voice._call_action = fake_action
    try:
        result = telnyx_voice.handle_webhook(
            {
                "data": {
                    "event_type": "call.playback.ended",
                    "payload": {
                        "client_state": state,
                        "call_control_id": "v3:test-playback",
                    },
                }
            }
        )
    finally:
        telnyx_voice._call_action = original
    assert result["action"] == "media_ended_hangup"
    assert calls and calls[0][0] == "hangup"


def test_webhook_playback_ended_sem_client_state_desliga():
    company = _seed_company()
    created = telnyx_voice.create_call(company)
    call_id = created["voice_call_id"]
    voice.update_voice_call(call_id, provider_call_id="v3:media-only")
    calls: list[str] = []

    def fake_action(call_control_id, action, payload):
        calls.append(action)
        return {"ok": True}

    original = telnyx_voice._call_action
    telnyx_voice._call_action = fake_action
    try:
        result = telnyx_voice.handle_webhook(
            {
                "data": {
                    "event_type": "call.playback.ended",
                    "payload": {"call_control_id": "v3:media-only"},
                }
            }
        )
    finally:
        telnyx_voice._call_action = original
    assert result["ok"] is True
    assert result["action"] == "media_ended_hangup"
    assert calls == ["hangup"]


def test_amd_machine_desliga_e_marca_voicemail():
    company = _seed_company()
    call = _registered_call(company)
    calls: list[str] = []

    def fake_action(call_control_id, action, payload):
        calls.append(action)
        return {"ok": True}

    original = telnyx_voice._call_action
    telnyx_voice._call_action = fake_action
    try:
        result = telnyx_voice.handle_webhook(
            {
                "data": {
                    "event_type": "call.machine.premium.detection.ended",
                    "payload": {
                        "call_control_id": "v3:tool-call",
                        "result": "machine",
                    },
                }
            }
        )
    finally:
        telnyx_voice._call_action = original
    assert result["action"] == "voicemail_hangup"
    assert calls == ["hangup"]
    current = voice.get_voice_call(call["id"])
    assert current["intent"] == "voicemail"
    assert current["hangup_cause"] == "voicemail_detected"


def test_amd_human_nao_desliga():
    company = _seed_company()
    call = _registered_call(company)
    state = base64.b64encode(
        json.dumps({"voice_call_id": call["id"], "company_id": company["id"]}).encode()
    ).decode()
    calls: list[str] = []

    def fake_action(call_control_id, action, payload):
        calls.append(action)
        return {"ok": True}

    original = telnyx_voice._call_action
    telnyx_voice._call_action = fake_action
    try:
        result = telnyx_voice.handle_webhook(
            {
                "data": {
                    "event_type": "call.machine.premium.detection.ended",
                    "payload": {
                        "client_state": state,
                        "call_control_id": "v3:tool-call",
                        "result": "human_business",
                    },
                }
            }
        )
    finally:
        telnyx_voice._call_action = original
    assert result["action"] == "amd_human"
    assert calls == []


def test_amd_silence_arranca_assistant_e_nao_desliga(monkeypatch):
    monkeypatch.setattr(telnyx_voice.settings, "VOICE_STAGING_MODE", False)
    monkeypatch.setattr(telnyx_voice.settings, "TELNYX_API_KEY", "key")
    monkeypatch.setattr(telnyx_voice.settings, "TELNYX_CONNECTION_ID", "conn")
    monkeypatch.setattr(telnyx_voice.settings, "TELNYX_FROM_NUMBER", "+16175550000")
    company = _seed_company()
    created = voice.create_voice_call(company, provider="pytest")
    call_id = created["id"]
    voice.update_voice_call(
        call_id,
        assistant_id="assistant-123",
        provider_call_id="v3:amd-silence",
        status="assistant_pending",
    )
    state = base64.b64encode(
        json.dumps({"voice_call_id": call_id, "company_id": company["id"]}).encode()
    ).decode()
    actions: list[str] = []

    def fake_action(call_control_id, action, payload):
        actions.append(action)
        return {"ok": True}

    original = telnyx_voice._call_action
    telnyx_voice._call_action = fake_action
    try:
        result = telnyx_voice.handle_webhook(
            {
                "data": {
                    "event_type": "call.machine.premium.detection.ended",
                    "payload": {
                        "client_state": state,
                        "call_control_id": "v3:amd-silence",
                        "result": "silence",
                    },
                }
            }
        )
    finally:
        telnyx_voice._call_action = original
    assert result["action"] == "amd_human"
    assert "hangup" not in actions
    assert "ai_assistant_start" in actions
    current = voice.get_voice_call(call_id)
    assert current["amd_result"] == "silence"
    assert current["status"] == "in_call"


def test_fallback_audio_existe_e_url_publica():
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "backend" / "static" / "voice_fallback.mp3"
    assert path.exists()
    assert path.stat().st_size > 1000
    assert telnyx_voice.fallback_audio_url().endswith("/api/voice/fallback.mp3")


def test_voice_daily_usage_exclui_test_e_dry_run():
    company = _seed_company()
    normal = voice.create_voice_call(company, provider="telnyx", campaign_id="pilot")
    voice.update_voice_call(normal["id"], cost_cents=10)
    test = voice.create_voice_call(company, provider="telnyx", campaign_id="test_call")
    voice.update_voice_call(test["id"], cost_cents=100)
    dry = voice.create_voice_call(company, provider="telnyx", campaign_id="pilot")
    voice.update_voice_call(dry["id"], status="dry_run", cost_cents=50)
    usage = voice.voice_daily_usage()
    assert usage["calls"] == 1
    assert usage["spent_cents"] == 10
    assert usage["active_calls"] == 1


def test_create_call_bloqueia_limite_diario_de_chamadas(monkeypatch):
    monkeypatch.setattr(telnyx_voice.settings, "VOICE_STAGING_MODE", False)
    monkeypatch.setattr(telnyx_voice.settings, "TELNYX_API_KEY", "key")
    monkeypatch.setattr(telnyx_voice.settings, "TELNYX_CONNECTION_ID", "conn")
    monkeypatch.setattr(telnyx_voice.settings, "TELNYX_FROM_NUMBER", "+16175550000")
    monkeypatch.setattr(telnyx_voice.settings, "VOICE_MAX_CALLS_PER_DAY", 1)
    monkeypatch.setattr(telnyx_voice.settings, "VOICE_MAX_DAILY_BUDGET_USD", 0.0)
    company = _seed_company()
    voice.create_voice_call(company, provider="telnyx", campaign_id="pilot")
    result = telnyx_voice.create_call(company, campaign_id="pilot", dry_run=False)
    assert result["ok"] is False
    assert result["reason"] == "daily_calls_reached"


def test_create_call_bloqueia_limite_diario_de_orcamento(monkeypatch):
    monkeypatch.setattr(telnyx_voice.settings, "VOICE_STAGING_MODE", False)
    monkeypatch.setattr(telnyx_voice.settings, "TELNYX_API_KEY", "key")
    monkeypatch.setattr(telnyx_voice.settings, "TELNYX_CONNECTION_ID", "conn")
    monkeypatch.setattr(telnyx_voice.settings, "TELNYX_FROM_NUMBER", "+16175550000")
    monkeypatch.setattr(telnyx_voice.settings, "VOICE_MAX_CALLS_PER_DAY", 0)
    monkeypatch.setattr(telnyx_voice.settings, "VOICE_MAX_DAILY_BUDGET_USD", 0.05)
    monkeypatch.setattr(telnyx_voice.settings, "VOICE_ESTIMATED_CALL_COST_CENTS", 25)
    company = _seed_company()
    voice.create_voice_call(company, provider="telnyx", campaign_id="pilot")
    result = telnyx_voice.create_call(company, campaign_id="pilot", dry_run=False)
    assert result["ok"] is False
    assert result["reason"] == "daily_budget_reached"


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


def test_tool_capture_email_marca_intent_antes_de_confirmar():
    company = _seed_company()
    _registered_call(company)
    result = telnyx_voice.handle_tool_call(
        "capture_email", {"email": "boss@newmail.com"}, "v3:tool-call"
    )
    assert result["ok"] is False
    assert result["reason"] == "email_not_confirmed"
    call = voice.get_voice_call_by_provider_id("v3:tool-call")
    assert call is not None
    assert call["intent"] == "showcase"


def test_tool_capture_email_guarda_e_envia(monkeypatch):
    company = _seed_company()
    _seed_showcase()
    call = _registered_call(company)
    result = telnyx_voice.handle_tool_call(
        "capture_email",
        {"email": "boss@newmail.com", "confirmed": True},
        "v3:tool-call",
    )
    assert result["ok"] is True
    assert result["email"] == "boss@newmail.com"
    updated = voice.get_company(company["id"])
    assert updated["email"] == "boss@newmail.com"
    current = voice.get_voice_call(call["id"])
    assert current["status"] == "showcase_sent"
    assert current["showcase_link_id"]


def test_tool_capture_email_exige_readback_confirmado():
    company = _seed_company()
    _seed_showcase()
    _registered_call(company)
    result = telnyx_voice.handle_tool_call(
        "capture_email", {"email": "boss@newmail.com"}, "v3:tool-call"
    )
    assert result["ok"] is False
    assert result["reason"] == "email_not_confirmed"
    assert voice.get_company(company["id"])["email"] == "jane@example.com"


def test_tool_send_showcase_confirma_email_da_ficha():
    company = _seed_company()
    _seed_showcase()
    call = _registered_call(company)
    mismatch = telnyx_voice.handle_tool_call(
        "send_showcase_link",
        {"confirmed_email": "wrong@example.com"},
        "v3:tool-call",
    )
    assert mismatch["ok"] is False
    assert mismatch["reason"] == "email_confirmation_mismatch"
    assert mismatch["email_on_file"] == "jane@example.com"
    assert voice.get_voice_call(call["id"])["showcase_link_id"] is None

    ok = telnyx_voice.handle_tool_call(
        "send_showcase_link",
        {"confirmed_email": "JANE@example.com"},
        "v3:tool-call",
    )
    assert ok["ok"] is True
    assert voice.get_voice_call(call["id"])["showcase_link_id"]


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
    assert result["assistant_started"] is False
    assert result["waiting_for_amd"] is True
    assert captured == {}
    assert voice.get_voice_call(call_id)["status"] == "assistant_pending"

    telnyx_voice.handle_webhook(
        {
            "data": {
                "event_type": "call.machine.premium.detection.ended",
                "payload": {
                    "client_state": state,
                    "call_control_id": "v3:answered",
                    "result": "human_business",
                },
            }
        }
    )
    sent = captured["json"]["assistant"]
    assert sent["id"] == "assistant-123"
    assert "Telnyx Roofing" in sent["instructions"]
    assert "active opportunities in your trade right now" in sent[
        "instructions"
    ]
    assert sent["greeting"].startswith("Hi Telnyx Roofing")
    assert "press 2" in sent["greeting"].lower()
    assert "Press 1 if that's correct" not in sent["greeting"]
    assert sent["voice_settings"]["voice"] == (
        "Telnyx.Ultra.00a77add-48d5-4ef6-8157-71e5437b282d"
    )
    assert "Do not ask for an email" in sent["instructions"]
    assert "send_showcase_link" not in sent["instructions"]


def test_test_call_amd_machine_nao_desliga():
    company = _seed_company()
    created = voice.create_voice_call(
        company,
        provider="pytest",
        campaign_id="test_call",
        trade_code="roofing",
    )
    call_id = created["id"]
    voice.update_voice_call(
        call_id, provider_call_id="v3:test-amd", status="assistant_pending"
    )
    state = base64.b64encode(
        json.dumps({"voice_call_id": call_id, "company_id": company["id"]}).encode()
    ).decode()
    actions: list[str] = []

    def fake_action(call_control_id, action, payload):
        actions.append(action)
        return {"ok": True}

    original = telnyx_voice._call_action
    telnyx_voice._call_action = fake_action
    try:
        result = telnyx_voice.handle_webhook(
            {
                "data": {
                    "event_type": "call.machine.premium.detection.ended",
                    "payload": {
                        "client_state": state,
                        "call_control_id": "v3:test-amd",
                        "result": "machine",
                    },
                }
            }
        )
    finally:
        telnyx_voice._call_action = original
    assert result["action"] == "amd_test_call_ignored"
    assert actions == []
    current = voice.get_voice_call(call_id)
    assert current["intent"] != "voicemail"
    assert current["hangup_cause"] is None


def test_test_call_answered_arranca_gather_imediatamente(monkeypatch):
    monkeypatch.setattr(telnyx_voice.settings, "VOICE_STAGING_MODE", False)
    monkeypatch.setattr(telnyx_voice.settings, "TELNYX_API_KEY", "key")
    monkeypatch.setattr(telnyx_voice.settings, "TELNYX_CONNECTION_ID", "conn")
    monkeypatch.setattr(telnyx_voice.settings, "TELNYX_FROM_NUMBER", "+16175550000")
    monkeypatch.setattr(telnyx_voice.settings, "VOICE_SCRIPT_MODE", "static")
    company = _seed_company()
    created = voice.create_voice_call(
        company,
        provider="pytest",
        campaign_id="test_call",
        trade_code="roofing",
    )
    call_id = created["id"]
    voice.update_voice_call(call_id, provider_call_id="v3:test-answered")
    state = base64.b64encode(
        json.dumps({"voice_call_id": call_id, "company_id": company["id"]}).encode()
    ).decode()
    actions: list[str] = []

    def fake_action(call_control_id, action, payload):
        actions.append(action)
        return {"ok": True}

    original = telnyx_voice._call_action
    telnyx_voice._call_action = fake_action
    try:
        result = telnyx_voice.handle_webhook(
            {
                "data": {
                    "event_type": "call.answered",
                    "payload": {
                        "client_state": state,
                        "call_control_id": "v3:test-answered",
                    },
                }
            }
        )
    finally:
        telnyx_voice._call_action = original
    assert result["action"] == "answered_test_call"
    assert result["waiting_for_amd"] is False
    assert "gather_using_speak" in actions
    assert voice.get_voice_call(call_id)["status"] == "in_call"


def test_test_call_gather_sem_digitos_nao_desliga():
    company = _seed_company()
    created = voice.create_voice_call(
        company,
        provider="pytest",
        campaign_id="test_call",
        trade_code="roofing",
    )
    call_id = created["id"]
    voice.update_voice_call(
        call_id, provider_call_id="v3:test-gather", status="in_call"
    )
    state = base64.b64encode(
        json.dumps({"voice_call_id": call_id, "company_id": company["id"]}).encode()
    ).decode()
    actions: list[str] = []

    def fake_action(call_control_id, action, payload):
        actions.append(action)
        return {"ok": True}

    original = telnyx_voice._call_action
    telnyx_voice._call_action = fake_action
    try:
        result = telnyx_voice.handle_webhook(
            {
                "data": {
                    "event_type": "call.gather.ended",
                    "payload": {
                        "client_state": state,
                        "call_control_id": "v3:test-gather",
                        "digits": "",
                    },
                }
            }
        )
    finally:
        telnyx_voice._call_action = original
    assert result["action"] == "gather_ended_test_keepalive"
    assert "hangup" not in actions


def test_test_call_speak_ended_nao_desliga():
    company = _seed_company()
    created = voice.create_voice_call(
        company,
        provider="pytest",
        campaign_id="test_call",
        trade_code="roofing",
    )
    call_id = created["id"]
    voice.update_voice_call(
        call_id, provider_call_id="v3:test-speak", status="in_call"
    )
    actions: list[str] = []

    def fake_action(call_control_id, action, payload):
        actions.append(action)
        return {"ok": True}

    original = telnyx_voice._call_action
    telnyx_voice._call_action = fake_action
    try:
        result = telnyx_voice.handle_webhook(
            {
                "data": {
                    "event_type": "call.speak.ended",
                    "payload": {
                        "call_control_id": "v3:test-speak",
                    },
                }
            }
        )
    finally:
        telnyx_voice._call_action = original
    assert result["action"] == "media_ended_test_keepalive"
    assert "hangup" not in actions

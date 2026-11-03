"""Roteiros de voz (Fase 2B): seed, versão, preview e aprovação."""
from __future__ import annotations

import pytest

from backend.services import b2b_voice, showcase, telnyx_voice, voice_scripts


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.setenv("VOICE_NOW_ISO", "2026-11-02T16:00:00+00:00")
    b2b_voice.init()
    voice_scripts.init()
    conn = b2b_voice.get_conn()
    try:
        for table in (
            "voice_calls",
            "call_attempts",
            "voice_suppressions",
            "dnc_checks",
            "prospect_companies",
        ):
            conn.execute(f"DELETE FROM {table}")
        conn.execute("DELETE FROM voice_script_versions")
        conn.execute("DELETE FROM voice_script_overrides")
        conn.execute("DELETE FROM voice_scripts")
        conn.execute(
            "DELETE FROM voice_meta WHERE key='scripts_template_version'"
        )
        conn.commit()
    finally:
        conn.close()
    voice_scripts._INIT["path"] = None
    voice_scripts.init()
    yield


def test_seed_cria_roteiros_com_template_oficial():
    scripts = voice_scripts.list_scripts()
    assert len(scripts) == 15
    codes = {item["trade_code"] for item in scripts}
    assert {"remodeling", "roofing", "electrical", "painting", "hvac"} <= codes
    for item in scripts:
        assert item["status"] == "draft"
        assert item["version"] == 1
        assert "Opening & Pitch" in item["body"]
        assert "automated assistant" in item["body"].lower()
        assert "before any competitor finds out" in item["body"]
        assert "If Yes / Press 1" in item["body"]
        assert "If No / Stop" in item["body"]


def test_approve_all_aprova_os_15():
    result = voice_scripts.approve_all(user_id=7)
    assert result["approved"] == 15
    scripts = voice_scripts.list_scripts()
    assert all(item["status"] == "approved" for item in scripts)
    assert voice_scripts.approved_for_trade("roofing") is not None


def test_override_cidade_tem_prioridade_sobre_global(monkeypatch):
    voice_scripts.approve_all(user_id=7)
    override = voice_scripts.save_override(
        "roofing",
        "city",
        "New York",
        "CITY OVERRIDE for {{company}}",
        disclosure="City disclosure.",
        assistant_id="assistant-city",
        user_id=7,
    )
    # Draft override não entra em produção; global continua.
    global_script = voice_scripts.get_effective_script(
        "roofing", city="New York", state="NY"
    )
    assert global_script["scope"] == "global"
    voice_scripts.approve_override(override["id"], user_id=7)
    city_script = voice_scripts.get_effective_script(
        "roofing", city="New York", state="NY"
    )
    assert city_script["scope"] == "city"
    assert city_script["body"] == "CITY OVERRIDE for {{company}}"
    other_city = voice_scripts.get_effective_script(
        "roofing", city="Boston", state="MA"
    )
    assert other_city["scope"] == "global"


def test_save_draft_incrementa_versao_e_approve():
    updated = voice_scripts.save_draft(
        "roofing",
        "ROLE: test {{company}} in {{city}}.",
        disclosure="This is an automated assistant.",
        assistant_id="assistant-123",
        user_id=7,
    )
    assert updated["version"] == 2
    assert updated["status"] == "draft"
    approved = voice_scripts.approve("roofing", user_id=7)
    assert approved["status"] == "approved"
    assert approved["approved_by"] == 7
    assert voice_scripts.approved_for_trade("roofing") is not None


def test_render_variaveis_e_showcase_line(monkeypatch):
    monkeypatch.setattr(
        showcase,
        "available",
        lambda city, trade: {
            "available": True,
            "exact_count": 7,
            "city_total": 10,
            "min_items": 3,
            "page_path": "/en/new-york/roofing",
        },
    )
    result = voice_scripts.render(
        "roofing", company="Acme Roofing", city="New York", permit_count=12
    )
    assert "Acme Roofing" in result["body"]
    assert "New York" in result["body"]
    assert "7 active roofing opportunities" in result["body"]
    assert "{{company}}" not in result["body"]


def test_render_fallback_cidade_nao_promete_nicho(monkeypatch):
    monkeypatch.setattr(
        showcase,
        "available",
        lambda city, trade: {
            "available": False,
            "exact_count": 0,
            "city_total": 42,
            "min_items": 3,
            "page_path": "/en/dallas/roofing",
        },
    )
    result = voice_scripts.render("roofing", city="Dallas")
    assert "42 active property opportunities" in result["body"]
    assert "42 active roofing" not in result["body"]


def test_start_ai_assistant_chama_telnyx(monkeypatch):
    monkeypatch.setattr(telnyx_voice.settings, "VOICE_STAGING_MODE", False)
    monkeypatch.setattr(telnyx_voice.settings, "TELNYX_API_KEY", "key")
    monkeypatch.setattr(telnyx_voice.settings, "TELNYX_CONNECTION_ID", "conn")
    monkeypatch.setattr(telnyx_voice.settings, "TELNYX_FROM_NUMBER", "+16175550000")
    calls = []

    class Response:
        status_code = 200

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return Response()

    monkeypatch.setattr(telnyx_voice.httpx, "post", fake_post)
    result = telnyx_voice.start_ai_assistant("v3:test-call", "assistant-123")
    assert result["ok"] is True
    assert calls
    assert calls[0][0].endswith("/calls/v3:test-call/actions/ai_assistant_start")
    assert calls[0][1]["json"] == {"assistant": {"id": "assistant-123"}}


def test_chamada_real_exige_roteiro_aprovado(monkeypatch):
    monkeypatch.setattr(telnyx_voice.settings, "VOICE_STAGING_MODE", False)
    monkeypatch.setattr(telnyx_voice.settings, "TELNYX_API_KEY", "key")
    monkeypatch.setattr(telnyx_voice.settings, "TELNYX_CONNECTION_ID", "conn")
    monkeypatch.setattr(telnyx_voice.settings, "TELNYX_FROM_NUMBER", "+16175550000")
    phone = "+16175550999"
    b2b_voice.import_licenses_csv(
        "company_name,phone,city,state,trade,license_status\n"
        f"Script Guard Co,{phone},Boston,MA,roofing,active\n",
        source_name="pytest",
    )
    b2b_voice.check_dnc(phone, listed=False, source="pytest")
    conn = b2b_voice.get_conn()
    try:
        company = dict(
            conn.execute(
                "SELECT * FROM prospect_companies WHERE phone=?", (phone,)
            ).fetchone()
        )
    finally:
        conn.close()
    result = telnyx_voice.create_call(company, dry_run=False)
    assert result["ok"] is False
    assert result["reason"] == "script_not_approved"


def test_sync_inclui_voz_nativa_tools_e_dtmf(monkeypatch):
    voice_scripts.approve_all(user_id=7)
    monkeypatch.setattr(voice_scripts.settings, "TELNYX_API_KEY", "key")
    monkeypatch.setattr(
        voice_scripts.settings, "TELNYX_WEBHOOK_SECRET", "tool-secret"
    )
    monkeypatch.setattr(
        voice_scripts.settings, "TELNYX_ASSISTANT_VOICE", "Telnyx.Ultra.Asher"
    )
    monkeypatch.setattr(voice_scripts.settings, "TELNYX_ASSISTANT_MODEL", "")
    captured: dict = {}

    class Response:
        status_code = 200
        content = b'{"data":{"id":"assistant-new"}}'

        def json(self):
            return {"data": {"id": "assistant-new"}}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["body"] = json
        return Response()

    monkeypatch.setattr(voice_scripts.httpx, "post", fake_post)
    result = voice_scripts.sync_to_telnyx("roofing")
    assert result["ok"] is True
    assert result["assistant_id"] == "assistant-new"
    body = captured["body"]
    assert body["voice_settings"]["voice"] == "Telnyx.Ultra.Asher"
    assert body["telephony_settings"]["disable_dtmf"] is False
    assert "model" not in body
    assert "send_showcase_link" in body["instructions"]
    names = {tool["webhook"]["name"] for tool in body["tools"]}
    assert names == {
        "mark_acceptance",
        "send_showcase_link",
        "capture_email",
        "remove_from_list",
    }
    for tool in body["tools"]:
        assert tool["webhook"]["url"].endswith(
            "/api/voice/telnyx/tools/" + tool["webhook"]["name"]
            + "?secret=tool-secret"
        )


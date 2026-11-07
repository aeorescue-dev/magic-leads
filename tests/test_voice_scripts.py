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
        assert item["status"] == "approved"
        assert item["version"] == 1
        assert "{{company | Contractor}}" in item["body"]
        assert "magicleads.app" in item["body"]
        assert "{{count}}" in item["body"]
        assert "automated message" in item["body"]
        assert "verified address" in item["body"]
        assert "send a letter" in item["body"]
        assert "press 2" in item["body"].lower()
        assert "five local contractors" in item["body"]
        assert "If Yes / Press 1" not in item["body"]


def test_approve_all_is_idempotent_when_v3_is_already_approved():
    result = voice_scripts.approve_all(user_id=7)
    assert result["approved"] == 0
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
        lambda city, trade, **kwargs: {
            "available": True,
            "exact_count": 7,
            "city_total": 10,
            "min_items": 3,
            "page_path": "/en/new-york/roofing",
            "fresh": True,
            "ready": True,
            "built_at": "2026-11-04T12:00:00+00:00",
            "age_hours": 1.0,
        },
    )
    result = voice_scripts.render(
        "roofing", company="Acme Roofing", city="New York", permit_count=12
    )
    assert "Acme Roofing" in result["body"]
    assert "New York" in result["body"]
    assert "7 active opportunities" in result["body"]
    assert "{{company}}" not in result["body"]


def test_render_company_fallback_usa_contractor(monkeypatch):
    monkeypatch.setattr(
        showcase,
        "available",
        lambda city, trade, **kwargs: {
            "available": True,
            "exact_count": 7,
            "city_total": 10,
            "min_items": 3,
            "page_path": "/en/new-york/roofing",
            "fresh": True,
            "ready": True,
            "built_at": "2026-11-04T12:00:00+00:00",
            "age_hours": 1.0,
        },
    )
    result = voice_scripts.render("roofing", company="", city="New York")
    assert result["greeting"].startswith("Hi Contractor.")
    assert "Hi ," not in result["greeting"]


def test_render_usa_contagem_exata_do_nicho(monkeypatch):
    monkeypatch.setattr(
        showcase,
        "available",
        lambda city, trade, **kwargs: {
            "available": True,
            "exact_count": 42,
            "city_total": 100,
            "min_items": 5,
            "page_path": "/en/dallas/roofing",
            "fresh": True,
            "ready": True,
            "built_at": "2026-11-04T12:00:00+00:00",
            "age_hours": 1.0,
        },
    )
    result = voice_scripts.render("roofing", city="Dallas")
    assert "42 active opportunities" in result["body"]


def test_render_bloqueia_nicho_sem_inventario_exato(monkeypatch):
    monkeypatch.setattr(
        showcase,
        "available",
        lambda city, trade, **kwargs: {
            "available": False,
            "exact_count": 0,
            "city_total": 42,
            "min_items": 5,
            "page_path": "/en/dallas/roofing",
            "fresh": True,
            "ready": True,
            "built_at": "2026-11-04T12:00:00+00:00",
            "age_hours": 1.0,
        },
    )
    with pytest.raises(ValueError, match="showcase_unavailable"):
        voice_scripts.render("roofing", city="Dallas")


def test_render_bloqueia_contagem_fraca(monkeypatch):
    monkeypatch.setattr(
        showcase,
        "available",
        lambda city, trade, **kwargs: {
            "available": False,
            "exact_count": 0,
            "city_total": 3,
            "min_items": 5,
            "page_path": "/en/dallas/roofing",
            "fresh": True,
            "ready": False,
            "built_at": "2026-11-04T12:00:00+00:00",
            "age_hours": 1.0,
        },
    )
    with pytest.raises(ValueError, match="showcase_unavailable"):
        voice_scripts.render("roofing", city="Dallas")


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
        conn.execute(
            "UPDATE voice_scripts SET status='draft' WHERE trade_code='roofing'"
        )
        conn.commit()
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


def test_sync_all_shared_assistant_atribui_aos_15(monkeypatch):
    voice_scripts.approve_all(user_id=7)
    monkeypatch.setattr(voice_scripts.settings, "TELNYX_API_KEY", "key")
    monkeypatch.setattr(
        voice_scripts.settings, "TELNYX_SHARED_ASSISTANT_ID", "assistant-shared"
    )
    monkeypatch.setattr(
        voice_scripts.settings, "TELNYX_WEBHOOK_SECRET", "tool-secret"
    )
    monkeypatch.setattr(
        voice_scripts.settings, "TELNYX_ASSISTANT_VOICE", "Telnyx.Ultra.test"
    )
    calls: list[str] = []

    class Response:
        status_code = 200
        content = b'{"id":"assistant-shared"}'

        def json(self):
            return {"id": "assistant-shared"}

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append(url)
        return Response()

    monkeypatch.setattr(voice_scripts.httpx, "post", fake_post)
    result = voice_scripts.sync_all()
    assert result["ok"] is True
    assert result["shared"] is True
    assert result["synced"] == 15
    assert result["assistant_id"] == "assistant-shared"
    assert len(calls) == 1
    assert calls[0].endswith("/ai/assistants/assistant-shared")
    assert all(
        item["assistant_id"] == "assistant-shared"
        for item in voice_scripts.list_scripts()
    )


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
    assert body["telephony_settings"]["disable_dtmf"] is True
    assert body["telephony_settings"]["recording_settings"]["enabled"] is False
    assert body["transcription"]["model"] == "deepgram/nova-3"
    assert "gmail.com" in body["transcription"]["settings"]["keyterm"]
    assert "noise_suppression" not in body["telephony_settings"]
    assert (
        body["telephony_settings"]["voicemail_detection"][
            "on_voicemail_detected"
        ]["action"]
        == "stop_assistant"
    )
    assert "model" not in body
    assert "remove_from_list" in body["instructions"]
    assert "Do not ask for an email" in body["instructions"]
    assert "send_showcase_link" not in body["instructions"]
    names = {tool["webhook"]["name"] for tool in body["tools"]}
    assert names == {"remove_from_list"}
    assert "MagicLeads dot app" in body["instructions"]
    for tool in body["tools"]:
        assert tool["webhook"]["url"].endswith(
            "/api/voice/telnyx/tools/" + tool["webhook"]["name"]
            + "?secret=tool-secret"
        )



def _guard_info(exact=0, city_total=12806, fresh=True):
    return {
        "available": exact > 0,
        "exact_count": exact,
        "city_total": city_total,
        "min_items": 5,
        "page_path": "/en/new-york",
        "fresh": fresh,
        "ready": exact > 0,
        "built_at": "2026-11-05T12:00:00+00:00",
        "age_hours": 1.0,
    }


def test_guard_default_exact_blocks_gc_even_with_city_total(monkeypatch):
    monkeypatch.setattr(voice_scripts.settings, "VOICE_GUARD_SCOPES", "exact")
    monkeypatch.setattr(
        showcase,
        "available",
        lambda city, trade, **kwargs: _guard_info(0, 12806),
    )
    guard = voice_scripts.showcase_guard("general_contractor", "New York")
    assert guard["ready"] is False
    assert guard["scope"] == "none"


def test_guard_bundle_allows_gc_when_two_trades_have_inventory(monkeypatch):
    monkeypatch.setattr(
        voice_scripts.settings, "VOICE_GUARD_SCOPES", "exact,bundle"
    )
    counts = {"plumbing": 10, "hvac": 20}

    def fake_available(city, trade, **kwargs):
        return _guard_info(counts.get(trade, 0), 12806)

    monkeypatch.setattr(showcase, "available", fake_available)
    guard = voice_scripts.showcase_guard("general_contractor", "New York")
    assert guard["ready"] is True
    assert guard["scope"] == "bundle"
    assert guard["bundle_code"] == "home_services"
    assert guard["count"] == 30
    assert "home-service opportunities" in guard["line"]


def test_guard_bundle_requires_two_trades(monkeypatch):
    monkeypatch.setattr(
        voice_scripts.settings, "VOICE_GUARD_SCOPES", "exact,bundle"
    )
    counts = {"plumbing": 30}

    def fake_available(city, trade, **kwargs):
        return _guard_info(counts.get(trade, 0), 12806)

    monkeypatch.setattr(showcase, "available", fake_available)
    guard = voice_scripts.showcase_guard("general_contractor", "New York")
    assert guard["ready"] is False


def test_guard_city_only_in_authorized_cities(monkeypatch):
    monkeypatch.setattr(
        voice_scripts.settings, "VOICE_GUARD_SCOPES", "exact,bundle,city"
    )
    monkeypatch.setattr(
        voice_scripts.settings, "VOICE_CITY_SCOPE_CITIES", "Dallas"
    )
    monkeypatch.setattr(voice_scripts.settings, "VOICE_CITY_MIN_TOTAL", 3000)
    monkeypatch.setattr(
        showcase,
        "available",
        lambda city, trade, **kwargs: _guard_info(0, 12806),
    )

    # Nova Iorque não está na allowlist: nem GC nem roofing podem usar city.
    gc_ny = voice_scripts.showcase_guard("general_contractor", "New York")
    assert gc_ny["ready"] is False
    assert gc_ny["scope"] == "none"
    roofing_ny = voice_scripts.showcase_guard("roofing", "New York")
    assert roofing_ny["ready"] is False

    # Dallas está na allowlist: city vale para GC e para os restantes trades.
    gc_dallas = voice_scripts.showcase_guard("general_contractor", "Dallas")
    assert gc_dallas["ready"] is True
    assert gc_dallas["scope"] == "city"
    assert "property opportunities" in gc_dallas["line"]
    roofing_dallas = voice_scripts.showcase_guard("roofing", "Dallas")
    assert roofing_dallas["ready"] is True
    assert roofing_dallas["scope"] == "city"


def test_template_version_propaga_para_scripts_existentes():
    conn = b2b_voice.get_conn()
    try:
        conn.execute("UPDATE voice_scripts SET version=3, body='OLD BODY'")
        conn.execute(
            "UPDATE voice_meta SET value='2026-11-04.3' "
            "WHERE key='scripts_template_version'"
        )
        conn.commit()
    finally:
        conn.close()

    voice_scripts._INIT["path"] = None
    voice_scripts.init()
    scripts = voice_scripts.list_scripts()
    assert len(scripts) == 15
    assert all(item["version"] == 4 for item in scripts)
    assert all(item["body"] == voice_scripts.DEFAULT_TEMPLATE for item in scripts)
    assert all(item["status"] == "approved" for item in scripts)


def test_render_bloqueia_count_fora_do_scope_exact(monkeypatch):
    monkeypatch.setattr(
        voice_scripts,
        "showcase_guard",
        lambda *args, **kwargs: {
            "ready": True,
            "line": "over 5,000 active home-service opportunities",
            "count": 5000,
            "scope": "bundle",
        },
    )
    with pytest.raises(ValueError, match="count_requires_exact_scope"):
        voice_scripts.render("plumbing", company="Acme", city="New York")


def test_guard_city_dallas_permite_trades_sem_exact(monkeypatch):
    monkeypatch.setattr(
        voice_scripts.settings, "VOICE_GUARD_SCOPES", "exact,bundle,city"
    )
    monkeypatch.setattr(
        voice_scripts.settings, "VOICE_CITY_SCOPE_CITIES", "Dallas"
    )
    monkeypatch.setattr(voice_scripts.settings, "VOICE_CITY_MIN_TOTAL", 3000)
    monkeypatch.setattr(
        showcase,
        "available",
        lambda city, trade, **kwargs: _guard_info(0, 3857),
    )
    dallas = voice_scripts.showcase_guard("electrical", "Dallas")
    assert dallas["ready"] is True
    assert dallas["scope"] == "city"
    assert "property opportunities" in dallas["line"]

    new_york = voice_scripts.showcase_guard("electrical", "New York")
    assert new_york["ready"] is False

"""Auto-scheduler e segmentos cidade+nicho (Fase 2A automação)."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from backend.services import auto_dialer, showcase, telnyx_voice
from backend.services import b2b_voice as voice
from backend.services.db import get_connection
from backend.services.timeutil import NY_TZ

NOW = datetime(2026, 11, 2, 16, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.setenv("VOICE_NOW_ISO", NOW.isoformat())
    monkeypatch.setattr(showcase.settings, "SHOWCASE_MIN_ITEMS", 3)
    monkeypatch.setattr(showcase.settings, "SHOWCASE_WINDOW_DAYS", 30)
    monkeypatch.setattr(showcase.settings, "EMAIL_API_KEY", "")
    monkeypatch.setattr(showcase.settings, "EMAIL_FROM", "")

    async def _no_sleep(_seconds):
        return None

    monkeypatch.setattr(auto_dialer.asyncio, "sleep", _no_sleep)
    voice.init()
    conn = voice.get_conn()
    try:
        for table in (
            "voice_campaign_skips",
            "voice_campaigns",
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
        leads.execute("DELETE FROM leads WHERE external_id LIKE 'pytest-%'")
        leads.commit()
    finally:
        leads.close()
    showcase._CACHE.clear()
    yield


def _seed_lead(city: str, state: str, category: str, zip_code: str, idx: int) -> None:
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO leads
              (external_id, source_type, address, city, state, zip_code,
               issue_category, date_reported, signal_type, signal_status,
               owner_name, is_junk)
            VALUES (?, 'pytest', ?, ?, ?, ?, ?, ?, 'open_request', 'open',
                    'Auto Owner', 0)
            """,
            (
                f"pytest-auto-{city}-{category}-{idx}",
                f"{400 + idx} {category} Ave",
                city,
                state,
                zip_code,
                category,
                NOW.isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _import_company(
    phone: str, city: str, state: str, trade: str = "Roofing"
) -> None:
    csv_text = (
        "company_name,contact_name,phone,email,city,state,license_status,trade,"
        "license_number,permit_count\n"
        f"Auto {city} Co,Test,{phone},{phone[1:]}@example.com,{city},{state},"
        f"active,{trade},LIC-{phone[1:]},7\n"
    )
    voice.import_licenses_csv(csv_text, source_name="pytest-auto")
    voice.check_dnc(phone, listed=False, source="pytest")
    voice.sync_company_trades()


def test_auto_dialer_dry_run_dispara_chamadas_sem_vitrine_precoce():
    for idx in range(3):
        _seed_lead("Boston", "MA", "Roof", "02118", idx)
    showcase.build_pages()
    for idx, phone in enumerate(("+16175550101", "+16175550102", "+16175550103")):
        _import_company(phone, "Boston", "MA")

    campaign = voice.create_campaign("Auto Boston Roofing", "Boston", "Roofing", 2)
    asyncio.run(auto_dialer.run_campaign(campaign["id"]))

    final = voice.get_campaign(campaign["id"])
    assert final is not None
    assert final["status"] == "completed"
    assert final["calls_started"] == 2
    # A vitrine so sai depois do consentimento (tool capture_email).
    assert final["showcases_sent"] == 0

    conn = voice.get_conn()
    try:
        calls = conn.execute(
            "SELECT * FROM voice_calls WHERE campaign_id=?", (str(campaign["id"]),)
        ).fetchall()
        assert len(calls) == 2
        assert all(row["showcase_link_id"] is None for row in calls)
        assert all(row["status"] == "dry_run" for row in calls)
    finally:
        conn.close()


def test_segments_classificam_dedicada_e_fallback():
    for idx in range(5):
        _seed_lead("Boston", "MA", "Roof", "02118", idx)
    for idx in range(5):
        _seed_lead("Dallas", "TX", "Structure", "75201", idx)
    showcase.build_pages()
    _import_company("+16175550104", "Boston", "MA")
    _import_company("+12145550105", "Dallas", "TX")

    segments = voice.segments()
    boston = next(
        s for s in segments if s["city"] == "Boston" and s["trade"] == "Roofing"
    )
    dallas = next(
        s for s in segments if s["city"] == "Dallas" and s["trade"] == "Roofing"
    )
    assert boston["showcase_mode"] == "dedicated"
    assert boston["showcase_exact"] >= 5
    assert dallas["showcase_mode"] == "city_fallback"
    assert dallas["showcase_exact"] == 0
    assert dallas["showcase_city_total"] >= 5


def test_campanha_interrompida_e_fechada_no_arranque():
    campaign = voice.create_campaign("Auto interrupted", "Boston", "Roofing", 5)
    closed = voice.mark_interrupted_campaigns()
    assert closed >= 1
    final = voice.get_campaign(campaign["id"])
    assert final["status"] == "error"
    assert "interrompida" in (final["error"] or "").lower()


def test_cota_total_com_lote_diario_pausa_e_retoma():
    for idx in range(3):
        _seed_lead("Boston", "MA", "Roof", "02118", idx)
    showcase.build_pages()
    for idx, phone in enumerate(("+16175550111", "+16175550112", "+16175550113")):
        _import_company(phone, "Boston", "MA")
    campaign = voice.create_campaign(
        "Batch 1", "Boston", "Roofing", 3, 0, 3, 1, True, False
    )
    asyncio.run(auto_dialer.run_campaign(campaign["id"]))
    paused = voice.get_campaign(campaign["id"])
    assert paused["status"] == "paused"
    assert paused["calls_started"] == 1
    assert paused["next_batch_at"]

    voice.update_campaign(campaign["id"], status="running", next_batch_at=None)
    asyncio.run(auto_dialer.run_campaign(campaign["id"]))
    paused2 = voice.get_campaign(campaign["id"])
    assert paused2["status"] == "paused"
    assert paused2["calls_started"] == 2

    voice.update_campaign(campaign["id"], status="running", next_batch_at=None)
    asyncio.run(auto_dialer.run_campaign(campaign["id"]))
    final = voice.get_campaign(campaign["id"])
    assert final["status"] == "completed"
    assert final["calls_started"] == 3


def test_auto_dialer_pausa_no_limite_diario(monkeypatch):
    for idx in range(3):
        _seed_lead("Boston", "MA", "Roof", "02118", idx)
    showcase.build_pages()
    _import_company("+16175550121", "Boston", "MA")
    campaign = voice.create_campaign("Budget", "Boston", "Roofing", 3)
    monkeypatch.setattr(
        auto_dialer.telnyx_voice,
        "create_call",
        lambda *a, **k: {
            "ok": False,
            "reason": "daily_budget_reached",
            "message": "limite",
        },
    )
    asyncio.run(auto_dialer.run_campaign(campaign["id"]))
    final = voice.get_campaign(campaign["id"])
    assert final["status"] == "paused"
    assert final["calls_started"] == 0
    assert final["error"] == "daily_budget_reached"
    assert final["next_batch_at"]


def _company_for_budget(phone: str) -> dict:
    _import_company(phone, "Boston", "MA")
    conn = voice.get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM prospect_companies WHERE phone=?", (phone,)
        ).fetchone()
        return dict(row)
    finally:
        conn.close()


def test_campaign_budget_daily_e_total():
    company = _company_for_budget("+16175550131")
    daily = voice.create_campaign(
        "Daily", "Boston", "Roofing", 10, 0, 10, 10, True, False, 100.0, 0.05, 2
    )
    call = voice.create_voice_call(
        company, provider="telnyx", campaign_id=str(daily["id"])
    )
    voice.update_voice_call(call["id"], status="ended", cost_cents=6)
    status = voice.campaign_budget_status(daily["id"])
    assert status["blocked_reason"] == "daily_budget_reached"

    total = voice.create_campaign(
        "Total", "Boston", "Roofing", 10, 0, 10, 10, True, False, 0.10, 100.0, 2
    )
    call = voice.create_voice_call(
        company, provider="telnyx", campaign_id=str(total["id"])
    )
    voice.update_voice_call(call["id"], status="ended", cost_cents=6)
    status = voice.campaign_budget_status(total["id"])
    assert status["blocked_reason"] == "total_budget_reached"


def test_campaign_budget_dias_termina():
    _company_for_budget("+16175550132")
    campaign = voice.create_campaign(
        "Dias", "Boston", "Roofing", 10, 0, 10, 10, True, False, 100.0, 100.0, 1
    )
    conn = voice.get_conn()
    try:
        conn.execute(
            "UPDATE voice_campaigns SET started_at=? WHERE id=?",
            ((NOW - timedelta(days=3)).isoformat(), campaign["id"]),
        )
        conn.commit()
    finally:
        conn.close()
    status = voice.campaign_budget_status(campaign["id"])
    assert status["blocked_reason"] == "days_limit_reached"


def test_create_call_respeita_total_budget_campanha(monkeypatch):
    monkeypatch.setattr(telnyx_voice.settings, "VOICE_STAGING_MODE", False)
    monkeypatch.setattr(telnyx_voice.settings, "TELNYX_API_KEY", "key")
    monkeypatch.setattr(telnyx_voice.settings, "TELNYX_CONNECTION_ID", "conn")
    monkeypatch.setattr(telnyx_voice.settings, "TELNYX_FROM_NUMBER", "+16175550000")
    company = _company_for_budget("+16175550133")
    campaign = voice.create_campaign(
        "TotalCall", "Boston", "Roofing", 10, 0, 10, 10, True, False, 0.10, 100.0, 2
    )
    call = voice.create_voice_call(
        company, provider="telnyx", campaign_id=str(campaign["id"])
    )
    voice.update_voice_call(call["id"], status="ended", cost_cents=6)
    result = telnyx_voice.create_call(
        company, campaign_id=str(campaign["id"]), dry_run=False
    )
    assert result["ok"] is False
    assert result["reason"] == "total_budget_reached"


def test_auto_dialer_termina_no_orcamento_total(monkeypatch):
    for idx in range(3):
        _seed_lead("Boston", "MA", "Roof", "02118", idx)
    showcase.build_pages()
    _import_company("+16175550134", "Boston", "MA")
    campaign = voice.create_campaign(
        "TotalEnd", "Boston", "Roofing", 3, 0, 3, 3, True, False, 0.10, 5.0, 30
    )
    monkeypatch.setattr(
        auto_dialer.telnyx_voice,
        "create_call",
        lambda *a, **k: {"ok": False, "reason": "total_budget_reached"},
    )
    asyncio.run(auto_dialer.run_campaign(campaign["id"]))
    final = voice.get_campaign(campaign["id"])
    assert final["status"] == "completed"
    assert final["error"] == "total_budget_reached"
    assert final["finished_at"]


def test_auto_dialer_pausa_fora_da_janela_sem_saltar(monkeypatch):
    _import_company("+16175550135", "Boston", "MA")
    campaign = voice.create_campaign(
        "ForaJanela", "Boston", "Roofing", 3, 0, 3, 3, True, False
    )
    monkeypatch.setattr(
        auto_dialer.telnyx_voice,
        "create_call",
        lambda *a, **k: {"ok": False, "reason": "outside_hours"},
    )
    asyncio.run(auto_dialer.run_campaign(campaign["id"]))
    final = voice.get_campaign(campaign["id"])
    assert final["status"] == "paused"
    assert final["error"] == "outside_hours"
    assert final["next_batch_at"]
    assert final["skipped"] == 0


def test_retoma_campanha_pausada_vencida(monkeypatch):
    import backend.main as main_module

    _import_company("+16175550135", "Boston", "MA", "Roofing")
    _import_company("+16175550136", "Boston", "MA", "Roofing")
    _import_company("+16175550137", "Boston", "MA", "Roofing")
    campaign = voice.create_campaign(
        "Retoma", "Boston", "Roofing", 3, 0, 3, 3, True, False
    )
    past = (NOW - timedelta(minutes=5)).isoformat()
    voice.update_campaign(
        campaign["id"], status="paused", next_batch_at=past,
        error="daily_budget_reached",
    )
    launched: list[int] = []
    monkeypatch.setattr(
        main_module, "_launch_voice_campaign", lambda cid: launched.append(cid)
    )
    resumed = asyncio.run(main_module._resume_due_voice_campaigns())
    assert campaign["id"] in resumed
    assert campaign["id"] in launched
    final = voice.get_campaign(campaign["id"])
    assert final["status"] == "running"
    assert final["next_batch_at"] is None
    assert final["error"] is None


def test_retoma_termina_campanha_no_orcamento_total(monkeypatch):
    import backend.main as main_module

    company = _company_for_budget("+16175550136")
    campaign = voice.create_campaign(
        "RetomaTotal", "Boston", "Roofing", 3, 0, 3, 3, True, False, 0.10, 5.0, 30
    )
    call = voice.create_voice_call(
        company, provider="telnyx", campaign_id=str(campaign["id"])
    )
    voice.update_voice_call(call["id"], status="ended", cost_cents=6)
    past = (NOW - timedelta(minutes=5)).isoformat()
    voice.update_campaign(
        campaign["id"], status="paused", next_batch_at=past,
        error="daily_budget_reached",
    )
    monkeypatch.setattr(
        main_module, "_launch_voice_campaign", lambda cid: None
    )
    resumed = asyncio.run(main_module._resume_due_voice_campaigns())
    assert resumed == []
    final = voice.get_campaign(campaign["id"])
    assert final["status"] == "completed"
    assert final["error"] == "total_budget_reached"


def test_campanha_nao_repete_contacto_global_7_dias():
    company = _company_for_budget("+16175550140")
    first = voice.create_campaign(
        "Global A", "Boston", "Roofing", 1, 0, 1, 1, True, False
    )
    second = voice.create_campaign(
        "Global B", "Boston", "Roofing", 1, 0, 1, 1, True, False
    )
    call = voice.create_voice_call(
        company, provider="telnyx", campaign_id=str(first["id"])
    )
    voice.update_voice_call(call["id"], status="ended")
    ids = [
        row["id"]
        for row in voice.campaign_candidates(
            second["id"], "Boston", "Roofing", 50, True
        )
    ]
    assert company["id"] not in ids

    old = (NOW - timedelta(days=8)).isoformat()
    conn = voice.get_conn()
    try:
        conn.execute(
            "UPDATE voice_calls SET created_at=?, started_at=? WHERE id=?",
            (old, old, call["id"]),
        )
        conn.commit()
    finally:
        conn.close()
    ids = [
        row["id"]
        for row in voice.campaign_candidates(
            second["id"], "Boston", "Roofing", 50, True
        )
    ]
    assert company["id"] in ids


def test_auto_dialer_pausa_em_erro_http_transitorio(monkeypatch):
    _import_company("+16175550141", "TransientCity", "MA")
    conn = voice.get_conn()
    try:
        company = dict(
            conn.execute(
                "SELECT * FROM prospect_companies WHERE phone=?",
                ("+16175550141",),
            ).fetchone()
        )
    finally:
        conn.close()
    campaign = voice.create_campaign(
        "Transient", "TransientCity", "Roofing", 3, 0, 3, 3, True, False
    )
    # provider pytest: nao entra na exclusao global de contactos reais.
    failed = voice.create_voice_call(
        company, provider="pytest", campaign_id="other"
    )
    monkeypatch.setattr(
        auto_dialer.telnyx_voice,
        "create_call",
        lambda *a, **k: {
            "ok": False,
            "reason": "http_402",
            "voice_call_id": failed["id"],
        },
    )
    asyncio.run(auto_dialer.run_campaign(campaign["id"]))
    final = voice.get_campaign(campaign["id"])
    assert final["status"] == "paused"
    assert final["error"] == "http_402"
    assert final["skipped"] == 0
    assert voice.get_voice_call(failed["id"]) is None


def test_auto_dialer_usa_hora_de_inicio_da_campanha(monkeypatch):
    _import_company("+16175550142", "HourCity", "MA")
    campaign = voice.create_campaign(
        "Hour10", "HourCity", "Roofing", 2, 0, 2, 1, True, False,
        10.0, 2.0, 7, 10,
    )
    assert campaign["start_hour_et"] == 10
    monkeypatch.setattr(
        auto_dialer.telnyx_voice,
        "create_call",
        lambda *a, **k: {"ok": True, "dry_run": True, "voice_call_id": 0},
    )
    asyncio.run(auto_dialer.run_campaign(campaign["id"]))
    final = voice.get_campaign(campaign["id"])
    assert final["status"] == "paused"
    next_at = datetime.fromisoformat(final["next_batch_at"]).replace(
        tzinfo=timezone.utc
    )
    assert next_at.astimezone(NY_TZ).hour == 10


def test_campaign_guarda_intervalo_e_plano():
    campaign = voice.create_campaign(
        "Plan", "PlanCity", "Roofing", 5, 0, 5, 1, True, False,
        10.0, 2.0, 7, 10, 600, [1, 2, 3],
    )
    assert campaign["call_interval_seconds"] == 600
    assert campaign["batch_plan"] == "[1, 2, 3]"
    assert campaign["plan_index"] == 0


def test_campaign_batch_size_respeita_plano():
    campaign = {"batch_plan": "[2, 3]", "plan_index": 0, "batch_size": 9}
    assert auto_dialer._campaign_batch_size(campaign) == 2
    campaign["plan_index"] = 1
    assert auto_dialer._campaign_batch_size(campaign) == 3
    campaign["plan_index"] = 9
    assert auto_dialer._campaign_batch_size(campaign) == 3
    assert auto_dialer._campaign_batch_size({"batch_size": 7}) == 7


def test_campaign_trade_plan_distribui_por_trade(monkeypatch):
    for phone in (
        "+16175550151",
        "+16175550152",
        "+16175550155",
        "+16175550156",
    ):
        _import_company(phone, "Multi", "MA", trade="Roofing")
    for phone in ("+16175550153", "+16175550154"):
        _import_company(phone, "Multi", "MA", trade="Painting")
    campaign = voice.create_campaign(
        name="Multi plan",
        city="Multi",
        trade="",
        max_calls=4,
        quota_total=4,
        batch_size=4,
        include_fallback=True,
        dry_run=False,
        budget_total_usd=10.0,
        budget_daily_usd=2.0,
        max_days=1,
        start_hour_et=0,
        call_interval_seconds=0,
        trade_plan=[
            {"trade": "Roofing", "quota": 2},
            {"trade": "Painting", "quota": 2},
        ],
    )
    assert campaign["trade_plan"]
    selected: list[str] = []
    from_numbers: list[str | None] = []
    monkeypatch.setattr(auto_dialer.settings, "VOICE_DID_DAILY_CAP", 2)
    monkeypatch.setattr(
        auto_dialer.settings,
        "TELNYX_FROM_NUMBER_SECONDARY",
        "+15189429910",
    )

    def fake_call(company, campaign_id, script_id, city, trade, dry_run, from_number=None):
        selected.append(trade)
        from_numbers.append(from_number)
        return {"ok": True, "dry_run": False, "voice_call_id": 0}

    monkeypatch.setattr(auto_dialer.telnyx_voice, "create_call", fake_call)
    asyncio.run(auto_dialer.run_campaign(campaign["id"]))
    final = voice.get_campaign(campaign["id"])
    assert final["status"] == "completed"
    assert final["calls_started"] == 4
    assert selected.count("roofing") == 2
    assert selected.count("painting") == 2
    assert from_numbers[:2] == ["", ""]
    assert from_numbers[2:] == ["+15189429910", "+15189429910"]


def test_auto_dialer_usa_intervalo_e_avanca_plano(monkeypatch):
    for idx, phone in enumerate(
        ("+16175550143", "+16175550144", "+16175550145")
    ):
        _import_company(phone, "PlanCity", "MA")
    campaign = voice.create_campaign(
        "Ramp", "PlanCity", "Roofing", 3, 0, 3, 1, True, False,
        10.0, 2.0, 7, 9, 600, [1, 2],
    )
    delays = []

    async def fake_sleep(seconds):
        delays.append(seconds)

    monkeypatch.setattr(auto_dialer.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(
        auto_dialer.telnyx_voice,
        "create_call",
        lambda *a, **k: {"ok": True, "dry_run": False, "voice_call_id": 0},
    )
    asyncio.run(auto_dialer.run_campaign(campaign["id"]))
    first = voice.get_campaign(campaign["id"])
    assert first["status"] == "paused"
    assert first["calls_started"] == 1
    assert first["plan_index"] == 1

    voice.update_campaign(campaign["id"], status="running", next_batch_at=None)
    asyncio.run(auto_dialer.run_campaign(campaign["id"]))
    final = voice.get_campaign(campaign["id"])
    assert final["status"] == "completed"
    assert final["calls_started"] == 3
    assert len(delays) == 1
    assert 480 <= delays[0] <= 720
    assert 600 not in delays


def test_metrics_calcula_funil(monkeypatch):
    _import_company("+16175550114", "Boston", "MA")
    conn = voice.get_conn()
    try:
        company = dict(
            conn.execute(
                "SELECT * FROM prospect_companies WHERE phone='+16175550114'"
            ).fetchone()
        )
    finally:
        conn.close()
    answered = voice.create_voice_call(company, provider="pytest", campaign_id="m1")
    voice.update_voice_call(
        answered["id"],
        status="ended",
        intent="showcase",
        answered_at=NOW.isoformat(),
        duration_seconds=60,
        listen_seconds=45,
        showcase_clicked_at=NOW.isoformat(),
        checkout_session_id="cs_metrics",
        revenue_cents=12000,
        cost_cents=100,
    )
    missed = voice.create_voice_call(company, provider="pytest", campaign_id="m1")
    voice.update_voice_call(
        missed["id"], status="ended", hangup_cause="no_answer", cost_cents=200
    )
    test_call = voice.create_voice_call(
        company, provider="pytest", campaign_id="test_call"
    )
    voice.update_voice_call(
        test_call["id"], status="ended", answered_at=NOW.isoformat()
    )
    result = voice.metrics(days=30)
    summary = result["summary"]
    assert summary["dialed"] == 2
    assert summary["answered"] == 1
    assert summary["answer_rate"] == 50.0
    assert summary["engagement_rate"] == 100.0
    assert summary["accepts"] == 1
    assert summary["accept_rate"] == 100.0
    assert summary["showcase_ctr"] == 100.0
    assert summary["checkout_rate"] == 100.0
    assert summary["subscription_rate"] == 100.0
    assert summary["revenue_per_accept_usd"] == 120.0
    assert summary["revenue_usd"] == 120.0
    assert summary["net_usd"] == 117.0
    assert result["funnel"]["dialed"] == 2
    assert result["funnel"]["answered"] == 1
    assert result["funnel"]["accepts"] == 1
    assert result["retention"][1]["seconds"] == 30
    assert result["retention"][1]["count"] == 1
    assert result["by_city_trade"]
    assert result["by_city_trade"][0]["accept_rate"] == 100.0
    assert result["by_state"][0]["state"] == "MA"
    assert result["by_state"][0]["subscription_rate"] == 100.0
    assert result["by_city"][0]["city"] == "Boston"
    assert result["by_trade"][0]["trade"] == "Roofing"


def test_bridge_contractor_entities_preenche_voice_db():
    leads = get_connection()
    try:
        leads.execute(
            "DELETE FROM contractor_entities WHERE entity_key LIKE 'pytest-bridge-%'"
        )
        for idx, (name, phone, city, state, niche) in enumerate(
            [
                ("Bridge Roofing LLC", "6175550201", "Boston", "MA", "roofing"),
                ("Bridge Electric LLC", "2145550202", "Dallas", "TX", "electrical"),
            ]
        ):
            leads.execute(
                """
                INSERT INTO contractor_entities
                  (entity_key, legal_name, normalized_name, city, state, phone,
                   email, license, niche_key, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'new')
                """,
                (
                    f"pytest-bridge-{idx}",
                    name,
                    name.lower(),
                    city,
                    state,
                    phone,
                    f"bridge{idx}@example.com",
                    f"LIC-{idx}",
                    niche,
                ),
            )
        leads.commit()
    finally:
        leads.close()

    result = voice.bridge_contractor_entities()
    assert result["imported"] >= 2
    conn = voice.get_conn()
    try:
        rows = [
            dict(r)
            for r in conn.execute(
                "SELECT company_name, city, state, trade FROM prospect_companies "
                "WHERE phone IN ('+16175550201','+12145550202')"
            ).fetchall()
        ]
    finally:
        conn.close()
    assert len(rows) == 2
    assert any(r["trade"] == "roofing" for r in rows)
    assert any(r["trade"] == "electrical" for r in rows)

    leads = get_connection()
    try:
        leads.execute(
            "DELETE FROM contractor_entities WHERE entity_key LIKE 'pytest-bridge-%'"
        )
        leads.commit()
    finally:
        leads.close()


def test_source_http_csv_importa_e_rebuilda_segmentos(monkeypatch):
    for idx in range(5):
        _seed_lead("Chicago", "IL", "Paint", "60601", idx)
    csv_text = (
        "company_name,contact_name,phone,email,city,state,license_status,trade,"
        "permit_count\n"
        "Source Painting,Ana,+13125550121,ana@example.com,Chicago,IL,active,Painting,6\n"
    )

    class FakeResponse:
        status_code = 200
        text = csv_text

        def raise_for_status(self):
            return None

    monkeypatch.setattr(
        voice.settings, "VOICE_SOURCE_ALLOWED_HOSTS", "example.com"
    )
    monkeypatch.setattr(
        voice.httpx, "get", lambda *args, **kwargs: FakeResponse()
    )
    source = voice.create_source(
        "Chicago licenses", "http_csv", "https://example.com/licenses.csv"
    )
    result = voice.sync_source(source["id"])
    assert result["ok"] is True
    assert result["import"]["imported"] == 1
    assert result["segments"] >= 1
    conn = voice.get_conn()
    try:
        ingest = conn.execute(
            "SELECT status, imported FROM raw_ingest WHERE source_id=?",
            (source["id"],),
        ).fetchone()
        assert ingest["status"] == "success"
        assert ingest["imported"] == 1
    finally:
        conn.close()
    segments = voice.cached_segments(city="Chicago", trade="Painting")
    assert segments
    assert segments[0]["showcase_mode"] == "dedicated"


def test_did_por_cidade_dallas_nao_usa_ny(monkeypatch):
    monkeypatch.setattr(
        auto_dialer.settings,
        "VOICE_DID_BY_CITY",
        '{"dallas":"+14699607326"}',
    )
    monkeypatch.setattr(
        auto_dialer.settings, "TELNYX_FROM_NUMBER", "+19292562550"
    )
    monkeypatch.setattr(
        auto_dialer.settings, "TELNYX_FROM_NUMBER_SECONDARY", "+15189429910"
    )
    for idx in range(3):
        _import_company(
            f"+12145550{idx:03d}", "Dallas", "TX", "Roofing"
        )
    campaign = voice.create_campaign(
        name="did-dallas",
        city="Dallas",
        trade="Roofing",
        max_calls=3,
        quota_total=3,
        trade_plan=[{"trade": "roofing", "quota": 3}],
    )
    captured: list[str] = []

    def fake_call(*args, **kwargs):
        captured.append(kwargs.get("from_number") or args[6])
        return {"ok": True, "dry_run": False, "voice_call_id": 0}

    monkeypatch.setattr(auto_dialer.telnyx_voice, "create_call", fake_call)
    asyncio.run(auto_dialer.run_campaign(campaign["id"]))
    assert captured == ["+14699607326"] * 3
    assert auto_dialer._did_for_city("New York") == ""
    assert auto_dialer._did_for_city("Dallas") == "+14699607326"


def test_did_por_cidade_aceita_formato_simples(monkeypatch):
    monkeypatch.setattr(
        auto_dialer.settings,
        "VOICE_DID_BY_CITY",
        "dallas=+14699607326,new york=+19292562550",
    )
    assert auto_dialer._did_for_city("Dallas") == "+14699607326"
    assert auto_dialer._did_for_city("New York") == "+19292562550"
    assert auto_dialer._did_for_city("Chicago") == ""

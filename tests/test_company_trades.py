"""Classificação multi-label e seleção de candidatos por trade secundário."""
from __future__ import annotations

import pytest

from backend.services import b2b_voice as voice


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.setenv("VOICE_NOW_ISO", "2026-11-02T16:00:00+00:00")
    voice.init()
    conn = voice.get_conn()
    try:
        for table in (
            "company_trades",
            "voice_calls",
            "voice_campaign_skips",
            "voice_campaigns",
            "call_attempts",
            "voice_suppressions",
            "dnc_checks",
            "prospect_companies",
        ):
            conn.execute(f"DELETE FROM {table}")
        conn.commit()
    finally:
        conn.close()
    yield


def _csv(company: str, phone: str, trade: str = "general_contractor") -> str:
    return (
        "company_name,contact_name,phone,city,state,license_status,trade,"
        "license_number,permit_count,permit_value_usd,years_active,employee_estimate\n"
        f"{company},John Smith,{phone},New York,NY,active,{trade},"
        f"LIC-{phone[1:]},4,250000,12,8\n"
    )


def test_sync_classifica_plumbing_e_hvac():
    voice.import_licenses_csv(
        _csv("Radant Plumbing & Heating", "+12125550123")
    )
    result = voice.sync_company_trades()
    assert result["companies"] == 1
    assert result["multi_trade"] == 1

    conn = voice.get_conn()
    try:
        company_id = conn.execute(
            "SELECT id FROM prospect_companies WHERE phone=?",
            ("+12125550123",),
        ).fetchone()[0]
    finally:
        conn.close()
    trades = {
        row["trade_code"]: row["confidence"]
        for row in voice.company_trades_for(company_id)
    }
    assert trades["plumbing"] >= 0.90
    assert trades["hvac"] >= 0.90


def test_campaign_candidates_usa_trade_secundario():
    voice.import_licenses_csv(
        _csv("Radant Plumbing & Heating", "+12125550124")
    )
    voice.sync_company_trades()
    campaign = voice.create_campaign(
        name="test-multi",
        city="New York",
        trade="plumbing",
        max_calls=1,
        quota_total=1,
        trade_plan=[{"trade": "plumbing", "quota": 1}],
    )
    rows = voice.campaign_candidates(
        int(campaign["id"]), "New York", "plumbing", 10, True
    )
    assert [row["company_name"] for row in rows] == [
        "Radant Plumbing & Heating"
    ]


def test_gc_generico_nao_entra_em_plumbing():
    voice.import_licenses_csv(_csv("ABC Construction Corp", "+12125550125"))
    result = voice.sync_company_trades()
    assert result["multi_trade"] == 0

    campaign = voice.create_campaign(
        name="test-gc",
        city="New York",
        trade="plumbing",
        max_calls=1,
        quota_total=1,
        trade_plan=[{"trade": "plumbing", "quota": 1}],
    )
    assert (
        voice.campaign_candidates(
            int(campaign["id"]), "New York", "plumbing", 10, True
        )
        == []
    )


def test_company_trade_stats_conta_distintos():
    voice.import_licenses_csv(
        _csv("Radant Plumbing & Heating", "+12125550126")
    )
    voice.sync_company_trades()
    stats = {
        row["trade"]: row["n"]
        for row in voice.company_trade_stats("New York", "NY")
    }
    assert stats["plumbing"] == 1
    assert stats["hvac"] == 1


def test_category_plan_mapeia_label_para_trade():
    import json

    campaign = voice.create_campaign(
        name="test-category",
        city="New York",
        trade="",
        max_calls=1,
        quota_total=1,
        trade_plan=[{"category": "Plumbing", "quota": 1}],
    )
    plan = json.loads(campaign["trade_plan"])
    assert plan == [{"trade": "plumbing", "quota": 1, "category": "Plumbing"}]


def test_gc_cap_bloqueia_quando_scope_nao_exact(monkeypatch):
    monkeypatch.setattr(
        voice.settings, "VOICE_GUARD_SCOPES", "exact,bundle,city"
    )
    with pytest.raises(ValueError, match="general_contractor"):
        voice.create_campaign(
            name="test-gc-cap",
            city="New York",
            trade="",
            max_calls=20,
            quota_total=20,
            trade_plan=[
                {"trade": "general_contractor", "quota": 5},
                {"trade": "remodeling", "quota": 15},
            ],
        )


def test_infer_trade_nao_default_para_general_contractor():
    assert voice._infer_trade("ABC Services LLC") == ""
    assert voice._infer_trade("ABC General Contractors") == "general_contractor"


def test_gc_040_nao_entra_nem_conta_como_verificado():
    voice.import_licenses_csv(
        _csv("ABC Services LLC", "+12125550127", "general_contractor")
    )
    voice.sync_company_trades()
    assert voice.verified_candidate_count("New York", "general_contractor") == 0
    campaign = voice.create_campaign(
        name="test-gc-040",
        city="New York",
        trade="general_contractor",
        max_calls=1,
        quota_total=1,
        trade_plan=[{"trade": "general_contractor", "quota": 1}],
    )
    assert (
        voice.campaign_candidates(
            int(campaign["id"]), "New York", "general_contractor", 10, True
        )
        == []
    )
    with pytest.raises(ValueError, match="niche_gate"):
        voice.validate_campaign_niche(int(campaign["id"]))


def test_trade_primario_sem_company_trades_nao_e_candidato():
    voice.import_licenses_csv(
        _csv("Alpha Electric", "+12125550128", "electrical")
    )
    # Sem sync_company_trades: existe trade primário, mas não há verificação.
    campaign = voice.create_campaign(
        name="test-primary-only",
        city="New York",
        trade="electrical",
        max_calls=1,
        quota_total=1,
        trade_plan=[{"trade": "electrical", "quota": 1}],
    )
    assert (
        voice.campaign_candidates(
            int(campaign["id"]), "New York", "electrical", 10, True
        )
        == []
    )


def test_validate_campaign_niche_exige_quota_verificada():
    voice.import_licenses_csv(_csv("Alpha Electric", "+12125550129", "electrical"))
    voice.import_licenses_csv(_csv("Beta Electric", "+12125550130", "electrical"))
    voice.sync_company_trades()
    assert voice.verified_candidate_count("New York", "electrical") == 2

    too_big = voice.create_campaign(
        name="test-gate-big",
        city="New York",
        trade="electrical",
        max_calls=3,
        quota_total=3,
        trade_plan=[{"trade": "electrical", "quota": 3}],
    )
    with pytest.raises(ValueError, match="quota 3 > verificados 2"):
        voice.validate_campaign_niche(int(too_big["id"]))

    ok = voice.create_campaign(
        name="test-gate-ok",
        city="New York",
        trade="electrical",
        max_calls=2,
        quota_total=2,
        trade_plan=[{"trade": "electrical", "quota": 2}],
    )
    gate = voice.validate_campaign_niche(int(ok["id"]))
    assert gate["ok"] is True
    assert gate["trades"][0]["verified"] == 2


def test_audit_campaign_candidates_all_green():
    from datetime import datetime, timezone

    for phone in ("+12125550131", "+12125550132"):
        voice.import_licenses_csv(_csv("Gamma Electric", phone, "electrical"))
        voice.check_dnc(phone, listed=False, source="pytest")
    voice.sync_company_trades()
    campaign = voice.create_campaign(
        name="audit-green",
        city="New York",
        trade="electrical",
        max_calls=2,
        quota_total=2,
        trade_plan=[{"trade": "electrical", "quota": 2}],
    )
    audit = voice.audit_campaign_candidates(
        int(campaign["id"]),
        at=datetime(2026, 11, 2, 16, 0, tzinfo=timezone.utc),
    )
    assert audit["all_green"] is True
    assert audit["gc_in_plan"] == 0
    assert audit["total_quota"] == 2
    assert audit["total_allowed"] == 2
    assert audit["trades"][0]["green"] is True


def test_infer_trade_word_boundary_casos_reais():
    assert voice._infer_trade("JD DESIGN AND DEVELOPERS LLC") == ""
    assert voice._infer_trade("CLEAR CHANNEL OUTDOOR INC") == ""
    assert voice._infer_trade("CLEANLEAF ENERGY LLC") == ""
    assert voice._infer_trade("MOTOR CONTROLS INC") == ""
    assert voice._infer_trade("ABC SIGNS & WRAPS") == "signage"
    assert voice._infer_trade("ABC DOOR & WINDOW LLC") == "windows"

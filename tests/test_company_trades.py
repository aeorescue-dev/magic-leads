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
        "permit_count,permit_value_usd,years_active,employee_estimate\n"
        f"{company},John Smith,{phone},New York,NY,active,{trade},"
        "4,250000,12,8\n"
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

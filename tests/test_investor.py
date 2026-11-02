"""Investor Room (Fase 30): preço semanal, valuation, proof, NDA e watermark."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.services import investor


def test_preco_semanal_normaliza_52_12():
    a = investor.DEFAULT_ASSUMPTIONS
    assert a["ticket_price_weekly"] == 120
    assert a["monthlyization_factor"] == pytest.approx(52 / 12)
    assert a["normalized_mrr_per_pass"] == pytest.approx(520)
    assert a["arr_per_pass"] == pytest.approx(6240)


def test_simulador_recalcula_receita_e_margem():
    asset = {"floor_low": 150000.0, "floor_high": 400000.0}
    out = investor.simulate(
        {
            "contractors": 10,
            "mailboxes": 2,
            "cities": 4,
            "monthly_churn": 0.08,
            "multiple": 3,
        },
        investor.DEFAULT_ASSUMPTIONS,
        asset,
    )
    assert out["weekly_revenue"] == 1200
    assert out["mrr_normalized"] == 5200
    assert out["arr_normalized"] == 62400
    assert out["valuation"]["base"] == 187200
    assert out["gross_margin_pct"] > 0
    assert out["ev_low"] == 150000  # piso patrimonial domina
    assert out["ev_high"] == 499200


def test_simulador_capacidade_zero_nao_rebenta():
    out = investor.simulate(
        {"contractors": 0},
        investor.DEFAULT_ASSUMPTIONS,
        {"floor_low": 1000, "floor_high": 2000},
    )
    assert out["mrr_normalized"] == 0
    assert out["gross_margin_pct"] == 0
    assert out["ev_low"] == 1000


def test_reconciliacao_nao_inventa_passes_pagos():
    metrics = {
        "users": {"access_active": 3, "pro_active": 10},
        "checkout": {"completed": 0},
        "stripe_events": {"completed": 3},
    }
    rec = investor._reconciliation(
        metrics, {"status": "ok", "cash_30d": 0.0, "cash_total": 360.0, "mode": "live"}
    )
    assert rec["verified_paid_passes"] == 0
    assert rec["access_passes"] == 3
    assert rec["status"] == "cash_without_mapping"


def test_asset_floor_e_proof_usam_metricas_reais():
    metrics = {
        "leads": {
            "total": 1000,
            "owners": 800,
            "addresses": 1000,
            "fresh7": 200,
            "provenance": 1000,
        },
        "searchbug": {
            "success": {"calls": 2, "billed": 2, "cost": 0.4},
            "error": {"calls": 2, "billed": 2, "cost": 0.4},
            "no_results": {"calls": 1, "billed": 0, "cost": 0.0},
        },
        "outbound": {"sent": 10},
        "bounces": {"bounce": 0},
        "replies": 0,
        "suppressions": 0,
        "health": {"overall_status": "ok", "overall_score": 100},
    }
    asset = investor._asset(metrics, investor.DEFAULT_ASSUMPTIONS)
    assert asset["data_low"] == 800 * 0.5
    assert asset["floor_low"] == 800 * 0.5 + 12 * 8000 + 10000
    proof = investor._proof(metrics, investor.DEFAULT_ASSUMPTIONS)
    assert proof["owner_coverage_pct"] == 80.0
    assert proof["phone"]["success_pct"] == 40.0
    assert proof["phone"]["error_billed"] == 2
    assert proof["phone"]["status"] == "em remediação"


@pytest.mark.asyncio
async def test_snapshot_e_export_csv_com_watermark(monkeypatch):
    monkeypatch.setattr(
        investor,
        "_stripe_cash",
        lambda: {"status": "not_configured", "cash_30d": None, "cash_total": None},
    )
    snap = investor.build_snapshot()
    assert snap["version"] == investor.VERSION
    assert snap["price_bridge"]["ticket_weekly"] == 120
    assert snap["asset"]["floor_low"] > 0
    csv_text = investor.export_csv(
        snap, "investor@example.com", "203.0.113.9", "pytest", user_id=99
    )
    assert "viewer_email" in csv_text
    assert "investor@example.com" in csv_text
    assert "IR-" in csv_text
    assert "ticket_weekly" in csv_text


def test_claims_register_tem_fonte_data_e_citacao():
    """Nenhum claim concorrencial pode existir sem URL, data e citação."""
    ids = set()
    for claim in investor.CLAIMS_REGISTER:
        ids.add(claim["id"])
        assert claim["source_url"].startswith("https://")
        assert claim["source_publisher"]
        assert claim["source_date"]
        assert claim["captured_at"] == investor.CLAIMS_CAPTURED_AT
        assert claim["quote"]
        assert claim["status"] in ("verified", "estimate", "pending_legal")
    assert ids
    for row in investor.COMPETITIVE_MATRIX:
        assert row["dimension"]
        assert row["magic"]
        assert row["angi"]
        assert row["edge"] in ("magic", "neutral", "angi")
        assert row["source_ids"]
        assert set(row["source_ids"]) <= ids


def test_snapshot_publica_claims_e_comparativo(monkeypatch):
    monkeypatch.setattr(
        investor,
        "_stripe_cash",
        lambda: {"status": "not_configured", "cash_30d": None, "cash_total": None},
    )
    snap = investor.build_snapshot()
    assert snap["claims_register"]["version"] == investor.CLAIMS_VERSION
    assert len(snap["claims_register"]["items"]) == len(investor.CLAIMS_REGISTER)
    assert len(snap["competitive"]) == len(investor.COMPETITIVE_MATRIX)
    assert any(
        item["source_url"].startswith("https://www.ftc.gov/")
        for item in snap["claims_register"]["items"]
    )


def test_nda_e_idempotente():
    investor.init()
    assert investor.has_nda(12345, investor.NDA_VERSION) is False
    investor.accept_nda(12345, "buyer@example.com", "203.0.113.9", "pytest")
    investor.accept_nda(12345, "buyer@example.com", "203.0.113.9", "pytest")
    assert investor.has_nda(12345, investor.NDA_VERSION) is True


def test_refresh_if_due_e_get_snapshot():
    investor.init()
    snap = investor.get_snapshot()
    assert snap["price_bridge"]["mrr_per_pass"] == pytest.approx(520)
    again = investor.refresh_if_due()
    assert again["status"] in ("ok", "skipped")

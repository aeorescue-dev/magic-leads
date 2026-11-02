"""Auto-scheduler e segmentos cidade+nicho (Fase 2A automação)."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from backend.services import auto_dialer, showcase
from backend.services import b2b_voice as voice
from backend.services.db import get_connection

NOW = datetime(2026, 11, 2, 16, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.setenv("VOICE_NOW_ISO", NOW.isoformat())
    monkeypatch.setattr(showcase.settings, "SHOWCASE_MIN_ITEMS", 3)
    monkeypatch.setattr(showcase.settings, "SHOWCASE_WINDOW_DAYS", 30)
    monkeypatch.setattr(showcase.settings, "EMAIL_API_KEY", "")
    monkeypatch.setattr(showcase.settings, "EMAIL_FROM", "")
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


def _import_company(phone: str, city: str, state: str) -> None:
    csv_text = (
        "company_name,contact_name,phone,email,city,state,license_status,trade,"
        "permit_count\n"
        f"Auto {city} Co,Test,{phone},{phone[1:]}@example.com,{city},{state},"
        "active,Roofing,7\n"
    )
    voice.import_licenses_csv(csv_text, source_name="pytest-auto")
    voice.check_dnc(phone, listed=False, source="pytest")


def test_auto_dialer_dry_run_dispara_chamadas_e_vitrines():
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
    assert final["showcases_sent"] == 2

    conn = voice.get_conn()
    try:
        calls = conn.execute(
            "SELECT * FROM voice_calls WHERE campaign_id=?", (str(campaign["id"]),)
        ).fetchall()
        assert len(calls) == 2
        assert all(row["showcase_link_id"] for row in calls)
        assert all(row["status"] == "showcase_sent" for row in calls)
    finally:
        conn.close()


def test_segments_classificam_dedicada_e_fallback():
    for idx in range(3):
        _seed_lead("Boston", "MA", "Roof", "02118", idx)
    for idx in range(3):
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
    assert boston["showcase_exact"] >= 3
    assert dallas["showcase_mode"] == "city_fallback"
    assert dallas["showcase_exact"] == 0
    assert dallas["showcase_city_total"] >= 3


def test_campanha_interrompida_e_fechada_no_arranque():
    campaign = voice.create_campaign("Auto interrupted", "Boston", "Roofing", 5)
    closed = voice.mark_interrupted_campaigns()
    assert closed >= 1
    final = voice.get_campaign(campaign["id"])
    assert final["status"] == "error"
    assert "interrompida" in (final["error"] or "").lower()

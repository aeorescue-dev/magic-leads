"""Vitrine pública (Fase 2A): inventário, mascaramento, tokens e atribuição."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from backend.services import showcase
from backend.services.db import get_connection

NOW = datetime.now(timezone.utc)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.setenv("SHOWCASE_MIN_ITEMS", "3")
    monkeypatch.setenv("SHOWCASE_WINDOW_DAYS", "30")
    monkeypatch.setattr(showcase.settings, "SHOWCASE_MIN_ITEMS", 3)
    monkeypatch.setattr(showcase.settings, "SHOWCASE_WINDOW_DAYS", 30)
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
                    'Owner Should Not Leak', 0)
            """,
            (
                f"pytest-showcase-{city}-{category}-{idx}",
                f"{100 + idx} {category} Street",
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


def test_build_publica_apenas_combos_com_3_ou_mais():
    for idx in range(3):
        _seed_lead("Boston", "MA", "Roof", "02118", idx)
    for idx in range(2):
        _seed_lead("Boston", "MA", "Paint", "02119", idx)
    for idx in range(4):
        _seed_lead("Chicago", "IL", "Plumbing", "60601", idx)

    result = showcase.build_pages()
    assert result["published"] == 2
    assert result["min_items"] == 3

    boston = showcase.get_page("boston", "roofing")
    assert boston is not None
    assert boston["page"]["count"] == 3
    assert len(boston["items"]) == 3
    assert boston["page"]["fallback"] is None

    chicago = showcase.get_page("chicago", "plumbing")
    assert chicago is not None
    assert chicago["page"]["count"] == 4

    # 2 < 3: não publica; mas cai no fallback da cidade (Boston tem roofing).
    fallback = showcase.get_page("boston", "painting")
    assert fallback is not None
    assert fallback["page"]["fallback"] == "city"


def test_payload_nao_expoe_pii():
    for idx in range(3):
        _seed_lead("Boston", "MA", "Roof", "02118", idx)
    showcase.build_pages()
    payload = showcase.get_page("boston", "roofing")
    assert payload is not None
    blob = json.dumps(payload)
    assert "Owner Should Not Leak" not in blob
    assert "Roof Street" not in blob
    for item in payload["items"]:
        assert "address" not in item
        assert "owner_name" not in item
        assert "owner_phone" not in item


def test_fallback_trade_quando_cidade_nao_tem_inventario():
    for idx in range(3):
        _seed_lead("Boston", "MA", "Roof", "02118", idx)
    showcase.build_pages()
    fallback = showcase.get_page("austin", "roofing")
    assert fallback is not None
    assert fallback["page"]["fallback"] == "trade"
    assert fallback["page"]["city"] == "Boston"


def test_available_para_guiao_de_voz():
    for idx in range(3):
        _seed_lead("Boston", "MA", "Roof", "02118", idx)
    showcase.build_pages()
    ok = showcase.available("boston", "roofing")
    assert ok["available"] is True
    assert ok["exact_count"] == 3
    missing = showcase.available("boston", "hvac")
    assert missing["available"] is False


def test_trade_slug_com_hifen_encontra_pagina_exata():
    for idx in range(3):
        _seed_lead("Boston", "MA", "Debris", "02120", idx)
    showcase.build_pages()
    exact = showcase.get_page("boston", "debris-removal")
    assert exact is not None
    assert exact["page"]["fallback"] is None
    assert exact["page"]["trade_code"] == "debris_removal"
    assert showcase.available("boston", "debris_removal")["available"] is True


def test_cidade_nyc_normaliza_para_new_york():
    for idx in range(3):
        _seed_lead("NYC", "NY", "Roof", "10001", idx)
    showcase.build_pages()
    exact = showcase.get_page("NYC", "roofing")
    assert exact is not None
    assert exact["page"]["fallback"] is None
    assert exact["page"]["city_slug"] == "new-york"
    assert showcase.available("NYC", "roofing")["available"] is True
    link = showcase.create_link(
        company_id=12,
        email="ny@example.com",
        city="NYC",
        trade_code="roofing",
    )
    resolved = showcase.resolve_link(link["token"])
    assert resolved is not None
    assert "/en/new-york/roofing?vt=" in showcase.redirect_url(
        resolved, link["token"]
    )


def test_token_cria_regista_visita_e_redireciona():
    for idx in range(3):
        _seed_lead("Boston", "MA", "Roof", "02118", idx)
    showcase.build_pages()
    link = showcase.create_link(
        company_id=10,
        email="contractor@example.com",
        city="Boston",
        trade_code="roofing",
        company_name="Example Roofing",
        voice_call_id=99,
    )
    assert link["url"].endswith("/r/" + link["token"])
    resolved = showcase.resolve_link(link["token"])
    assert resolved is not None
    assert resolved["city_slug"] == "boston"

    visited = showcase.record_visit(
        link["token"], "/r/token", "https://email", "203.0.113.9", "pytest"
    )
    assert visited is not None
    conn = showcase.get_conn()
    try:
        row = conn.execute(
            "SELECT visit_count FROM showcase_links WHERE id=?", (link["link_id"],)
        ).fetchone()
        assert row["visit_count"] == 1
    finally:
        conn.close()
    assert showcase.redirect_url(resolved, link["token"]).startswith(
        "http"
    )
    assert "/en/boston/roofing?vt=" in showcase.redirect_url(
        resolved, link["token"]
    )


def test_token_expirado_e_rejeitado():
    for idx in range(3):
        _seed_lead("Boston", "MA", "Roof", "02118", idx)
    showcase.build_pages()
    link = showcase.create_link(
        company_id=11,
        email="x@example.com",
        city="Boston",
        trade_code="roofing",
    )
    conn = showcase.get_conn()
    try:
        conn.execute(
            "UPDATE showcase_links SET expires_at=? WHERE id=?",
            ((NOW - timedelta(days=1)).isoformat(), link["link_id"]),
        )
        conn.commit()
    finally:
        conn.close()
    assert showcase.resolve_link(link["token"]) is None


def test_email_sem_canal_e_dry_run(monkeypatch):
    monkeypatch.setattr(showcase.settings, "EMAIL_API_KEY", "")
    monkeypatch.setattr(showcase.settings, "EMAIL_FROM", "")
    result = showcase.send_showcase_email(
        to_email="contractor@example.com",
        company_name="Example Roofing",
        city="Boston",
        trade_code="roofing",
        count=3,
        link_url="https://magicleads.app/r/test",
    )
    assert result["sent"] is False
    assert result.get("dry_run") is True


def test_email_staging_forca_dry_run(monkeypatch):
    monkeypatch.setattr(showcase.settings, "VOICE_STAGING_MODE", True)
    monkeypatch.setattr(showcase.settings, "EMAIL_API_KEY", "re_test")
    monkeypatch.setattr(showcase.settings, "EMAIL_FROM", "Magic Leads <x@example.com>")
    result = showcase.send_showcase_email(
        to_email="contractor@example.com",
        company_name="Example Roofing",
        city="Boston",
        trade_code="roofing",
        count=3,
        link_url="https://magicleads.app/r/test",
    )
    assert result["sent"] is False
    assert result["dry_run"] is True
    assert result["reason"] == "staging_mode"


def test_checkout_grava_atribuicao():
    showcase.record_checkout(
        link_id=1,
        session_id="cs_test_showcase",
        user_id=7,
        email="contractor@example.com",
        amount_cents=12000,
    )
    showcase.mark_checkout_completed("cs_test_showcase")
    stats = showcase.attribution_stats()
    assert stats["checkouts"] == 1
    assert stats["completed"] == 1
    assert stats["revenue_cents"] == 12000

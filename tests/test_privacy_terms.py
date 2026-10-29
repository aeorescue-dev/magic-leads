"""Regra de ouro de IP: nenhum termo da fonte/arquitetura chega ao cliente.

Cobre tres camadas:
1. `privacy.scrub` / `sanitize_lead` (backend);
2. as traducoes do produto (i18n do frontend e `translations.py`);
3. a resposta de API que alimenta dashboard, push e in-app.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from backend.services.privacy import (
    contains_banned,
    neutral_source_type,
    sanitize_lead,
    scrub,
)

ROOT = Path(__file__).resolve().parents[1]

BANNED_SAMPLES = [
    "311",
    "Socrata",
    "CKAN",
    "DOB",
    "HPD",
    "scraper",
    "dataset",
    "Open Data",
    "API",
    "BBL",
    "BIN",
]


# ---------------------------------------------------------------------------
# scrub
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("term", BANNED_SAMPLES)
def test_scrub_removes_each_banned_term(term):
    assert not contains_banned(scrub(f"Ocorrência via {term} no imóvel"))


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Water/Wastewater Line Locate - 311", "Water/Wastewater Line Locate"),
        ("DOB SUMMONS ISSUED FOR STRUCTURE", "SUMMONS ISSUED FOR STRUCTURE"),
        ("FAILURE TO FILE ANNUAL BOILER REPORT", "FAILURE TO FILE ANNUAL BOILER REPORT"),
        ("https://data.cityofnewyork.us/resource/3h2n-5cm9", None),
        ("", None),
        (None, None),
    ],
)
def test_scrub_preserves_meaning(raw, expected):
    assert scrub(raw) == expected


def test_scrub_does_not_break_words_containing_short_tokens():
    # `API` dentro de CAPITAL e `311` dentro de 3110 nao podem ser tocados.
    assert scrub("CAPITAL IMPROVEMENT 3110") == "CAPITAL IMPROVEMENT 3110"


# ---------------------------------------------------------------------------
# sanitize_lead
# ---------------------------------------------------------------------------

def test_sanitize_lead_hides_source_and_department():
    lead = {
        "id": 1,
        "source": "data.cityofnewyork.us/3h2n-5cm9",
        "department": "DOB - Buildings",
        "source_type": "dob_violation",
        "case_title": "DOB SUMMONS ISSUED",
        "descriptor": "Water Line Locate - 311",
        "issue_description": "Report filed via 311 about Socrata export",
        "neighborhood": "BROOKLYN",
    }
    safe = sanitize_lead(lead)
    assert safe["source"] is None
    assert safe["department"] is None
    assert safe["source_type"] == "building_notice"
    assert safe["case_title"] == "SUMMONS ISSUED"
    assert safe["descriptor"] == "Water Line Locate"
    assert safe["neighborhood"] == "BROOKLYN"  # geografia real permanece
    for key in ("case_title", "descriptor", "issue_description"):
        assert not contains_banned(safe[key]), key


def test_neutral_source_types():
    assert neutral_source_type("311") == "service_request"
    assert neutral_source_type("hpd_violation") == "housing_notice"
    assert neutral_source_type("permit") == "permit"
    assert neutral_source_type("qualquer_coisa") == "record"
    assert neutral_source_type(None) is None


# ---------------------------------------------------------------------------
# Resposta de API (o que chega ao dashboard)
# ---------------------------------------------------------------------------

def test_lead_response_is_clean():
    from backend.main import _to_lead_response

    lead = {
        "id": 7,
        "external_id": "DOB-311-1",
        "source_type": "dob_violation",
        "signal_type": "open_request",
        "signal_status": "open",
        "address": "1 MAIN ST",
        "city": "NYC",
        "issue_category": "Roof",
        "issue_description": "DOB violation exported from Socrata via 311",
        "owner_name": None,
        "owner_phone": None,
        "date_reported": "2026-10-01T00:00:00",
        "urgency_level": "high",
        "image_url": None,
        "status": "new",
        "case_title": "HPD VIOLATION - 311",
        "descriptor": "API dataset scraper",
        "department": "DOB",
        "source": "data.cityofnewyork.us/3h2n-5cm9",
        "closure_reason": "CKAN Open Data sync",
        "resolution_description": "BBL 3012340050",
        "neighborhood": "BROOKLYN",
    }
    out = _to_lead_response(lead).model_dump()

    assert out["source"] is None
    assert out["department"] is None
    assert out["source_type"] == "building_notice"
    for key, value in out.items():
        if isinstance(value, str):
            assert not contains_banned(value), f"{key} vazou: {value!r}"


# ---------------------------------------------------------------------------
# Traducoes do produto
# ---------------------------------------------------------------------------

def _i18n_values() -> list[tuple[str, str]]:
    text = (ROOT / "frontend" / "lib" / "i18n.tsx").read_text(encoding="utf-8")
    pattern = re.compile(r'"([^"\n]+)"\s*:\s*"((?:[^"\\]|\\.)*)"')
    return [(m.group(1), m.group(2)) for m in pattern.finditer(text)]


def test_frontend_i18n_has_no_banned_terms():
    leaks = [(k, v) for k, v in _i18n_values() if contains_banned(v)]
    assert leaks == [], f"Termos internos na UI: {leaks[:5]}"


def test_backend_translations_have_no_banned_terms():
    from backend.services.translations import TRANSLATIONS

    leaks = []
    for group, locales in TRANSLATIONS.items():
        if not isinstance(locales, dict):
            continue
        for locale, table in locales.items():
            if not isinstance(table, dict):
                continue
            for key, value in table.items():
                if isinstance(value, str) and contains_banned(value):
                    leaks.append((group, locale, key, value[:60]))
    assert leaks == [], f"Termos internos nas traducoes: {leaks[:5]}"


def test_quiet_hours_copy_matches_product_language():
    values = dict(_i18n_values())
    pt = values["dashboard.settings.quiet_body"]
    en = values["dashboard.settings.quiet_body"]
    # A chave repete-se por locale; recolhe todas as variantes.
    all_quiet = [v for k, v in _i18n_values() if k == "dashboard.settings.quiet_body"]
    assert len(all_quiet) == 3
    for text in all_quiet:
        assert "311" not in text
        assert "oportunidades" in text.lower() or "opportunities" in text.lower()
    assert pt and en  # sanity


# ---------------------------------------------------------------------------
# Sino (in-app) — inclui notificacoes antigas ja gravadas
# ---------------------------------------------------------------------------

def test_notifications_are_scrubbed_on_read():
    import uuid
    from datetime import datetime, timedelta, timezone

    from fastapi.testclient import TestClient

    from backend.main import _get_current_user, app
    from backend.services.db import db_service, get_connection

    conn = get_connection()
    try:
        conn.execute("DELETE FROM notifications")
        conn.execute("DELETE FROM users")
        cur = conn.execute(
            "INSERT INTO users (email, password_hash, company_name, plan, "
            "subscription_status, plan_until, locale) VALUES (?, 'x', 'IP Co', 'pro', "
            "'active', ?, 'pt')",
            (
                f"privacy_{uuid.uuid4().hex[:8]}@test.com",
                (datetime.now(timezone.utc) + timedelta(days=5)).isoformat(),
            ),
        )
        uid = int(cur.lastrowid)
        conn.commit()
    finally:
        conn.close()

    db_service._service.add_notification_for_user(
        uid, "new_lead", "Novos leads capturados",
        "1692 novo(s) lead(s) 311 adicionado(s) via Socrata",
    )

    client = TestClient(app)
    app.dependency_overrides[_get_current_user] = lambda: {"id": uid, "email": "x@y.z"}
    try:
        r = client.get("/api/notifications?filter=all")
        assert r.status_code == 200
        items = r.json()
        assert len(items) == 1
        assert "311" not in items[0]["message"]
        assert "Socrata" not in items[0]["message"]
        assert not contains_banned(items[0]["message"])
        assert not contains_banned(items[0]["title"])
    finally:
        app.dependency_overrides.clear()


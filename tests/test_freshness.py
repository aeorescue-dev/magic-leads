"""P1: frescura HPD/DOB + consolidacao da reincidencia + phone_confidence."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from backend.services import freshness
from backend.services.db import db_service, get_connection
from backend.services.lead_rules import phone_confidence

CITY = "P1"


@pytest.fixture(autouse=True)
def _clean():
    conn = get_connection()
    try:
        conn.execute("DELETE FROM leads WHERE city = ?", (CITY,))
        conn.execute("DELETE FROM freshness_runs")
        conn.commit()
    finally:
        conn.close()
    yield
    conn = get_connection()
    try:
        conn.execute("DELETE FROM leads WHERE city = ?", (CITY,))
        conn.execute("DELETE FROM freshness_runs")
        conn.commit()
    finally:
        conn.close()


def _lead(ext, source, signal_type, signal_status, *, status="available", case_status=None):
    conn = get_connection()
    try:
        cur = conn.execute(
            """INSERT INTO leads
               (external_id, source_type, address, city, state, issue_category,
                case_status, date_reported, signal_type, signal_status,
                issue_description, lead_status)
               VALUES (?, ?, ?, ?, 'NY', 'Roof', ?, datetime('now','-2 days'),
                       ?, ?, 'roof leak', ?)""",
            (ext, source, f"{abs(hash(ext)) % 9000 + 100} P1 STREET", CITY,
             case_status, signal_type, signal_status, status),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def _row(lead_id):
    conn = get_connection()
    try:
        return dict(conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone())
    finally:
        conn.close()


async def _fake_fetch(self, *, dataset, **_kwargs):
    if dataset == "wvxf-dwi5":
        return [
            {"violationid": "H1", "violationstatus": "Close",
             "currentstatus": "VIOLATION CLOSED"},
            {"violationid": "H2", "violationstatus": "Open",
             "currentstatus": "VIOLATION OPEN"},
        ]
    if dataset == "3h2n-5cm9":
        return [
            {"violation_number": "D1", "disposition_date": "2026-10-01",
             "disposition_comments": "Dismissed"},
        ]
    return []


@pytest.mark.asyncio
async def test_freshness_closes_hpd_dob_and_keeps_others(monkeypatch):
    h1 = _lead("H1", "hpd_violation", "legal_obligation", "unknown")
    h2 = _lead("H2", "hpd_violation", "legal_obligation", "unknown")
    d1 = _lead("D1", "dob_violation", "legal_obligation", "unknown")
    s1 = _lead("S1", "311", "open_request", "open")
    hc = _lead("HC", "hpd_violation", "legal_obligation", "unknown", status="converted")

    # historico recente do H2 para a consolidacao da reincidencia
    db_service._service.append_case_occurrences([
        {
            "lead_id": h2,
            "external_id": "H2-OCC-1",
            "issue_category": "Roof",
            "case_status": "Open",
            "opened_at": (datetime.now() - timedelta(days=10)).isoformat(),
        },
        {
            "lead_id": h2,
            "external_id": "H2-OCC-OLD",
            "issue_category": "Roof",
            "case_status": "Open",
            "opened_at": (datetime.now() - timedelta(days=400)).isoformat(),
        },
    ])

    monkeypatch.setattr(
        freshness.socrata_scraper,
        "_fetch_soql",
        _fake_fetch.__get__(freshness.socrata_scraper),
    )

    result = await freshness.run_freshness()

    assert result["hpd_checked"] == 2
    assert result["hpd_closed"] == 1
    assert result["dob_checked"] == 1
    assert result["dob_closed"] == 1
    assert result["status"] == "ok"

    assert _row(h1)["signal_status"] == "closed"
    assert _row(h2)["signal_status"] == "open"
    assert _row(d1)["signal_status"] == "closed"
    assert _row(s1)["signal_status"] == "open"
    assert _row(hc)["signal_status"] == "unknown"

    conn = get_connection()
    try:
        runs = conn.execute("SELECT COUNT(*) FROM freshness_runs").fetchone()[0]
        hist = dict(conn.execute(
            "SELECT * FROM lead_history WHERE lead_id = ?", (h2,)
        ).fetchone())
    finally:
        conn.close()
    assert runs == 1
    assert hist["repeat_365"] == 1
    assert hist["open_cases"] == 2
    assert hist["oldest_open_days"] >= 400


def test_phone_confidence_levels():
    base = {"address": "123 Main Street", "zip_code": "11201"}
    assert phone_confidence({**base, "owner_phone": "+17185550100",
                             "phone_verified": 1, "owner_name": "JOHN SMITH"}) == "verified"
    assert phone_confidence({**base, "owner_name": "JOHN SMITH"}) == "high"
    assert phone_confidence({**base, "owner_name": "ACME HOLDINGS LLC"}) == "medium"
    assert phone_confidence({**base, "owner_name": "NYC HOUSING AUTHORITY"}) == "none"
    assert phone_confidence({**base}) == "none"

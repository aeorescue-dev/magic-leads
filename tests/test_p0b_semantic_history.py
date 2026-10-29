"""P0-B: classificacao semantica, feed SQL e historico/reincidencia."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from backend.services.db import _migrate_schema, db_service, get_connection
from backend.services.lead_rules import (
    derive_signal,
    normalize_case_status,
)

CITY = "P0B"


@pytest.fixture(autouse=True)
def _clean():
    conn = get_connection()
    try:
        conn.execute("DELETE FROM leads WHERE city = ?", (CITY,))
        conn.commit()
    finally:
        conn.close()
    yield
    conn = get_connection()
    try:
        conn.execute("DELETE FROM leads WHERE city = ?", (CITY,))
        conn.commit()
    finally:
        conn.close()


def _insert(
    ext: str,
    source: str,
    signal_type: str | None,
    signal_status: str | None,
    *,
    address: str | None = None,
    category: str = "Roof",
    case_status: str = "Open",
    days_ago: int = 1,
    lead_status: str = "available",
) -> int:
    conn = get_connection()
    try:
        reported = (datetime.now() - timedelta(days=days_ago)).isoformat()
        cur = conn.execute(
            """INSERT INTO leads
               (external_id, source_type, address, city, state, issue_category,
                case_status, date_reported, signal_type, signal_status,
                issue_description, lead_status)
               VALUES (?, ?, ?, ?, 'NY', ?, ?, ?, ?, ?, 'roof leak', ?)""",
            (
                ext, source, address or f"{abs(hash(ext)) % 9000 + 100} P0B STREET",
                CITY, category, case_status, reported, signal_type, signal_status,
                lead_status,
            ),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def test_derive_signal_rules():
    assert derive_signal("311", "Open") == ("open_request", "open")
    assert derive_signal("311", "Closed") == ("open_request", "closed")
    assert derive_signal("permit", "Permit Issued") == ("authorized_work", "open")
    assert derive_signal("hpd_violation", None) == ("legal_obligation", "unknown")
    assert derive_signal("dob_violation", "Open") == ("legal_obligation", "open")
    assert derive_signal("import_b2b", "open") == (None, "unknown")


def test_normalize_case_status_variants():
    assert normalize_case_status("Closed (Duplicate)") == "closed"
    assert normalize_case_status("In Progress") == "open"
    assert normalize_case_status("Violation Open") == "open"
    assert normalize_case_status("") == "unknown"


def test_backfill_classifies_existing_rows():
    _insert("bf-311-open", "311", None, None, case_status="Open")
    _insert("bf-311-closed", "311", None, None, case_status="Closed")
    _insert("bf-permit", "permit", None, None, case_status="Permit Issued")
    _insert("bf-hpd", "hpd_violation", None, None, case_status=None)
    _insert("bf-b2b", "import_b2b", None, None, case_status="open")

    conn = get_connection()
    try:
        _migrate_schema(conn)
        conn.commit()
        rows = {
            r["external_id"]: (r["signal_type"], r["signal_status"])
            for r in conn.execute(
                "SELECT external_id, signal_type, signal_status FROM leads WHERE city = ?",
                (CITY,),
            )
        }
    finally:
        conn.close()

    assert rows["bf-311-open"] == ("open_request", "open")
    assert rows["bf-311-closed"] == ("open_request", "closed")
    assert rows["bf-permit"] == ("authorized_work", "open")
    assert rows["bf-hpd"] == ("legal_obligation", "unknown")
    assert rows["bf-b2b"] == (None, "unknown")


def test_feed_filters_by_signal_and_excludes_closed():
    _insert("f-legal-open", "hpd_violation", "legal_obligation", "open")
    _insert("f-legal-closed", "hpd_violation", "legal_obligation", "closed")
    _insert("f-311", "311", "open_request", "open")
    _insert("f-permit", "permit", "authorized_work", "open")
    _insert("f-reserved", "311", "open_request", "open", lead_status="reserved")

    rows, total = db_service._service.get_leads_feed(city=CITY)
    assert total == 3
    assert {r["external_id"] for r in rows} == {"f-legal-open", "f-311", "f-permit"}

    legal, legal_total = db_service._service.get_leads_feed(
        city=CITY, signal_type="legal_obligation"
    )
    assert legal_total == 1
    assert legal[0]["external_id"] == "f-legal-open"

    closed, closed_total = db_service._service.get_leads_feed(
        city=CITY, include_closed=True
    )
    assert closed_total == 4
    assert any(r["external_id"] == "f-legal-closed" for r in closed)


def test_feed_total_matches_pagination():
    for i in range(5):
        _insert(f"page-{i}", "permit", "authorized_work", "open")

    page1, total = db_service._service.get_leads_feed(city=CITY, limit=2, offset=0)
    page2, total2 = db_service._service.get_leads_feed(city=CITY, limit=2, offset=2)

    assert total == total2 == 5
    assert len(page1) == len(page2) == 2
    assert {r["id"] for r in page1}.isdisjoint({r["id"] for r in page2})


def test_history_recurrence_and_feed_join():
    lead_id = _insert("hist-1", "311", "open_request", "open", days_ago=5)
    now = datetime.now()

    def occ(ext, days, status):
        return {
            "lead_id": lead_id,
            "external_id": ext,
            "issue_category": "Roof",
            "case_status": status,
            "opened_at": (now - timedelta(days=days)).isoformat(),
        }

    db_service._service.append_case_occurrences([
        occ("o1", 10, "Open"),
        occ("o2", 40, "Open"),
        occ("o3", 400, "Closed"),
    ])
    # duplicado: UNIQUE(lead_id, external_id) ignora
    db_service._service.append_case_occurrences([occ("o1", 10, "Open")])
    db_service._service.refresh_lead_history([lead_id])

    conn = get_connection()
    try:
        hist = dict(conn.execute(
            "SELECT * FROM lead_history WHERE lead_id = ?", (lead_id,)
        ).fetchone())
        count = conn.execute(
            "SELECT COUNT(*) FROM lead_case_history WHERE lead_id = ?", (lead_id,)
        ).fetchone()[0]
    finally:
        conn.close()

    assert count == 3
    assert hist["repeat_365"] == 2
    assert hist["open_cases"] == 2
    assert hist["oldest_open_days"] == 40
    assert hist["last_case_at"] is not None

    rows, total = db_service._service.get_leads_feed(city=CITY)
    assert total == 1
    assert rows[0]["repeat_365"] == 2
    assert rows[0]["open_cases"] == 2

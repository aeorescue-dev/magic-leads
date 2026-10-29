"""P1 produto: reparacao de stage_expires_at, cidade case-insensitive e merge."""
from __future__ import annotations

import pytest

from backend.services.db import db_service, get_connection, init_db

CITY = "P1C"


def _clean():
    conn = get_connection()
    try:
        conn.execute("DELETE FROM leads WHERE city IN (?, ?, ?)", (CITY, "CHICAGO", "Chicago"))
        conn.commit()
    finally:
        conn.close()


@pytest.fixture(autouse=True)
def _isolated():
    _clean()
    yield
    _clean()


def _insert(address: str, city: str, *, lead_status: str = "available",
            stage_expires_at=None) -> int:
    conn = get_connection()
    try:
        cur = conn.execute(
            """INSERT INTO leads
               (external_id, source_type, address, city, state, zip_code,
                issue_category, issue_description, signal_type, signal_status,
                date_reported, lead_status, stage_expires_at, reserved_until)
               VALUES (?, '311', ?, ?, 'NY', '11201', 'Roof', 'roof leak',
                       'open_request', 'open', datetime('now'), ?, ?,
                       datetime('now', '+1 hour'))""",
            (f"p1c:{address}", address, city, lead_status, stage_expires_at),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def _row(lead_id: int) -> dict:
    conn = get_connection()
    try:
        return dict(conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone())
    finally:
        conn.close()


def test_backfill_stage_expires_at_for_orphan_stage():
    reserved = _insert("100 P1C STREET", CITY, lead_status="reserved")
    contacted = _insert("200 P1C STREET", CITY, lead_status="contacted")
    negotiating = _insert("300 P1C STREET", CITY, lead_status="in_negotiation")

    init_db()  # corre _migrate_schema, que repara as linhas sem prazo

    for lead_id in (reserved, contacted, negotiating):
        assert _row(lead_id)["stage_expires_at"], f"lead {lead_id} continua sem prazo"

    # Em negociacao, o prazo minimo e' 24h no futuro (nao desaparece no sweep).
    conn = get_connection()
    try:
        future = conn.execute(
            "SELECT COUNT(*) FROM leads WHERE id = ? "
            "AND stage_expires_at >= datetime('now', '+23 hours')",
            (negotiating,),
        ).fetchone()[0]
    finally:
        conn.close()
    assert future == 1


def test_feed_city_filter_is_case_insensitive():
    lead_id = _insert("400 P1C STREET", "CHICAGO")

    rows, total = db_service._service.get_leads_feed(city="Chicago", limit=50)
    assert total >= 1
    assert any(int(r["id"]) == lead_id for r in rows)


def test_city_counts_merge_case_variants():
    _insert("500 P1C STREET", "CHICAGO")
    _insert("600 P1C STREET", "Chicago")

    cities = {
        c["city"]: c["count"]
        for c in db_service._service.get_cities_with_counts_filtered()
    }
    lowered = {k.lower(): v for k, v in cities.items()}
    assert lowered.get("chicago", 0) >= 2
    # Uma unica entrada para a cidade, nao uma por grafia.
    assert sum(1 for k in cities if k.lower() == "chicago") == 1


def test_l3_unnamed_consumes_attempt_budget_but_not_quota():
    from backend.services.lead_rules import will_call_provider

    unnamed = {"address": "123 Main Street", "owner_name": None}
    named = {"address": "123 Main Street", "owner_name": "JOHN SMITH"}

    # L3 desligado: nao se chama o provider para um lead sem nome.
    assert will_call_provider(unnamed, l3_unnamed_enabled=False) is False
    # L3 ligado: chama (logo gasta tentativa), mas a entrega fica incompleta
    # (sem nome) -> nao consome cota.
    assert will_call_provider(unnamed, l3_unnamed_enabled=True) is True
    assert will_call_provider(named, l3_unnamed_enabled=True) is True

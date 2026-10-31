"""Fase E — normalização de cidades e índices de consulta.

A base tem linhas com casing misto (`CHICAGO`/`Chicago`). A métrica pública
deduplica pela forma canónica para não anunciar 5 cidades quando serve 4.
"""

from __future__ import annotations

from backend.services.db import (
    canonical_served_cities,
    get_connection,
    init_db,
)

init_db()


def test_canonical_cities_collapses_casing_and_drops_unsupported():
    raw = ["CHICAGO", "Chicago", "chicago", "NYC", "DALLAS", "BOSTON", "NORFOLK"]
    assert canonical_served_cities(raw) == ["Boston", "Chicago", "Dallas", "NYC"]


def test_canonical_cities_handles_empty_values():
    assert canonical_served_cities([]) == []
    assert canonical_served_cities([None, "", "  "]) == []


def test_lead_reveals_indexes_exist():
    conn = get_connection()
    try:
        names = {
            r["name"] for r in conn.execute("PRAGMA index_list('lead_reveals')").fetchall()
        }
    finally:
        conn.close()
    for expected in (
        "idx_lead_reveals_user",
        "idx_lead_reveals_lead",
        "idx_lead_reveals_date",
        "idx_lead_reveals_refund",
    ):
        assert expected in names, f"índice em falta: {expected}"


def test_notifications_composite_index_exists():
    conn = get_connection()
    try:
        names = {
            r["name"] for r in conn.execute("PRAGMA index_list('notifications')").fetchall()
        }
    finally:
        conn.close()
    assert "idx_notifications_user_read" in names

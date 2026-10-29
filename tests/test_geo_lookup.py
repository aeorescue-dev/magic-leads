"""B3: BBL -> PLUTO (coordenadas gratuitas) e backfill idempotente."""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

import pytest

from backend.services import geo_lookup
from backend.services.db import db_service, get_connection


def _run(coro):
    return asyncio.run(coro)


def _reset():
    conn = get_connection()
    try:
        for table in ("leads", "bbl_coords"):
            conn.execute(f"DELETE FROM {table}")
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# compose_bbl
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "boro,block,lot,expected",
    [
        ("3", "01234", "0050", "3012340050"),
        ("1", "1", "1", "1000010001"),
        ("B", "00042", "7", "3000420007"),   # boro alfabetico (Brooklyn)
        ("Q", " 123 ", " 45 ", "4001230045"),  # espacos
        ("4", "00012", "0000", "4000120000"),  # lot presente mas zero
    ],
)
def test_compose_bbl(boro, block, lot, expected):
    assert geo_lookup.compose_bbl(boro, block, lot) == expected


def test_compose_bbl_rejects_invalid():
    assert geo_lookup.compose_bbl(None, "1", "1") is None
    assert geo_lookup.compose_bbl("9", "1", "1") is None
    assert geo_lookup.compose_bbl("3", "", "1") is None
    assert geo_lookup.compose_bbl("3", "1", "") is None
    assert geo_lookup.compose_bbl("3", "ABC", "1") is None


# ---------------------------------------------------------------------------
# resolve_bbl_coords
# ---------------------------------------------------------------------------

def _fetch_stub(mapping, calls):
    async def fake(bbls):
        calls.append(list(bbls))
        return {b: mapping[b] for b in bbls if b in mapping}

    return fake


def test_cache_hit_does_not_touch_network(monkeypatch):
    _reset()
    db_service._service.upsert_bbl_coords(
        [{"bbl": "3012340050", "lat": 40.7, "lng": -73.9, "source": "pluto"}]
    )
    calls = []

    async def boom(bbls):
        calls.append(bbls)
        raise AssertionError("nao devia consultar o PLUTO")

    monkeypatch.setattr(geo_lookup, "_fetch_from_pluto", boom)

    coords = _run(geo_lookup.resolve_bbl_coords(["3012340050"]))
    assert coords == {"3012340050": (40.7, -73.9)}
    assert calls == []


def test_missing_bbl_is_fetched_and_cached(monkeypatch):
    _reset()
    calls = []
    monkeypatch.setattr(
        geo_lookup, "_fetch_from_pluto", _fetch_stub({"3012340050": (40.71, -73.91)}, calls)
    )

    coords = _run(geo_lookup.resolve_bbl_coords(["3012340050", "9999999999"]))
    assert coords == {"3012340050": (40.71, -73.91)}
    assert len(calls) == 1

    # Segunda chamada: o hit veio da BD, o miss ficou em cache (nao repete).
    calls.clear()
    coords2 = _run(geo_lookup.resolve_bbl_coords(["3012340050", "9999999999"]))
    assert coords2 == {"3012340050": (40.71, -73.91)}
    assert calls == []


def test_stale_miss_is_retried(monkeypatch):
    _reset()
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO bbl_coords (bbl, lat, lng, source, updated_at) "
            "VALUES ('3012340050', NULL, NULL, 'pluto_miss', datetime('now','-40 days'))"
        )
        conn.commit()
    finally:
        conn.close()

    calls = []
    monkeypatch.setattr(
        geo_lookup, "_fetch_from_pluto", _fetch_stub({"3012340050": (40.5, -73.5)}, calls)
    )

    coords = _run(geo_lookup.resolve_bbl_coords(["3012340050"]))
    assert coords == {"3012340050": (40.5, -73.5)}
    assert len(calls) == 1


def test_fresh_miss_is_not_retried(monkeypatch):
    _reset()
    db_service._service.upsert_bbl_coords(
        [{"bbl": "3012340050", "lat": None, "lng": None, "source": "pluto_miss"}]
    )
    calls = []
    monkeypatch.setattr(geo_lookup, "_fetch_from_pluto", _fetch_stub({}, calls))

    assert _run(geo_lookup.resolve_bbl_coords(["3012340050"])) == {}
    assert calls == []


def test_network_can_be_disabled(monkeypatch):
    _reset()
    calls = []
    monkeypatch.setattr(geo_lookup, "_fetch_from_pluto", _fetch_stub({}, calls))
    assert _run(geo_lookup.resolve_bbl_coords(["3012340050"], allow_network=False)) == {}
    assert calls == []


def test_pluto_bbl_is_normalized(monkeypatch):
    """O PLUTO devolve `3074130059.00000000`; a chave tem de casar."""
    _reset()
    assert geo_lookup._normalize_bbl("3074130059.00000000") == "3074130059"
    assert geo_lookup._normalize_bbl(" 3012340050 ") == "3012340050"

    from backend.scrapers.socrata_311 import socrata_scraper

    async def fake_pages(**kwargs):
        return [
            {"bbl": "3074130059.00000000", "latitude": "40.5901865", "longitude": "-73.9584284"},
            {"bbl": "3076800063.00000000", "latitude": "0", "longitude": "0"},
            {"bbl": "3088060150.00000000", "latitude": "999", "longitude": "-73.9"},
            {"bbl": "3099999999.00000000", "latitude": "n/a", "longitude": "-73.9"},
        ]

    monkeypatch.setattr(socrata_scraper, "_fetch_all_pages", fake_pages)

    coords = _run(geo_lookup.resolve_bbl_coords(["3074130059", "3076800063", "3088060150", "3099999999"]))
    assert coords == {"3074130059": (40.5901865, -73.9584284)}


# ---------------------------------------------------------------------------
# Backfill
# ---------------------------------------------------------------------------

def _lead(bbl: str | None, *, lat=None, lng=None, source_type="dob_violation") -> int:
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO leads (external_id, source_type, address, city, state, "
            "issue_category, date_reported, case_status, bbl, lat, lng) "
            "VALUES (?, ?, ?, 'NYC', 'NY', 'Roof', ?, 'Open', ?, ?, ?)",
            (
                f"geo-{uuid.uuid4().hex[:10]}",
                source_type,
                f"{uuid.uuid4().hex[:6]} GEO STREET",
                datetime.now(timezone.utc).isoformat(),
                bbl,
                lat,
                lng,
            ),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def _coords(lead_id: int):
    conn = get_connection()
    try:
        r = conn.execute(
            "SELECT lat, lng FROM leads WHERE id = ?", (lead_id,)
        ).fetchone()
        return (r["lat"], r["lng"])
    finally:
        conn.close()


def test_backfill_sets_coordinates_and_is_idempotent(monkeypatch):
    _reset()
    a = _lead("3012340050")
    b = _lead("3012340051")
    c = _lead(None)  # sem BBL: nao e' candidato
    d = _lead("3012340050", lat=40.0, lng=-73.0)  # ja tem coords

    calls = []
    monkeypatch.setattr(
        geo_lookup,
        "_fetch_from_pluto",
        _fetch_stub(
            {"3012340050": (40.71, -73.91), "3012340051": (40.72, -73.92)}, calls
        ),
    )

    result = _run(geo_lookup.backfill_missing_coords(batch=500, max_batches=5))
    assert result["candidates"] == 2
    assert result["resolved"] == 2
    assert _coords(a) == (40.71, -73.91)
    assert _coords(b) == (40.72, -73.92)
    assert _coords(c) == (None, None)
    assert _coords(d) == (40.0, -73.0)  # nunca sobrepoe

    # Correr de novo: nada a fazer.
    calls.clear()
    again = _run(geo_lookup.backfill_missing_coords(batch=500, max_batches=5))
    assert again["candidates"] == 0
    assert again["resolved"] == 0
    assert calls == []


def test_backfill_skips_leads_without_bbl(monkeypatch):
    _reset()
    _lead(None)
    calls = []
    monkeypatch.setattr(geo_lookup, "_fetch_from_pluto", _fetch_stub({}, calls))

    result = _run(geo_lookup.backfill_missing_coords(batch=100, max_batches=3))
    assert result == {"candidates": 0, "resolved": 0, "missing": 0}
    assert calls == []


def test_count_missing_coords():
    _reset()
    _lead("3012340050")
    _lead(None)
    _lead("3012340051", lat=40.0, lng=-73.0)

    stats = db_service._service.count_leads_missing_coords()
    assert stats["total"] == 3
    assert stats["missing"] == 2
    assert stats["missing_with_bbl"] == 1


def test_backfill_dob_bbl_from_source(monkeypatch):
    """Leads antigos (bbl NULL) recuperam o BBL pelo violation_number."""
    _reset()
    a = _lead(None)
    b = _lead(None)
    keep = _lead("3012340050")

    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, external_id FROM leads WHERE id IN (?, ?) ORDER BY id", (a, b)
        ).fetchall()
    finally:
        conn.close()
    ext_a, ext_b = rows[0]["external_id"], rows[1]["external_id"]

    from backend.scrapers.socrata_311 import socrata_scraper

    async def fake_pages(**kwargs):
        return [
            {"violation_number": ext_a, "ecb_number": None, "boro": "3", "block": "01234", "lot": "0050"},
            {"violation_number": ext_b, "ecb_number": None, "boro": "Q", "block": "42", "lot": "7"},
        ]

    monkeypatch.setattr(socrata_scraper, "_fetch_all_pages", fake_pages)

    result = _run(geo_lookup.backfill_dob_bbl_from_source(batch=150, max_batches=3))
    assert result["candidates"] == 2
    assert result["bbl_filled"] == 2

    conn = get_connection()
    try:
        got = {
            r["id"]: r["bbl"]
            for r in conn.execute(
                "SELECT id, bbl FROM leads WHERE id IN (?, ?, ?)", (a, b, keep)
            )
        }
    finally:
        conn.close()
    assert got[a] == "3012340050"
    assert got[b] == "4000420007"
    assert got[keep] == "3012340050"  # nao foi tocado

    # Segunda passagem: ja nao ha candidatos.
    again = _run(geo_lookup.backfill_dob_bbl_from_source(batch=150, max_batches=3))
    assert again["candidates"] == 0


def test_backfill_dob_bbl_ignores_unresolvable(monkeypatch):
    _reset()
    lead = _lead(None)

    from backend.scrapers.socrata_311 import socrata_scraper

    async def fake_pages(**kwargs):
        return [{"violation_number": "x", "ecb_number": None, "boro": "", "block": "", "lot": ""}]

    monkeypatch.setattr(socrata_scraper, "_fetch_all_pages", fake_pages)

    result = _run(geo_lookup.backfill_dob_bbl_from_source(batch=150, max_batches=3))
    assert result["bbl_filled"] == 0

    conn = get_connection()
    try:
        bbl = conn.execute("SELECT bbl FROM leads WHERE id = ?", (lead,)).fetchone()["bbl"]
    finally:
        conn.close()
    assert bbl is None


def test_dob_scraper_selects_bbl_columns():
    """O select de DOB Violations tem de pedir boro/block/lot (fonte do BBL)."""
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "backend" / "main.py"
    text = src.read_text(encoding="utf-8")
    assert "boro, block, lot, bin" in text
    assert "compose_bbl" in text

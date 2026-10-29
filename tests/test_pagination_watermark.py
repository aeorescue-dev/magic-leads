"""P0-A: paginacao `$offset`, watermark e indice do feed."""
from __future__ import annotations

import pytest

from backend.scrapers.socrata_311 import socrata_scraper
from backend.services.db import db_service, get_connection


def _row(n: int):
    return {
        "unique_key": f"p0-{n}",
        "created_date": "2026-10-29T10:00:00.000",
        "complaint_type": "Plumbing",
        "incident_address": f"{100 + n} MAIN STREET",
        "status": "Open",
    }


@pytest.mark.asyncio
async def test_fetch_soql_sends_offset(monkeypatch):
    captured = {}

    class _Resp:
        status_code = 200
        text = "[]"

        def raise_for_status(self):
            return None

        def json(self):
            return []

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, params=None, headers=None):
            captured.update(params or {})
            return _Resp()

    import backend.scrapers.socrata_311 as mod
    monkeypatch.setattr(mod.httpx, "AsyncClient", lambda *a, **k: _Client())

    await socrata_scraper._fetch_soql(
        domain="data.cityofnewyork.us", dataset="erm2-nwe9",
        select="unique_key", where="created_date > '2026-10-01'",
        limit=5000, order="created_date DESC", offset=10000,
    )

    assert captured["$offset"] == 10000
    assert captured["$limit"] == 5000


@pytest.mark.asyncio
async def test_fetch_all_pages_stops_on_short_page(monkeypatch):
    calls = []

    async def fake(self, **kwargs):
        calls.append(kwargs["offset"])
        if kwargs["offset"] == 0:
            return [_row(i) for i in range(kwargs["limit"])]
        return [_row(1)]

    monkeypatch.setattr(socrata_scraper, "_fetch_soql", fake.__get__(socrata_scraper))

    rows = await socrata_scraper._fetch_all_pages(
        domain="d", dataset="x", select="*", where="1=1", order="date DESC",
        page_size=2, max_pages=10, date_col="created_date",
    )

    assert calls == [0, 2]
    assert len(rows) == 3
    assert socrata_scraper.last_meta["truncated"] is False
    assert socrata_scraper.last_meta["max_date"] == "2026-10-29"


@pytest.mark.asyncio
async def test_fetch_all_pages_marks_truncated(monkeypatch):
    async def fake(self, **kwargs):
        return [_row(i) for i in range(kwargs["limit"])]

    monkeypatch.setattr(socrata_scraper, "_fetch_soql", fake.__get__(socrata_scraper))

    rows = await socrata_scraper._fetch_all_pages(
        domain="d", dataset="x", select="*", where="1=1", order="date DESC",
        page_size=2, max_pages=3,
    )

    assert len(rows) == 6
    assert socrata_scraper.last_meta["truncated"] is True


@pytest.mark.asyncio
async def test_fetch_from_dataset_uses_watermark(monkeypatch):
    captured = {}

    async def fake(self, **kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(socrata_scraper, "_fetch_soql", fake.__get__(socrata_scraper))

    await socrata_scraper.fetch_from_dataset(
        "data.cityofnewyork.us", "erm2-nwe9", "NYC", "NY",
        field_names=["unique_key", "created_date", "complaint_type", "incident_address"],
        hours=96, limit=5000, trade_filter=False,
        watermark="2026-10-20", overlap_hours=6,
    )

    assert "2026-10-19" in captured["where"]


def test_watermark_get_set():
    key = "pytest/p0-watermark"
    db_service._service.set_scraper_watermark(key, "2026-10-20")
    assert db_service._service.get_scraper_watermark(key) == "2026-10-20"
    db_service._service.set_scraper_watermark(key, "2026-10-21")
    assert db_service._service.get_scraper_watermark(key) == "2026-10-21"


def test_feed_query_plan_uses_index():
    conn = get_connection()
    try:
        plan = conn.execute(
            """EXPLAIN QUERY PLAN
               SELECT * FROM leads
               WHERE city = 'NYC' AND lead_status = 'available'
               ORDER BY date_reported DESC LIMIT 20"""
        ).fetchall()
    finally:
        conn.close()
    text = " ".join(str(r[3]) for r in plan)
    assert "USING INDEX" in text.upper(), text

"""Backfill em lote de owners (P1, auditoria 01/11/2026)."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.services import owner_backfill

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)


class FakeDB:
    def __init__(self, leads, state=None):
        self.leads = leads
        self.state = state or {"jobs_today": 0, "last_id": 0}
        self.bumps = []
        self.updated = []
        self.listed_before = []

    async def get_owner_backfill_state(self, city, day):
        return dict(self.state)

    async def list_leads_missing_owner(self, city, before_id, limit):
        self.listed_before.append(before_id)
        return list(self.leads)[:limit]

    async def update_owner_details(self, lead_id, owner_name, mailing_address=None):
        self.updated.append((lead_id, owner_name, mailing_address))
        return True

    async def bump_owner_backfill_state(self, city, day, jobs, last_id=None):
        self.bumps.append((city, day, jobs, last_id))


@pytest.fixture()
def no_sleep(monkeypatch):
    monkeypatch.setattr(owner_backfill, "MIN_INTERVAL_SECONDS", 0)


@pytest.mark.asyncio
async def test_fills_owners_and_advances_cursor(monkeypatch, no_sleep):
    leads = [
        {"id": 30, "address": "10 Main St", "city": "NYC", "bbl": None},
        {"id": 29, "address": "20 Main St", "city": "NYC", "bbl": None},
        {"id": 28, "address": "B2B contact - a@b.com", "city": "NYC"},
    ]
    fake = FakeDB(leads)
    monkeypatch.setattr(owner_backfill, "db_service", fake)
    monkeypatch.setattr(owner_backfill, "per_city_day", lambda: 10)

    async def fake_enrich(address, city, bbl=None):
        if address == "10 Main St":
            return {"owner_name": "ANA COSTA", "mailing_address": "PO Box 1"}
        return None

    monkeypatch.setattr(owner_backfill.owner_enrichment, "enrich", fake_enrich)

    result = await owner_backfill.run_once(now=NOW, cities_override=["NYC"])

    assert result["filled"] == 1
    # B2B não é tentado nem conta para a quota.
    assert fake.bumps == [("NYC", "2026-11-02", 2, 28)]
    assert fake.updated == [(30, "ANA COSTA", "PO Box 1")]


@pytest.mark.asyncio
async def test_wraps_cursor_when_no_more_leads(monkeypatch, no_sleep):
    fake = FakeDB([], state={"jobs_today": 0, "last_id": 5})
    monkeypatch.setattr(owner_backfill, "db_service", fake)
    monkeypatch.setattr(owner_backfill, "per_city_day", lambda: 10)

    result = await owner_backfill.run_once(now=NOW, cities_override=["NYC"])

    assert result["cities"]["NYC"]["status"] == "wrapped"
    assert fake.bumps == [("NYC", "2026-11-02", 0, 0)]


@pytest.mark.asyncio
async def test_respects_daily_quota(monkeypatch, no_sleep):
    fake = FakeDB([])
    monkeypatch.setattr(owner_backfill, "db_service", fake)
    monkeypatch.setattr(owner_backfill, "per_city_day", lambda: 10)
    fake.state = {"jobs_today": 10, "last_id": 120}

    result = await owner_backfill.run_once(now=NOW, cities_override=["NYC"])

    assert result["cities"]["NYC"]["status"] == "quota"
    assert fake.bumps == []


@pytest.mark.asyncio
async def test_owner_api_failure_does_not_abort_batch(monkeypatch, no_sleep):
    leads = [
        {"id": 2, "address": "1 A St", "city": "NYC"},
        {"id": 1, "address": "2 B St", "city": "NYC"},
    ]
    fake = FakeDB(leads)
    monkeypatch.setattr(owner_backfill, "db_service", fake)
    monkeypatch.setattr(owner_backfill, "per_city_day", lambda: 10)

    async def flaky(address, city, bbl=None):
        if address == "1 A St":
            raise RuntimeError("socrata down")
        return {"owner_name": "BETA LLC"}

    monkeypatch.setattr(owner_backfill.owner_enrichment, "enrich", flaky)

    result = await owner_backfill.run_once(now=NOW, cities_override=["NYC"])

    assert result["filled"] == 1
    assert fake.bumps == [("NYC", "2026-11-02", 2, 1)]

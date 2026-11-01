"""Quota de descoberta alinhada ao orçamento Brave (P1, 01/11/2026)."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.services import brave_search
from backend.services import enrichment_scheduler as es

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)


# ------------------------------------------------------------------ quotas
def test_domain_cap_divides_brave_budget_by_enabled_cities(monkeypatch):
    monkeypatch.delenv("ENRICH_DOMAIN_PER_CITY_DAY", raising=False)
    monkeypatch.setattr(brave_search, "api_key", lambda: "brave-key")
    monkeypatch.setattr(brave_search, "daily_limit", lambda: 250)

    assert es.domain_per_city_day(3) == 83
    assert es.domain_per_city_day(8) == 31
    assert es.domain_per_city_day(0) == 250  # evita divisão por zero


def test_domain_cap_can_be_overridden(monkeypatch):
    monkeypatch.setenv("ENRICH_DOMAIN_PER_CITY_DAY", "42")
    assert es.domain_per_city_day(3) == 42


def test_without_brave_key_the_job_quota_is_used(monkeypatch):
    monkeypatch.delenv("ENRICH_DOMAIN_PER_CITY_DAY", raising=False)
    monkeypatch.setattr(brave_search, "api_key", lambda: "")
    monkeypatch.setenv("ENRICH_ENTITIES_PER_CITY_DAY", "600")
    assert es.domain_per_city_day(3) == 600


def test_domain_search_unavailable_when_budget_exhausted(monkeypatch):
    monkeypatch.setattr(brave_search, "api_key", lambda: "brave-key")
    monkeypatch.setattr(brave_search, "budget_left", lambda: 0)
    assert es.domain_search_available() is False
    monkeypatch.setattr(brave_search, "budget_left", lambda: 5)
    assert es.domain_search_available() is True


def test_without_key_search_is_not_blocked(monkeypatch):
    monkeypatch.setattr(brave_search, "api_key", lambda: "")
    monkeypatch.setattr(brave_search, "budget_left", lambda: 0)
    assert es.domain_search_available() is True


@pytest.mark.asyncio
async def test_domain_stage_defers_without_consuming_attempt(monkeypatch):
    monkeypatch.setattr(es, "domain_search_available", lambda: False)
    assert await es._domain_stage({"id": 1, "legal_name": "X"}) == "deferred"


# ------------------------------------------------------------- run_once
class FakeDB:
    def __init__(self, email_jobs=None):
        self.calls: list[tuple] = []
        self.email_jobs = email_jobs or []
        self.bump = None

    async def get_outbound_config(self, city):
        return {"enrich_enabled": "1"}

    async def get_city_enrichment_state(self, city, day):
        return {"jobs_today": 0, "domain_jobs_today": 0}

    async def list_entities_for_domain(self, city, take):
        self.calls.append(("domain", take))
        return [{"id": 1, "legal_name": "ACME", "city": city}]

    async def list_entities_for_email(self, city, take):
        self.calls.append(("email", take))
        return list(self.email_jobs)

    async def bump_city_enrichment_state(self, *args, **kwargs):
        self.bump = args


async def _no_bridge(city, take):
    return {"processed": 0, "outcomes": {}}


@pytest.mark.asyncio
async def test_run_once_does_not_list_domain_jobs_when_budget_is_gone(monkeypatch):
    fake = FakeDB()
    monkeypatch.setattr(es, "db_service", fake)
    monkeypatch.setattr(es.entity_bridge, "bridge_ready_entities", _no_bridge)
    monkeypatch.setattr(es, "domain_per_city_day", lambda n: 5)
    monkeypatch.setattr(es, "domain_search_available", lambda: False)

    result = await es.run_once(now=NOW, cities_override=["TESTCITY"])

    assert result["cities"]["TESTCITY"]["status"] == "idle"
    # Sem orçamento não há listagem de domínio; o estágio de e-mail (grátis) segue.
    assert not any(kind == "domain" for kind, _ in fake.calls)


@pytest.mark.asyncio
async def test_run_once_caps_domain_jobs_per_city(monkeypatch):
    fake = FakeDB()
    monkeypatch.setattr(es, "db_service", fake)
    monkeypatch.setattr(es.entity_bridge, "bridge_ready_entities", _no_bridge)
    monkeypatch.setattr(es, "domain_per_city_day", lambda n: 2)
    monkeypatch.setattr(es, "domain_search_available", lambda: True)

    async def fake_domain(entity):
        return "domain"

    monkeypatch.setattr(es, "_domain_stage", fake_domain)

    result = await es.run_once(now=NOW, cities_override=["TESTCITY"])

    assert ("domain", 2) in fake.calls  # take = min(CONCURRENCY, cap restante)
    assert result["cities"]["TESTCITY"]["outcomes"] == {"domain": 1}
    # bump(city, day, processed, last_id, domain_jobs)
    assert fake.bump[4] == 1

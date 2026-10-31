"""Fase 3: scheduler autónomo (OSM -> SMTP -> ready/quarentena)."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from backend.services import enrichment_scheduler
from backend.services.db import db_service, get_connection

CITY = "TESTCITY"
NOW = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)


@pytest.fixture()
def clean_entities():
    svc = db_service._service
    conn = get_connection()
    try:
        conn.execute("DELETE FROM contractor_entity_sources")
        conn.execute("DELETE FROM contractor_entities")
        conn.execute("DELETE FROM city_enrichment_state")
        conn.execute("DELETE FROM outbound_config WHERE city=?", (CITY,))
        conn.execute(
            "DELETE FROM outbound_messages WHERE lower(to_email) LIKE '%@wightco.com'"
        )
        conn.execute(
            "DELETE FROM outbound_contacts WHERE lower(email) LIKE '%@wightco.com'"
        )
        conn.execute(
            "DELETE FROM leads WHERE source_type='import_b2b' "
            "AND lower(owner_email) LIKE '%@wightco.com'"
        )
        conn.commit()
    finally:
        conn.close()
    svc.set_outbound_config("enrich_enabled", "1", CITY)
    yield
    conn = get_connection()
    try:
        conn.execute("DELETE FROM contractor_entity_sources")
        conn.execute("DELETE FROM contractor_entities")
        conn.execute("DELETE FROM city_enrichment_state")
        conn.execute("DELETE FROM outbound_config WHERE city=?", (CITY,))
        conn.execute(
            "DELETE FROM outbound_messages WHERE lower(to_email) LIKE '%@wightco.com'"
        )
        conn.execute(
            "DELETE FROM outbound_contacts WHERE lower(email) LIKE '%@wightco.com'"
        )
        conn.execute(
            "DELETE FROM leads WHERE source_type='import_b2b' "
            "AND lower(owner_email) LIKE '%@wightco.com'"
        )
        conn.commit()
    finally:
        conn.close()


def _entity(name="Wight & Company", city=CITY):
    row = db_service._service.upsert_contractor_entity(
        name, city, state="IL", role="contractor", source="test", external_id=name
    )
    assert row
    return row


@pytest.fixture(autouse=True)
def no_throttle(monkeypatch):
    async def _noop():
        return None

    monkeypatch.setattr(enrichment_scheduler, "_throttle_overpass", _noop)
    monkeypatch.setattr(
        enrichment_scheduler._discovery, "heuristic_domain", lambda *a, **k: None
    )


@pytest.mark.asyncio
async def test_domain_e_depois_email_ate_ready(clean_entities, monkeypatch):
    _entity()

    async def fake_resolve(name, city):
        return {"domain": "wightco.com", "confidence": 0.9}

    monkeypatch.setattr(enrichment_scheduler, "resolve_domain", fake_resolve)
    first = await enrichment_scheduler.run_once(now=NOW, cities_override=[CITY])
    assert first["cities"][CITY]["outcomes"] == {"domain": 1}

    fake = SimpleNamespace(catch_all=False, accepted=["info@wightco.com"])
    monkeypatch.setattr(
        enrichment_scheduler._discovery, "validate_domain", lambda *a, **k: fake
    )
    monkeypatch.setattr(
        enrichment_scheduler.entity_bridge.niche_classifier,
        "classify",
        lambda *a, **k: {
            "niche": "general_contractors",
            "status": "confirmed",
            "score": 10,
            "margin": 5,
        },
    )
    second = await enrichment_scheduler.run_once(now=NOW, cities_override=[CITY])
    assert second["cities"][CITY]["outcomes"] == {"bridged": 1}

    row = db_service._service.list_contractor_entities(CITY)[0]
    assert row["status"] == "ready"
    assert row["email"] == "info@wightco.com"
    assert row["bridged_at"]
    contact = db_service._service.get_outbound_contact_by_email(
        "info@wightco.com"
    )
    assert contact and contact["niche_status"] == "confirmed"
    assert db_service._service.outbound_readiness(CITY)["ready"] == 1


@pytest.mark.asyncio
async def test_nicho_nao_confirmado_nao_cria_contacto(clean_entities, monkeypatch):
    row = _entity()
    db_service._service.set_contractor_entity_domain(row["id"], "wightco.com", 0.9)

    fake = SimpleNamespace(catch_all=False, accepted=["info@wightco.com"])
    monkeypatch.setattr(
        enrichment_scheduler._discovery, "validate_domain", lambda *a, **k: fake
    )
    monkeypatch.setattr(
        enrichment_scheduler.entity_bridge.niche_classifier,
        "classify",
        lambda *a, **k: {
            "niche": None,
            "status": "unknown",
            "score": 0,
            "margin": 0,
        },
    )
    result = await enrichment_scheduler.run_once(now=NOW, cities_override=[CITY])
    assert result["cities"][CITY]["outcomes"] == {"niche_unconfirmed": 1}
    row = db_service._service.list_contractor_entities(CITY)[0]
    assert row["status"] == "quarantined"
    assert row["quarantine_reason"] == "niche_unconfirmed"
    assert not db_service._service.get_outbound_contact_by_email(
        "info@wightco.com"
    )


@pytest.mark.asyncio
async def test_sem_dominio_duas_vezes_quarentena(clean_entities, monkeypatch):
    _entity()

    async def fake_resolve(name, city):
        return None

    monkeypatch.setattr(enrichment_scheduler, "resolve_domain", fake_resolve)
    await enrichment_scheduler.run_once(now=NOW, cities_override=[CITY])
    row = db_service._service.list_contractor_entities(CITY)[0]
    assert row["status"] == "new"
    assert row["domain_attempts"] == 1
    await enrichment_scheduler.run_once(now=NOW, cities_override=[CITY])
    row = db_service._service.list_contractor_entities(CITY)[0]
    assert row["status"] == "quarantined"
    assert row["quarantine_reason"] == "no_domain"


@pytest.mark.asyncio
async def test_catch_all_quarentena_imediata(clean_entities, monkeypatch):
    row = _entity()
    db_service._service.set_contractor_entity_domain(row["id"], "wightco.com", 0.9)

    fake = SimpleNamespace(catch_all=True, accepted=[])
    monkeypatch.setattr(
        enrichment_scheduler._discovery, "validate_domain", lambda *a, **k: fake
    )
    result = await enrichment_scheduler.run_once(now=NOW, cities_override=[CITY])
    assert result["cities"][CITY]["outcomes"] == {"catch_all": 1}
    row = db_service._service.list_contractor_entities(CITY)[0]
    assert row["status"] == "quarantined"
    assert row["quarantine_reason"] == "catch_all"


@pytest.mark.asyncio
async def test_cidade_desligada_nao_processa(clean_entities):
    _entity()
    db_service._service.set_outbound_config("enrich_enabled", "0", CITY)
    result = await enrichment_scheduler.run_once(now=NOW, cities_override=[CITY])
    assert result["cities"][CITY]["status"] == "disabled"
    assert result["processed"] == 0


@pytest.mark.asyncio
async def test_quota_por_cidade(clean_entities, monkeypatch):
    _entity()
    monkeypatch.setenv("ENRICH_ENTITIES_PER_CITY_DAY", "1")
    day = NOW.strftime("%Y-%m-%d")
    db_service._service.bump_city_enrichment_state(CITY, day, 1)
    result = await enrichment_scheduler.run_once(now=NOW, cities_override=[CITY])
    assert result["cities"][CITY]["status"] == "quota"

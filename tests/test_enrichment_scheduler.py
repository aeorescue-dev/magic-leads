"""Fase 3: scheduler autónomo (OSM -> SMTP -> ready/quarentena)."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from backend.services import brave_search, enrichment_scheduler, entity_bridge
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
        conn.execute(
            "DELETE FROM outbound_messages WHERE lower(to_email) LIKE '%@nomisgroup.com'"
        )
        conn.execute(
            "DELETE FROM outbound_contacts WHERE lower(email) LIKE '%@nomisgroup.com'"
        )
        conn.execute(
            "DELETE FROM leads WHERE source_type='import_b2b' "
            "AND lower(owner_email) LIKE '%@nomisgroup.com'"
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
        conn.execute(
            "DELETE FROM outbound_messages WHERE lower(to_email) LIKE '%@nomisgroup.com'"
        )
        conn.execute(
            "DELETE FROM outbound_contacts WHERE lower(email) LIKE '%@nomisgroup.com'"
        )
        conn.execute(
            "DELETE FROM leads WHERE source_type='import_b2b' "
            "AND lower(owner_email) LIKE '%@nomisgroup.com'"
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
    # A ponte nunca deve ir a rede nos testes.
    monkeypatch.setattr(entity_bridge, "_site_snippet", lambda domain: "")

    async def _no_brave(*a, **k):
        return None

    monkeypatch.setattr(brave_search, "find_domain", _no_brave)


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
async def test_fallback_heuristico_usa_o_relogio_do_motor(clean_entities, monkeypatch):
    """O deadline do heuristico tem de estar no mesmo relogio do motor.

    Regressao: o scheduler passava `time.monotonic()` e o heuristico compara
    com `time.time()`, logo expirava sempre e nada chegava a `domain`.
    """
    import time as _time

    _entity()
    captured: dict[str, float] = {}

    async def fake_resolve(name, city):
        return None

    def fake_heuristic(lead, deadline):
        captured["deadline"] = deadline
        return None

    monkeypatch.setattr(enrichment_scheduler, "resolve_domain", fake_resolve)
    monkeypatch.setattr(
        enrichment_scheduler._discovery, "heuristic_domain", fake_heuristic
    )
    await enrichment_scheduler.run_once(now=NOW, cities_override=[CITY])
    assert captured, "heuristico nao foi chamado"
    assert abs(captured["deadline"] - _time.time()) < 60


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
async def test_domain_guarda_snippet_do_site(clean_entities, monkeypatch):
    _entity()

    async def fake_resolve(name, city):
        return {
            "domain": "wightco.com",
            "confidence": 0.9,
            "snippet": "Wight & Company design build plumbing",
        }

    monkeypatch.setattr(enrichment_scheduler, "resolve_domain", fake_resolve)
    await enrichment_scheduler.run_once(now=NOW, cities_override=[CITY])
    row = db_service._service.list_contractor_entities(CITY)[0]
    assert row["site_snippet"].startswith("Wight & Company design")


@pytest.mark.asyncio
async def test_ponte_confirma_nicho_pelo_texto_do_site(clean_entities, monkeypatch):
    """Sem texto, 'Nomis Group' nao confirma nicho; com o site, confirma."""
    _entity(name="Nomis Group")
    entity_id = db_service._service.list_contractor_entities(CITY)[0]["id"]
    db_service._service.mark_contractor_domain_attempt(
        entity_id,
        "nomisgroup.com",
        0.9,
        2,
        "Nomis Group is a commercial construction and general contracting firm",
    )
    db_service._service.mark_contractor_email_attempt(
        entity_id, "info@nomisgroup.com", "valid", 2
    )

    row = db_service._service.list_contractor_entities(CITY)[0]
    assert row["niche_status"] != "confirmed"  # o nome sozinho nao chega
    result = await entity_bridge.bridge_entity(row)
    assert result == "bridged"
    contact = db_service._service.get_outbound_contact_by_email(
        "info@nomisgroup.com"
    )
    assert contact and contact["niche_status"] == "confirmed"
    entity = db_service._service.list_contractor_entities(CITY)[0]
    assert entity["niche_key"] == "general_contractors"
    assert entity["niche_status"] == "confirmed"


@pytest.mark.asyncio
async def test_dominio_partilhado_vai_para_quarentena(clean_entities, monkeypatch):
    """Duas empresas no mesmo dominio = diretorio, nunca site de cada uma."""
    for name, email in (
        ("Wight & Company", "info@wightco.com"),
        ("Wight Partners", "hello@wightco.com"),
    ):
        row = _entity(name=name)
        db_service._service.mark_contractor_domain_attempt(
            row["id"], "wightco.com", 0.9, 2, "construction company"
        )
        db_service._service.mark_contractor_email_attempt(
            row["id"], email, "valid", 2
        )

    rows = db_service._service.list_contractor_entities(CITY)
    results = [await entity_bridge.bridge_entity(r) for r in rows]
    assert results == ["shared_domain", "shared_domain"]
    for row in db_service._service.list_contractor_entities(CITY):
        assert row["status"] == "quarantined"
        assert row["quarantine_reason"] == "shared_domain"
    assert db_service._service.get_outbound_contact_by_email("info@wightco.com") is None


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

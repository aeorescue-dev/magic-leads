"""Fase 2: resolver de domínio OSM (corroboração e quarentena)."""

from __future__ import annotations

import pytest

from backend.services import domain_resolver
from backend.services.domain_resolver import (
    build_overpass_query,
    name_match,
    pick_domain,
)


def test_name_match_tokens():
    assert name_match("Wight & Company", "Wight and Company") >= 0.5
    assert name_match("Skender", "Skender Construction") >= 0.5
    assert name_match("Wight & Company", "Turner Construction") == 0.0


def test_build_query_mapeia_cidade_e_escapa_nome():
    q = build_overpass_query('Acme "Builders" LLC', "NYC")
    assert 'area["name"="New York"]' in q
    assert 'nwr["name"~"Acme  Builders  LLC",i]' in q
    assert 'website' in q and 'contact:website' in q


def test_pick_domain_escolhe_melhor_e_rejeita_baixa_confianca():
    elements = [
        {
            "tags": {
                "name": "Wight and Company",
                "website": "https://www.wightco.com/about",
            }
        },
        {"tags": {"name": "Wight & Company", "contact:website": "wightco.com"}},
        {"tags": {"name": "Turner Construction", "website": "turner.com"}},
        {"tags": {"name": "Wight", "website": ""}},
    ]
    best = pick_domain(elements, "Wight & Company", "CHICAGO")
    assert best
    assert best["domain"] == "wightco.com"
    assert best["confidence"] >= 0.5
    assert pick_domain([], "Wight & Company", "CHICAGO") is None


def test_pick_domain_sem_site_nao_inventa():
    elements = [{"tags": {"name": "Wight & Company"}}]
    assert pick_domain(elements, "Wight & Company", "CHICAGO") is None


@pytest.mark.asyncio
async def test_resolve_domain_usa_fetch_mock(monkeypatch):
    async def fake_fetch(legal_name, city):
        return [
            {"tags": {"name": "Wight & Company", "website": "https://wightco.com"}}
        ]

    monkeypatch.setattr(domain_resolver, "fetch_osm_elements", fake_fetch)
    out = await domain_resolver.resolve_domain("Wight & Company", "CHICAGO")
    assert out and out["domain"] == "wightco.com"

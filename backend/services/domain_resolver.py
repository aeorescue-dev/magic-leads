"""Resolver de website/domínio por OSM/Overpass (Fase 2).

Sem site corroborado -> a entidade fica em quarentena. Nunca adivinha domínio
a partir do nome do proprietário: só aceita um resultado quando o nome do
negócio no OSM coincide com a empresa (Jaccard de tokens >= 0.5).
"""
from __future__ import annotations

import re
from typing import Iterable, Optional

import httpx

from ..utils.logger import logger
from .company_discovery import registrable_domain
from .contractor_entities import normalize_company_name

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
CITY_OSM_NAME = {
    "NYC": "New York",
    "NEW YORK": "New York",
    "CHICAGO": "Chicago",
    "DALLAS": "Dallas",
    "BOSTON": "Boston",
}
MIN_MATCH = 0.5


def _tokens(value: str) -> set[str]:
    return {t for t in re.split(r"[^A-Z0-9]+", normalize_company_name(value)) if t}


def name_match(left: str, right: str) -> float:
    a, b = _tokens(left), _tokens(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def build_overpass_query(legal_name: str, city: str) -> str:
    osm_city = CITY_OSM_NAME.get((city or "").strip().upper(), city)
    safe_name = re.sub(r'["\\\n\r\t]', " ", legal_name or "").strip()[:80]
    return (
        "[out:json][timeout:25];"
        f'area["name"="{osm_city}"]["boundary"="administrative"]->.a;'
        "("
        f'nwr["name"~"{safe_name}",i]["website"](area.a);'
        f'nwr["name"~"{safe_name}",i]["contact:website"](area.a);'
        ");"
        "out tags center 8;"
    )


def _website(tags: dict) -> Optional[str]:
    for key in ("website", "contact:website", "url"):
        value = (tags or {}).get(key)
        if value:
            return str(value).strip()
    return None


def pick_domain(
    elements: Iterable[dict], legal_name: str, city: str
) -> Optional[dict]:
    """Melhor candidato (domínio + confiança) ou None."""
    best: Optional[dict] = None
    for element in elements or []:
        tags = element.get("tags") or {}
        name = tags.get("name") or ""
        website = _website(tags)
        if not name or not website:
            continue
        score = name_match(legal_name, name)
        if score < MIN_MATCH:
            continue
        domain = registrable_domain(website)
        if not domain:
            continue
        candidate = {
            "domain": domain,
            "website": website,
            "osm_name": name,
            "confidence": round(score, 3),
            "city": city,
        }
        if not best or candidate["confidence"] > best["confidence"]:
            best = candidate
    return best


async def fetch_osm_elements(legal_name: str, city: str) -> list[dict]:
    query = build_overpass_query(legal_name, city)
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                OVERPASS_URL,
                data={"data": query},
                headers={"User-Agent": "MagicLeads/1.0 (contractor discovery)"},
            )
        if resp.status_code != 200:
            logger.warning("[DOMAIN] Overpass HTTP %s", resp.status_code)
            return []
        return list((resp.json() or {}).get("elements") or [])
    except Exception as exc:  # noqa: BLE001
        logger.warning("[DOMAIN] Overpass falhou para %r: %s", legal_name, exc)
        return []


async def resolve_domain(legal_name: str, city: str) -> Optional[dict]:
    elements = await fetch_osm_elements(legal_name, city)
    return pick_domain(elements, legal_name, city)

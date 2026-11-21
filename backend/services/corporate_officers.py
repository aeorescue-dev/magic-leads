"""Resolucao de responsaveis de entidades (LLC/trust) em registos estaduais.

Porque existe
-------------
O telefone de uma LLC nao e' o telefone do decisor: e' o telefone do imovel,
da gestora ou de um inquilino. A unica forma honesta de chegar ao decisor e'
resolver o *officer/member* no registo do Estado e so depois procurar a pessoa.

Estado actual
-------------
* `SOS_OFFICERS_ENABLED=0` por defeito (fail-closed).
* Provider implementado: OpenCorporates (API publica, precisa de chave).
* Sem chave / sem resultado -> `None`. A politica cai para `address_only`
  rotulado, nunca para "verificado".
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional

import httpx

from ..config import settings
from ..utils.logger import logger

_JURISDICTION_BY_CITY = {
    "NYC": "us_ny",
    "NEW YORK": "us_ny",
    "BROOKLYN": "us_ny",
    "QUEENS": "us_ny",
    "BRONX": "us_ny",
    "MANHATTAN": "us_ny",
    "STATEN ISLAND": "us_ny",
    "CHICAGO": "us_il",
    "BOSTON": "us_ma",
    "DALLAS": "us_tx",
}
_JURISDICTION_BY_STATE = {
    "NY": "us_ny",
    "IL": "us_il",
    "MA": "us_ma",
    "TX": "us_tx",
}

# Cargos que costumam ter poder de decisao numa LLC/empresa.
_DECISION_ROLES = (
    "member",
    "manager",
    "managing",
    "director",
    "president",
    "owner",
    "partner",
    "officer",
    "agent",
    "trustee",
)


@dataclass(frozen=True)
class OfficerRecord:
    name: str
    role: Optional[str]
    source: str
    company_name: str
    jurisdiction: str


def _jurisdiction(city: Optional[str], state: Optional[str]) -> Optional[str]:
    city_key = str(city or "").upper().strip()
    if city_key in _JURISDICTION_BY_CITY:
        return _JURISDICTION_BY_CITY[city_key]
    state_key = str(state or "").upper().strip()
    return _JURISDICTION_BY_STATE.get(state_key)


def _normalize_name(value: str) -> str:
    tokens = re.findall(r"[A-Z0-9]+", str(value or "").upper())
    noise = {"LLC", "INC", "CORP", "CO", "LTD", "LP", "LLP", "PLLC", "PC", "THE"}
    return " ".join(token for token in tokens if token not in noise)


def _pick_officer(company: dict[str, Any]) -> Optional[dict[str, Any]]:
    officers = company.get("officers") or []
    if not officers:
        return None
    best = None
    best_rank = -1
    for entry in officers:
        officer = entry.get("officer") if isinstance(entry, dict) else None
        if not officer:
            continue
        name = str(officer.get("name") or "").strip()
        if not name:
            continue
        role = str(officer.get("position") or officer.get("role") or "").strip()
        role_lower = role.lower()
        rank = 0
        for index, marker in enumerate(_DECISION_ROLES):
            if marker in role_lower:
                rank = len(_DECISION_ROLES) - index
                break
        if rank > best_rank:
            best_rank = rank
            best = {"name": name, "role": role or None}
    return best


async def _opencorporates_lookup(
    owner_name: str, jurisdiction: str
) -> Optional[OfficerRecord]:
    api_key = str(getattr(settings, "OPENCORPORATES_API_KEY", "") or "").strip()
    if not api_key:
        return None
    timeout = float(getattr(settings, "SOS_OFFICERS_TIMEOUT_SECONDS", 8.0) or 8.0)
    base = "https://api.opencorporates.com/v0.4"
    params = {
        "q": owner_name,
        "jurisdiction_code": jurisdiction,
        "api_token": api_key,
        "per_page": 5,
    }
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(f"{base}/companies/search", params=params)
            if resp.status_code != 200:
                logger.info("OpenCorporates search HTTP %s", resp.status_code)
                return None
            payload = resp.json()
            companies = (
                (payload.get("results") or {}).get("companies") or []
            )
            wanted = _normalize_name(owner_name)
            chosen = None
            for entry in companies:
                company = entry.get("company") if isinstance(entry, dict) else None
                if not company:
                    continue
                if _normalize_name(company.get("name") or "") == wanted:
                    chosen = company
                    break
            if chosen is None:
                # Sem nome exacto nao se atribui decisor: um homonimo de
                # empresa daria o contacto de outra pessoa.
                logger.info("OpenCorporates: sem match exacto para %r", owner_name)
                return None
            number = chosen.get("company_number")
            if not number:
                return None
            detail = await client.get(
                f"{base}/companies/{jurisdiction}/{number}",
                params={"api_token": api_key},
            )
            if detail.status_code != 200:
                return None
            company = (detail.json().get("results") or {}).get("company") or {}
    except Exception as exc:  # noqa: BLE001 - registo externo nunca derruba o fluxo
        logger.info("OpenCorporates lookup falhou: %s", exc)
        return None

    officer = _pick_officer(company)
    if not officer:
        return None
    return OfficerRecord(
        name=officer["name"],
        role=officer.get("role"),
        source=f"opencorporates:{jurisdiction}",
        company_name=str(company.get("name") or owner_name),
        jurisdiction=jurisdiction,
    )


async def resolve_officer(
    owner_name: Optional[str],
    city: Optional[str],
    state: Optional[str],
) -> Optional[OfficerRecord]:
    """Devolve o responsavel registado ou `None` (nunca um nome inventado)."""
    if not bool(getattr(settings, "SOS_OFFICERS_ENABLED", False)):
        return None
    if not owner_name:
        return None
    jurisdiction = _jurisdiction(city, state)
    if not jurisdiction:
        return None
    return await _opencorporates_lookup(owner_name, jurisdiction)

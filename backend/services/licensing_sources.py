"""Ingestao de licencas publicas de empreiteiros (dados de governo, $0 de API).

Primeira fonte: NYC DCWP `Issued Licenses` (Socrata w7w3-xahh), categoria
`Home Improvement Contractor`, apenas `Active` e `Premises` (empresa, nao o
individuo qualificador). Traz `contact_phone`, que o `corroborate()` usa como
sinal mais forte para aceitar um dominio — a licenca aumenta a pool E melhora
a precisao do enriquecimento.

O dataset muda devagar: corre semanalmente e e' idempotente (dedupe por
licenca/nome). Nunca levanta: devolve contagens e loga.
"""
from __future__ import annotations

import re
from typing import Iterable, Optional

import httpx

from ..utils.logger import logger
from .contractor_entities import is_usable_company_name
from .contractor_ingest import record_entities

NYC_DCWP_URL = "https://data.cityofnewyork.us/resource/w7w3-xahh.json"
NYC_LICENSE_SOURCE = "nyc_dcwp"
NYC_SELECT = (
    "business_name,dba_trade_name,license_nbr,contact_phone,"
    "address_city,address_state,address_zip,license_creation_date"
)
NYC_WHERE = (
    "business_category='Home Improvement Contractor' "
    "AND license_status='Active' AND license_type='Premises'"
)
MAX_ROWS = 20000


def _clean(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _phone(value: object) -> Optional[str]:
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits if len(digits) == 10 else None


def extract_nyc_licenses(rows: Iterable[dict]) -> list[dict]:
    """Linhas do DCWP -> entidades de contractor (puro, testavel)."""
    out: list[dict] = []
    for row in rows or []:
        name = _clean(row.get("business_name"))
        license_no = _clean(row.get("license_nbr"))
        if not name or not license_no or not is_usable_company_name(name):
            continue
        rec = {
            "legal_name": name,
            "city": "NYC",
            "state": "NY",
            "role": "contractor",
            "license": license_no,
            "source": NYC_LICENSE_SOURCE,
            "external_id": license_no,
            "phone": _phone(row.get("contact_phone")),
        }
        out.append(rec)
    return out


async def fetch_nyc_licenses(limit: int = 5000) -> list[dict]:
    """Ultimas licencas ativas (paginado) direto do Socrata, sem chave."""
    limit = max(1, min(int(limit), MAX_ROWS))
    params = {
        "$select": NYC_SELECT,
        "$where": NYC_WHERE,
        "$order": "license_creation_date DESC",
        "$limit": str(limit),
    }
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(NYC_DCWP_URL, params=params)
        if resp.status_code != 200:
            logger.warning("[LICENSES] NYC HTTP %s", resp.status_code)
            return []
        data = resp.json()
        return data if isinstance(data, list) else []
    except Exception as exc:  # noqa: BLE001
        logger.warning("[LICENSES] NYC fetch falhou: %s", exc)
        return []


async def ingest_nyc_licenses(limit: int = 2000) -> dict:
    """Busca + grava. Idempotente; devolve {fetched, extracted, saved, ...}."""
    rows = await fetch_nyc_licenses(limit=limit)
    records = extract_nyc_licenses(rows)
    result = await record_entities(records, max_records=limit)
    result["fetched"] = len(rows)
    result["extracted"] = len(records)
    logger.info(
        "[LICENSES] NYC: fetched=%s extracted=%s saved=%s",
        result["fetched"], result["extracted"], result.get("saved"),
    )
    return result

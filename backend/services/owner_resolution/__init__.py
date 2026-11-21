"""Ponto unico de resolucao de proprietario para as 4 cidades.

Uso:
    record = await resolve_owner(address="...", city="BOSTON", bbl=None)

O chamador nunca escolhe o dataset; escolhe a cidade. As diferencas de fonte
ficam nos adapters. Sem resultado -> `None` (nunca um dono "aproximado").
"""
from __future__ import annotations

from typing import Optional

from ...config import settings
from ..enrichment import CITY_ALIASES
from .base import (
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    OWNER_KIND_BUILDING,
    OWNER_KIND_COMPANY,
    OWNER_KIND_PERSON,
    OWNER_KIND_PUBLIC,
    OWNER_KIND_TRUST,
    OWNER_KIND_UNKNOWN,
    OwnerRecord,
    names_equivalent,
)
from .boston import BostonAdapter
from .chicago import ChicagoAdapter
from .dallas import DallasAdapter
from .nyc import NYCAdapter

__all__ = [
    "OwnerRecord",
    "resolve_owner",
    "city_key",
    "names_equivalent",
    "CONFIDENCE_HIGH",
    "CONFIDENCE_MEDIUM",
    "CONFIDENCE_LOW",
    "OWNER_KIND_PERSON",
    "OWNER_KIND_COMPANY",
    "OWNER_KIND_TRUST",
    "OWNER_KIND_PUBLIC",
    "OWNER_KIND_BUILDING",
    "OWNER_KIND_UNKNOWN",
]

_ADAPTERS = {
    "NYC": NYCAdapter(),
    "CHICAGO": ChicagoAdapter(),
    "BOSTON": BostonAdapter(),
    "DALLAS": DallasAdapter(),
}


def city_key(city: Optional[str]) -> Optional[str]:
    """Normaliza 'Brooklyn'/'New York'/'chicago' para a chave do adapter."""
    upper = str(city or "").upper().strip()
    if not upper:
        return None
    if upper in _ADAPTERS:
        return upper
    for alias, target in CITY_ALIASES.items():
        if alias in upper:
            return target
    return None


async def resolve_owner(
    address: str,
    city: Optional[str],
    bbl: Optional[str] = None,
) -> Optional[OwnerRecord]:
    key = city_key(city)
    adapter = _ADAPTERS.get(key or "")
    if adapter is None:
        return None
    return await adapter.resolve(address, bbl=bbl)


def max_stale_years() -> int:
    return int(getattr(settings, "PHONE_STALE_YEARS", 5) or 5)

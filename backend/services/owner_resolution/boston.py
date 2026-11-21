"""Adapter Boston — CKAN parcelas, com casamento exacto de rua.

O fallback antigo aceitava o unico candidato mesmo com rua diferente. Foi
removido no `enrichment.py`; este adapter apenas empacota o resultado exacto.
"""
from __future__ import annotations

from typing import Optional

from ..enrichment import owner_enrichment
from .base import OwnerRecord, build_record

CITY = "BOSTON"


class BostonAdapter:
    city = CITY

    async def resolve(self, address: str, bbl: Optional[str] = None) -> Optional[OwnerRecord]:
        raw = await owner_enrichment.enrich(address, CITY)
        if not raw:
            return None
        return build_record(address=address, city=CITY, raw=raw)

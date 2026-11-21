"""Adapter Dallas — DCAD por parcelid/appraisalyr."""
from __future__ import annotations

from typing import Optional

from ..enrichment import owner_enrichment
from .base import OwnerRecord, build_record

CITY = "DALLAS"


class DallasAdapter:
    city = CITY

    async def resolve(self, address: str, bbl: Optional[str] = None) -> Optional[OwnerRecord]:
        raw = await owner_enrichment.enrich(address, CITY)
        if not raw:
            return None
        return build_record(address=address, city=CITY, raw=raw)

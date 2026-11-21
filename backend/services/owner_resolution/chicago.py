"""Adapter Chicago — Cook County Assessor por PIN/PIN10.

O dataset tem `year`. Um registo antigo continua a ser o titular *daquele ano*;
nao e' licito apresenta-lo como dono actual. `stale` viaja no OwnerRecord e a
politica bloqueia a consulta paga quando o registo tem mais de 5 anos.
"""
from __future__ import annotations

from typing import Optional

from ..enrichment import owner_enrichment
from .base import OwnerRecord, build_record

CITY = "CHICAGO"


class ChicagoAdapter:
    city = CITY

    async def resolve(self, address: str, bbl: Optional[str] = None) -> Optional[OwnerRecord]:
        raw = await owner_enrichment.enrich(address, CITY)
        if not raw:
            return None
        return build_record(address=address, city=CITY, raw=raw)

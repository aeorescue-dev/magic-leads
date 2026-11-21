"""Adapter NYC — PLUTO por BBL."""
from __future__ import annotations

from typing import Optional

from ..enrichment import owner_enrichment
from .base import OwnerRecord, build_record

CITY = "NYC"

# PLUTO devolve por vezes o edificio/cooperativa em vez do dono da fraccao.
# Nao se pode chamar a isso "dono da unidade": fica `building` e a politica
# trata como entidade (nunca entrega telefone como verificado).
_BUILDING_MARKERS = (
    "CONDO",
    "CONDOMINIUM",
    "CO-OP",
    "COOP",
    "COOPERATIVE",
    "OWNERS CORP",
    "OWNERS CORPORATION",
    "HOMEOWNERS",
    "HOUSING DEVELOPMENT FUND",
)


class NYCAdapter:
    city = CITY

    async def resolve(self, address: str, bbl: Optional[str] = None) -> Optional[OwnerRecord]:
        raw = await owner_enrichment.enrich(address, CITY, bbl=bbl)
        if not raw:
            return None
        kind_override = None
        name_upper = str(raw.get("owner_name") or "").upper()
        if any(marker in name_upper for marker in _BUILDING_MARKERS):
            kind_override = "building"
        return build_record(
            address=address,
            city=CITY,
            raw=raw,
            default_parcel=bbl,
            kind_override=kind_override,
        )

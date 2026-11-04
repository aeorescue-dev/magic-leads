"""Canonicalização das 16 categorias de alerta.

O Alert Planner agrupa leads por `issue_category`. Alguns imports B2B usam
rótulos de nicho (`Roofing`, `Heating & HVAC`, ...) que não existem em
`user_interests`; sem esta camada, esses leads ficam silenciosos. Este módulo
mapeia os rótulos observados para as 16 categorias canónicas, sem alterar as
preferências dos utilizadores.

Não tem efeitos secundários: é uma função pura, testável isoladamente.
"""
from __future__ import annotations

from typing import Optional

# Fonte de verdade = categorias de `user_interests` / onboarding.
CANONICAL_CATEGORIES: tuple[str, ...] = (
    "Debris",
    "Door_Window",
    "Electrical",
    "Elevator",
    "Gas",
    "Grass",
    "Heating",
    "Lead",
    "Mold",
    "Paint",
    "Permit_Rejected",
    "Plumbing",
    "Rodent",
    "Roof",
    "Structure",
    "Unsanitary",
)

CANONICAL_SET = frozenset(CANONICAL_CATEGORIES)

# Aliases observados em produção + variantes comuns. As chaves são comparadas
# sem case e com espaços normalizados.
_ALIASES: dict[str, str] = {
    "general contractor": "Structure",
    "general contractors": "Structure",
    "remodeling": "Structure",
    "remodeling & renovation": "Structure",
    "renovation": "Structure",
    "heating & hvac": "Heating",
    "heating and hvac": "Heating",
    "hvac": "Heating",
    "roofing": "Roof",
    "restoration": "Mold",
    "restoration & cleanup": "Mold",
    "restoration and cleanup": "Mold",
    "landscaping": "Grass",
    "landscaping & grounds": "Grass",
    "landscaping and grounds": "Grass",
    "grounds": "Grass",
    "painting": "Paint",
    "doors & windows": "Door_Window",
    "doors and windows": "Door_Window",
    "door & window": "Door_Window",
    "permit rejected": "Permit_Rejected",
    "unsanitary conditions": "Unsanitary",
}

_ALIASES_NORMALIZED = {
    " ".join(key.lower().split()): value for key, value in _ALIASES.items()
}
_CANONICAL_NORMALIZED = {value.lower(): value for value in CANONICAL_CATEGORIES}


def canonical_category(raw: Optional[str]) -> str:
    """Devolve uma das 16 categorias ou "" quando não há mapeamento."""
    text = " ".join(str(raw or "").strip().split())
    if not text:
        return ""
    lower = text.lower()
    if lower in _CANONICAL_NORMALIZED:
        return _CANONICAL_NORMALIZED[lower]
    return _ALIASES_NORMALIZED.get(lower, "")


def is_supported_category(raw: Optional[str]) -> bool:
    return bool(canonical_category(raw))

"""Aliases de categoria usados por alertas e B2B.

A fonte de verdade passou a ser `category_taxonomy`. Este modulo mantem a API
historica (`CANONICAL_CATEGORIES`, `canonical_category`,
`is_supported_category`) para os chamadores existentes, mas ja nao tem uma
segunda tabela de aliases: qualquer divergencia entre alerta, ingestao e
frontend seria uma regressao.

`Unclassified` e' devolvido como string vazia por `canonical_category`: nao e'
um oficio, nao tem audiencia e nao deve gerar alerta individual.
"""
from __future__ import annotations

from typing import Optional

from .category_taxonomy import (
    TRADE_CATEGORIES,
    UNCLASSIFIED,
    normalize_category,
)

CANONICAL_CATEGORIES: tuple[str, ...] = TRADE_CATEGORIES
CANONICAL_SET = frozenset(CANONICAL_CATEGORIES)


def canonical_category(raw: Optional[str]) -> str:
    """Devolve uma das 16 categorias ou "" quando não há ofício."""
    resolved = normalize_category(raw)
    if not resolved or resolved == UNCLASSIFIED:
        return ""
    return resolved if resolved in CANONICAL_SET else ""


def is_supported_category(raw: Optional[str]) -> bool:
    return bool(canonical_category(raw))

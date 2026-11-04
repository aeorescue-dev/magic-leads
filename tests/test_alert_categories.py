"""Cobertura das 16 categorias canónicas e aliases de ingestão."""
from __future__ import annotations

import pytest

from backend.services.alert_categories import (
    CANONICAL_CATEGORIES,
    canonical_category,
    is_supported_category,
)

EXPECTED = {
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
}


def test_lista_canonica_tem_exatamente_16():
    assert len(CANONICAL_CATEGORIES) == 16
    assert set(CANONICAL_CATEGORIES) == EXPECTED


@pytest.mark.parametrize("category", sorted(EXPECTED))
def test_cada_categoria_canonica_e_idempotente(category):
    assert canonical_category(category) == category
    assert is_supported_category(category) is True


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("General Contractors", "Structure"),
        ("general contractor", "Structure"),
        ("Remodeling & Renovation", "Structure"),
        ("Remodeling", "Structure"),
        ("Heating & HVAC", "Heating"),
        ("hvac", "Heating"),
        ("Roofing", "Roof"),
        ("Restoration & Cleanup", "Mold"),
        ("Landscaping & Grounds", "Grass"),
        ("Painting", "Paint"),
        ("Doors & Windows", "Door_Window"),
        ("  roof  ", "Roof"),
        ("ROOFING", "Roof"),
    ],
)
def test_aliases_observados(raw, expected):
    assert canonical_category(raw) == expected


def test_categoria_desconhecida_nao_e_silenciada():
    assert canonical_category("Categoria Inventada") == ""
    assert is_supported_category("Categoria Inventada") is False
    assert canonical_category(None) == ""
    assert canonical_category("") == ""

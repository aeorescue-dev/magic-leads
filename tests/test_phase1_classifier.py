"""Testes do classificador de ofícios da ingestão preventiva."""
from __future__ import annotations

import pytest

from backend.services.opportunity_workflow import opportunity_workflow
from backend.services.phase1_enrichment import (
    is_actionable,
    map_category,
    phase1_enrichment,
)


@pytest.mark.parametrize(
    "description,expected",
    [
        ("SIDEWALK SHED IN PLACE WITH AN ACTIVE PERMIT", "Structure"),
        ("PEDESTRIAN PROTECTION BETWEEN STORAGE ZONE AND SIDEWALK", "Structure"),
        ("CONSTRUCTION OF A 9-STORY NEW BUILDING", "Structure"),
        ("ACTIVE SUSPENDED SCAFFOLDS AT EXPOSURE 2", "Structure"),
        ("STRUCTURAL CRACKS ON THE FACADE", "Structure"),
        ("MAINTAIN OR REPAIR ELECT ELEVA", "Elevator"),
        ("MAINTAIN OR REPAIR HYDRO ELEVA", "Elevator"),
        ("REPAIR/REPLACE SMOKE DETECTORS", "Electrical"),
        ("NO PERMIT WIRING", "Electrical"),
        ("GENERAL - BELL/BUZZER/INTERCOM", "Electrical"),
        ("CHIMNEY CAPPING", "Roof"),
        ("REPAIR EXTERIOR WALL", "Structure"),
        ("REPAIR INTERIOR WALLS/CEILING", "Structure"),
        ("SAFETY - FIRE ESCAPE", "Structure"),
        ("FOLLOW PLANS/RESUBMIT REVISED", "Permit_Rejected"),
        ("HEAT/HOT WATER - ENTIRE BUILDING", "Heating"),
        ("WATER LEAK IN THE BATHROOM", "Plumbing"),
        ("PEST CONTROL REQUIRED", "Rodent"),
        ("MOLD ON THE CEILING", "Mold"),
        ("LEAD PAINT HAZARD", "Lead"),
        ("BROKEN WINDOW FRAME", "Door_Window"),
        ("DEBRIS AND TRASH IN THE YARD", "Debris"),
        ("GAS LEAK IN THE BASEMENT", "Gas"),
        ("UNSANITARY CONDITIONS", "Unsanitary"),
        ("PAINT AND PLASTER REPAIR", "Paint"),
        ("ROOF LEAK", "Roof"),
        ("SOMETHING COMPLETELY UNKNOWN", "Structure"),
    ],
)
def test_map_category_covers_construction_and_trades(description, expected):
    assert map_category(description) == expected


def test_map_category_never_returns_unclassified():
    assert map_category("") == "Structure"
    assert map_category("X") == "Structure"


@pytest.mark.parametrize(
    "description,expected",
    [
        ("OPEN", False),
        ("ARRANGE PREMISE INSPECTION", False),
        ("OWNER OR LICENSED CONTRACTOR", False),
        ("", False),
        ("SIDEWALK SHED", True),
        ("CHIMNEY CAPPING", True),
    ],
)
def test_is_actionable_filters_generic_descriptions(description, expected):
    assert is_actionable(description) is expected


def test_reclassify_existing_cleans_unclassified_and_drops_generic():
    keep = opportunity_workflow.create_opportunity(
        source_kind="preventive",
        source_record_id="reclassify-keep",
        address="100 SIDEWALK SHED STREET",
        city="NYC",
        state="NY",
        bbl="9000000301",
        category="Unclassified",
        description="SIDEWALK SHED IN PLACE WITH AN ACTIVE PERMIT",
    )
    drop = opportunity_workflow.create_opportunity(
        source_kind="preventive",
        source_record_id="reclassify-drop",
        address="200 GENERIC STREET",
        city="NYC",
        state="NY",
        bbl="9000000302",
        category="Unclassified",
        description="OPEN",
    )

    stats = phase1_enrichment.reclassify_existing()
    assert stats["reclassified"] >= 1
    assert stats["dropped"] >= 1
    assert opportunity_workflow.get(keep["id"])["category"] == "Structure"
    assert opportunity_workflow.get(drop["id"]) is None

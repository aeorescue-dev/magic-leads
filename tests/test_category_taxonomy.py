"""Golden set da taxonomia unica (P0).

Cada caso aqui foi medido na base de producao na auditoria de 2026-11-08.
O teste e' deliberadamente negativo: os falsos positivos historicos
("rat" em registration, "shed" em unleashed, "heat" em sheathing, "leaning"
em cleaning, "brush" em brush/bulk, "overgrown" em overgrown tree) tem de
ficar em Unclassified, nunca em Roof/Structure/Rodent.
"""
from __future__ import annotations

import pytest

from backend.models.schemas import IssueCategory
from backend.scrapers.socrata_311 import socrata_scraper
from backend.services.category_taxonomy import (
    TRADE_CATEGORIES,
    UNCLASSIFIED,
    classify,
    normalize_category,
    normalize_trade_categories,
)


def _cat(desc: str, source_type: str | None = None) -> IssueCategory:
    return classify(desc, source_type).category


@pytest.mark.parametrize(
    "desc, expected",
    [
        # Exemplos explicitos do pedido: tem de continuar corretos.
        ("Clean Vacant Lot Request", IssueCategory.GRASS),
        ("Rodent Baiting/Rat Complaint", IssueCategory.RODENT),
        ("Weed Removal Request", IssueCategory.GRASS),
        # Lead: todas as formas oficiais.
        ("Lead", IssueCategory.LEAD),
        ("CONSTRUCTION LEAD DUST", IssueCategory.LEAD),
        ("Lead-Based Paint", IssueCategory.LEAD),
        ("Lead hazard", IssueCategory.LEAD),
        ("Lead Inspection Request", IssueCategory.LEAD),
        ("SCH 9/21 Lead", IssueCategory.LEAD),
        # Oficios comuns.
        ("HEAT/HOT WATER", IssueCategory.HEATING),
        ("DISP10/20Heat - Excessive Insufficient", IssueCategory.HEATING),
        ("Boiler", IssueCategory.HEATING),
        ("Gas leak", IssueCategory.GAS),
        ("Electrical wiring", IssueCategory.ELECTRICAL),
        ("Elevator", IssueCategory.ELEVATOR),
        ("Roof leak", IssueCategory.ROOF),
        ("ROOF SHEATHING", IssueCategory.ROOF),
        ("DOOR LEADING TO THE ROOF", IssueCategory.DOOR_WINDOW),
        ("Water leak", IssueCategory.PLUMBING),
        ("Water On Street Complaint", IssueCategory.PLUMBING),
        ("Water in Basement Complaint", IssueCategory.PLUMBING),
        ("Low Water Pressure Complaint", IssueCategory.PLUMBING),
        ("Water Maintenance", IssueCategory.PLUMBING),
        ("REPAIR THE LEAKY FAUCETS", IssueCategory.PLUMBING),
        ("REPAIR THE WATER CLOSET", IssueCategory.PLUMBING),
        ("PROVIDE ADEQUATE SUPPLY OF COLD WATER FOR THE FIXTURES", IssueCategory.PLUMBING),
        ("No Utilities Residential - Water", IssueCategory.PLUMBING),
        ("HOT WATERER EXCEEDS THE MAXIMUM OF 130 DEGREES", IssueCategory.HEATING),
        ("Work w/out Permit", IssueCategory.PERMIT_REJECTED),
        ("Building Permits Violation - PDD", IssueCategory.PERMIT_REJECTED),
        ("Sewer Maintenance", IssueCategory.PLUMBING),
        ("PAINT/PLASTER", IssueCategory.PAINT),
        ("Illegal Graffiti", IssueCategory.PAINT),
        ("Illegal Dumping", IssueCategory.DEBRIS),
        ("Tree Debris Clean-Up Request", IssueCategory.DEBRIS),
        ("Foundation crack", IssueCategory.STRUCTURE),
        ("TUCKPOINTING AND UNIT MASONRY REPAIR", IssueCategory.STRUCTURE),
        ("NEW DETACHED WOOD FRAME GARAGE", IssueCategory.STRUCTURE),
        ("EMERGENCY DEMOLITION OF A 2-STORY BUILDING", IssueCategory.STRUCTURE),
        ("Overgrown Weeds", IssueCategory.GRASS),
        ("Mold", IssueCategory.MOLD),
        ("Unsanitary Condition", IssueCategory.UNSANITARY),
        ("DOOR/WINDOW", IssueCategory.DOOR_WINDOW),
        ("Rent Stabilization", IssueCategory.UNCLASSIFIED),
    ],
)
def test_golden_cases(desc, expected):
    assert _cat(desc) == expected


@pytest.mark.parametrize(
    "desc",
    [
        # Falsos positivos por substring do motor antigo.
        "Single Family Rental Needs Registration - CCS",
        "ALTERATION OF EXISTING COMMUNICATION EQUIPMENT.",
        "LEVEL 2 ALTERATIONS TO AN EXISTING STOREFRONT",
        "REPAIR, REPLACE OR PROVIDE AN OPERATIONAL SMOKE DETECTOR",
        "Unleashed Dog",
        "Theater",
        "REPLACE GASKET",
        "Street Cleaning Request",
        "Sanitation Missed Brush/Bulk - SAN",
        "Overgrown Tree/Branches",
        # Ruido municipal/compliance que nao e' oficio.
        "Garbage Cart Maintenance",
        "Sanitation Missed Garbage - SAN",
        "Missed Garbage Pick-Up Complaint",
        "Missed Waste Pick-up",
        "Water/Wastewater Line Locate - 311",
        "Water Questions - 311",
        "Water Payments & Billing Inquiry - 311",
        "Water Lead Test Kit Request",
        "Rent Stabilization notice",
        "Animal-Abuse",
        "Animal Loose - DAS",
        "Stray Animal Complaint",
        "Report an Injured Animal",
        "Finance Parking Code Enforcement Review",
        "Sanitation Code Violation",
        "Unsanitary Conditions - Food",
        "Unsanitary Conditions - Establishment",
        "Code Concern - CCS",
        "FAILURE TO DISPLAY ENERGY EFFICIENCY SCORE",
        "FAILURE TO FILE BENCHMARKING REPORT OF ENERGY USE",
        "Indoor Air Quality",
        "Sidewalk Café/Outdoor Dining Complaint",
        "Street Light Pole Door Missing Complaint",
        "Street Light Outage",
        "Pothole",
        "Sidewalk Repair",
        "Building Inspection Request",
        "Domestic Animal Issue",
        "Parking Enforcement",
        "Abandoned Vehicles",
        "Sign Repair",
        "Traffic Signal Inspection",
        "Needle Pickup",
        "Contractors Complaint",
        "Illegal Dumping Sign - CCS",
        "Clean Sweep Litter Removal",
        "Graffiti Traffic Signal",
        "FISP inspection (facade inspection safety program)",
        "CL2 - Exempt",
        "The lead singer was loud",
    ],
)
def test_known_false_positives_are_unclassified(desc):
    result = classify(desc)
    assert result.category == IssueCategory.UNCLASSIFIED, (
        f"{desc!r} -> {result.category.value} ({result.rule})"
    )
    assert result.matched is False


def test_lead_does_not_match_leading_or_singer():
    # "leading" nao e' "lead": o problema era a categoria Lead, nao o oficio
    # real que porventura exista na mesma frase.
    assert _cat("LEADING TO THE ROOF") != IssueCategory.LEAD
    assert _cat("LEADING TO THE BASEMENT") == IssueCategory.UNCLASSIFIED
    assert _cat("The lead singer was loud") == IssueCategory.UNCLASSIFIED
    assert _cat("Lead") == IssueCategory.LEAD
    assert _cat("Construction Lead Dust") == IssueCategory.LEAD


def test_severe_structure_beats_roof_and_mold():
    desc = (
        "STRUCTURE RENDERED NON COMPLIANT. GARAGE AND REAR YARD WITHIN THE "
        "COLLAPSE ZONE. FIRE, SMOKE AND WATER DAMAGE. HOLES IN THE ROOF."
    )
    assert _cat(desc, "dob_violation") == IssueCategory.STRUCTURE


def test_waterproofing_is_not_roof():
    desc = (
        "FAILURE TO MAINTAIN BUILDING. PARTY WALL MISSING, INADEQUATE "
        "FLASHING/WATERPROOFING BETWEEN PROPERTIES."
    )
    assert _cat(desc, "dob_violation") == IssueCategory.STRUCTURE


def test_work_without_permit_is_permit_rejected_not_grass():
    desc = (
        "WORK W/O PERMIT. OBSERVED THE EXISTING GRASS HAS BEEN REMOVED WITH "
        "CHANGE IN GRADE AND CONCRETE INSTALLED."
    )
    assert _cat(desc, "dob_violation") == IssueCategory.PERMIT_REJECTED


def test_b2b_aliases_are_shared():
    assert _cat("B2B contact import (Restoration & Cleanup)", "import_b2b") == IssueCategory.MOLD
    assert _cat("B2B contact import (Landscaping & Grounds)", "import_b2b") == IssueCategory.GRASS
    assert _cat("B2B contact import (General Contractors)", "import_b2b") == IssueCategory.STRUCTURE
    assert _cat("B2B contact import (Remodeling & Renovation)", "import_b2b") == IssueCategory.STRUCTURE


def test_canonical_alias_normalization():
    assert normalize_category("telhado") == "Roof"
    assert normalize_category("Restoration & Cleanup") == "Mold"
    assert normalize_category("Unclassified") == UNCLASSIFIED
    assert normalize_category("Categoria Inventada") == ""
    assert normalize_trade_categories(["Roof", "telhado", "Unclassified"]) == ["Roof"]


def test_trade_categories_are_exactly_16_and_exclude_unclassified():
    assert len(TRADE_CATEGORIES) == 16
    assert UNCLASSIFIED not in TRADE_CATEGORIES


def test_scraper_delegates_to_taxonomy():
    assert socrata_scraper._infer_category("Lead") == IssueCategory.LEAD
    assert socrata_scraper._infer_category("Unleashed Dog") == IssueCategory.UNCLASSIFIED
    cat, matched = socrata_scraper._infer_category_ex("Garbage Cart Maintenance")
    assert (cat, matched) == (IssueCategory.UNCLASSIFIED, False)

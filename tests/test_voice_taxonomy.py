"""Taxonomia de voz: sinónimos, licenças e classificação multi-label."""
from __future__ import annotations

from backend.services import voice_taxonomy as tax


def _trades(signals):
    return {s.trade: s.confidence for s in signals}


def test_license_type_master_plumber():
    signals = tax.classify_company("ACME CORP", license_type="MASTER PLUMBER")
    assert signals[0].trade == "plumbing"
    assert signals[0].confidence >= 0.95
    assert signals[0].source == "license_type"


def test_name_plumbing_and_heating_is_multi_label():
    signals = tax.classify_company("Radant Plumbing & Heating")
    trades = _trades(signals)
    assert trades["plumbing"] >= 0.90
    assert trades["hvac"] >= 0.90


def test_generic_construction_does_not_create_trade():
    assert tax.classify_company("ABC Construction Corp") == []


def test_negative_supply_blocks_false_positive():
    assert "plumbing" not in _trades(tax.classify_company("ABC Plumbing Supply"))
    assert "roofing" not in _trades(tax.classify_company("NY Roofing Supply"))


def test_waste_oil_is_not_debris_removal():
    assert "debris_removal" not in _trades(
        tax.classify_company("Boro Waste Oil, LLC")
    )


def test_stairlift_is_low_confidence_elevator():
    trades = _trades(tax.classify_company("American Stairlifts, LLC"))
    assert trades.get("elevator", 0) < 0.80


def test_glass_and_storefront_are_windows():
    trades = _trades(tax.classify_company("Major Glass & Metal"))
    assert trades["windows"] >= 0.80


def test_primary_specific_trade_is_preserved():
    signals = tax.classify_company("XYZ Corp", primary_trade="plumbing")
    assert "plumbing" in _trades(signals)


def test_primary_general_contractor_does_not_confirm_by_itself():
    signals = tax.classify_company("XYZ Corp", primary_trade="general_contractor")
    assert "general_contractor" not in _trades(signals)


def test_category_trade_dropdown_labels():
    assert tax.category_trade("Roofing & Structure") == "roofing"
    assert tax.category_trade("Structure") == "remodeling"
    assert tax.category_trade("Heating & Hot Water") == "hvac"
    assert tax.category_trade("Doors & Windows") == "windows"
    assert tax.category_trade("Rodents & Pests") == "pest_control"
    assert tax.category_trade("Construction & Permits") is None


def test_category_for_trade():
    assert tax.category_for_trade("plumbing") == "Plumbing"
    assert tax.category_for_trade("hvac") == "Heating"
    assert tax.category_for_trade("unknown") == ""

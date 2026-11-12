"""Conectores de permisos de obra (Dallas e Boston).

Contexto medido em producao (2026-11-11): o 311 de Dallas tinha 15.708 de
17.151 leads em `Unclassified` (91%) porque o dataset so publica o tipo
municipal ("Code Concern", "Missed Garbage", "Animal Loose"). O dataset de
Building Permits de Dallas traz o oficio no proprio tipo e ~1.600 registos
por 7 dias. Boston tem o mesmo padrao: 311 cobre queixas, os permisos
trazem a obra.

Este teste fixa:
  1. o tipo de permiso manda na classificacao;
  2. a descricao so decide quando o tipo e' generico;
  3. artefactos ("elevator lobby", "paint booth") nao viram oficio;
  4. datas MM/DD/YY (Dallas) sao interpretadas corretamente;
  5. endereco, zip e dedupe ficam consistentes.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.models.schemas import IssueCategory
from backend.scrapers.socrata_311 import socrata_scraper
from backend.services.category_taxonomy import UNCLASSIFIED, classify_permit


@pytest.mark.parametrize(
    "permit_type, description, expected",
    [
        ("Residential Plumbing Permit", "Replace 40 ft gas yard service", IssueCategory.GAS),
        ("Commercial Plumbing Permit", "Gas test for restaurant", IssueCategory.GAS),
        ("Residential Plumbing Permit", "Repair sewer line", IssueCategory.PLUMBING),
        ("Commercial Electrical Permit", "Panel upgrade", IssueCategory.ELECTRICAL),
        ("Residential Solar/PV Permit", "11.34 kW PV solar installation", IssueCategory.ELECTRICAL),
        ("Residential Mechanical Permit", "HVAC changeout", IssueCategory.HEATING),
        ("Commercial Mechanical Permit", "Replace two RTUs", IssueCategory.HEATING),
        ("Residential Roofing Permit", "Remove shingles, install new roof", IssueCategory.ROOF),
        ("Residential Foundation Repair", "Pier and beam leveling", IssueCategory.STRUCTURE),
        ("Residential Accessory Structure Permit", "8 foot fence", IssueCategory.STRUCTURE),
        ("Residential New Construction Permit", "New single family construction", IssueCategory.STRUCTURE),
        ("Residential Demolition Permit", "Complete demolition and haul off", IssueCategory.STRUCTURE),
        # Boston usa worktype como codigo e permittypedescr como rotulo.
        ("Electrical Permit ELECTRICAL", "120 volts 30 amps", IssueCategory.ELECTRICAL),
        ("Plumbing Permit PLUMBING", "Replace water heater", IssueCategory.PLUMBING),
        ("Gas Permit GAS", "Gas piping", IssueCategory.GAS),
        ("Roof Permit ROOF", "Strip and re-roof", IssueCategory.ROOF),
    ],
)
def test_permit_type_drives_category(permit_type, description, expected):
    result = classify_permit(permit_type, description)
    assert result.matched is True, f"{permit_type!r} devia ser oficio"
    assert result.category == expected


@pytest.mark.parametrize(
    "permit_type, description",
    [
        ("Commercial Alteration Addition Permit", "New spec suite including Elevator Lobby"),
        ("Commercial Alteration Addition Permit", "Replace two paint booths"),
        ("Residential Drive Approach and Sidewalk Permit", "New driveway approach"),
        ("Residential Pool Permit", "New swimming pool"),
        ("Commercial Alteration Addition Permit", "Install pallet racking"),
    ],
)
def test_generic_permits_without_trade_stay_unclassified(permit_type, description):
    result = classify_permit(permit_type, description)
    assert result.matched is False
    assert result.category.value == UNCLASSIFIED


def test_permit_date_mm_dd_yy_is_parsed():
    parsed = socrata_scraper._parse_permit_date("11/05/26")
    assert parsed == datetime(2026, 11, 5, tzinfo=timezone.utc)
    # Export antigo sem zero a esquerda.
    assert socrata_scraper._parse_permit_date("11/5/26") == parsed


def test_permit_date_iso_is_parsed():
    parsed = socrata_scraper._parse_permit_date("2026-11-06T14:04:22")
    assert parsed == datetime(2026, 11, 6, 14, 4, 22, tzinfo=timezone.utc)


def test_dallas_permit_row_becomes_lead():
    row = {
        "permit_number": "RES-ROOF-26-000123",
        "issued_date": "11/05/26",
        "permit_type": "Residential Roofing Permit",
        "work_description": "Remove existing shingles and install new roof",
        "street_address": "1902 N CARROLL AVE, Dallas, TX",
        "zip_code": "75204",
    }
    leads = socrata_scraper.parse_permit_rows(
        [row], city="Dallas", state="TX", external_prefix="dal-permit:"
    )
    assert len(leads) == 1
    lead = leads[0]
    assert lead.external_id == "dal-permit:RES-ROOF-26-000123"
    assert lead.address == "1902 N CARROLL AVE"
    assert lead.city == "Dallas"
    assert lead.zip_code == "75204"
    assert lead.source_type == "permit"
    assert lead.issue_category == IssueCategory.ROOF
    assert lead.created_at.date().isoformat() == "2026-11-05"


def test_boston_permit_row_becomes_lead():
    row = {
        "permitnumber": "E1917340",
        "issued_date": "2026-11-06T14:04:22",
        "permittypedescr": "Electrical Permit",
        "worktype": "ELECTRICAL",
        "description": "Electrical",
        "comments": "120 volts 30 amps Disconnect",
        "address": "101 Redlands RD",
        "city": "West Roxbury",
        "state": "MA",
        "zip": "02132",
    }
    leads = socrata_scraper.parse_permit_rows(
        [row], city="Boston", state="MA", external_prefix="bos-permit:"
    )
    assert len(leads) == 1
    lead = leads[0]
    assert lead.external_id == "bos-permit:E1917340"
    assert lead.address == "101 REDLANDS RD"
    assert lead.zip_code == "02132"
    assert lead.issue_category == IssueCategory.ELECTRICAL


def test_permit_before_min_date_is_dropped():
    row = {
        "permit_number": "OLD-1",
        "issued_date": "10/01/26",
        "permit_type": "Residential Roofing Permit",
        "work_description": "Re-roof",
        "street_address": "10 OLD ST, Dallas, TX",
        "zip_code": "75201",
    }
    leads = socrata_scraper.parse_permit_rows(
        [row],
        city="Dallas",
        state="TX",
        min_date=datetime(2026, 11, 4, tzinfo=timezone.utc),
    )
    assert leads == []


def test_permit_without_street_is_dropped():
    row = {
        "permit_number": "NOADDR-1",
        "issued_date": "11/05/26",
        "permit_type": "Residential Roofing Permit",
        "work_description": "Re-roof",
        "street_address": "Dallas, TX",
        "zip_code": "75201",
    }
    leads = socrata_scraper.parse_permit_rows([row], city="Dallas", state="TX")
    assert leads == []


def test_permit_rows_are_deduplicated_by_number():
    row = {
        "permit_number": "DUP-1",
        "issued_date": "11/05/26",
        "permit_type": "Residential Plumbing Permit",
        "work_description": "Replace sewer line",
        "street_address": "500 MAIN ST, Dallas, TX",
        "zip_code": "75201",
    }
    leads = socrata_scraper.parse_permit_rows(
        [row, dict(row)], city="Dallas", state="TX"
    )
    assert len(leads) == 1

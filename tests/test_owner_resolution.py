"""Resolucao do proprietario nas 4 cidades + regra do registo antigo."""
from __future__ import annotations

import asyncio

import pytest

from backend.services.enrichment import CITY_DATASETS, OwnerEnrichment, owner_enrichment
from backend.services.owner_resolution import (
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    OWNER_KIND_BUILDING,
    OWNER_KIND_COMPANY,
    OWNER_KIND_PERSON,
    resolve_owner,
)
from backend.services.owner_resolution.base import (
    build_record,
    classify_confidence,
    mailing_matches_property,
)


def _patch_enrich(monkeypatch, payload):
    async def _fake(*args, **kwargs):
        return payload

    monkeypatch.setattr(owner_enrichment, "enrich", _fake)


def test_nyc_bbl_is_high_confidence_and_parcel_key(monkeypatch):
    _patch_enrich(
        monkeypatch,
        {
            "owner_name": "SENGARAYAR, LOYD",
            "parcel_key": "4087860042",
            "match_method": "bbl",
            "match_score": 1.0,
            "source_dataset": "data.cityofnewyork.us/64uk-42ks",
        },
    )
    record = asyncio.run(resolve_owner("84-74 257 STREET", "QUEENS", bbl="4087860042"))
    assert record is not None
    assert record.confidence == CONFIDENCE_HIGH
    assert record.parcel_key == "4087860042"
    assert record.owner_kind == OWNER_KIND_PERSON
    assert record.match_method == "bbl"


def test_nyc_condo_is_building_not_unit_owner(monkeypatch):
    _patch_enrich(
        monkeypatch,
        {
            "owner_name": "PARK PLACE OWNERS CORP",
            "parcel_key": "3000010001",
            "match_method": "bbl",
            "match_score": 1.0,
        },
    )
    record = asyncio.run(resolve_owner("100 PARK PLACE", "MANHATTAN", bbl="3000010001"))
    assert record is not None
    assert record.owner_kind == OWNER_KIND_BUILDING
    assert record.is_entity is True


def test_chicago_old_year_is_stale(monkeypatch):
    _patch_enrich(
        monkeypatch,
        {
            "owner_name": "BIG DEAHL LTD LIAB CO",
            "parcel_key": "14123000100000",
            "record_year": 2011,
            "match_method": "exact_address",
            "match_score": 1.0,
        },
    )
    record = asyncio.run(resolve_owner("1412 N KINGSBURY ST", "CHICAGO"))
    assert record is not None
    assert record.stale is True
    assert record.owner_kind == OWNER_KIND_COMPANY


def test_chicago_recent_year_is_fresh(monkeypatch):
    _patch_enrich(
        monkeypatch,
        {
            "owner_name": "JANE DOE",
            "parcel_key": "123",
            "record_year": 2025,
            "match_method": "exact_address",
            "match_score": 1.0,
        },
    )
    record = asyncio.run(resolve_owner("10 N STATE ST", "CHICAGO"))
    assert record is not None
    assert record.stale is False


def test_boston_owner_occupied_and_pid(monkeypatch):
    _patch_enrich(
        monkeypatch,
        {
            "owner_name": "CLAIRE M CRONIN BE",
            "parcel_key": "0501234000",
            "owner_occupied": True,
            "match_method": "exact_address",
            "match_score": 1.0,
        },
    )
    record = asyncio.run(resolve_owner("199 SAVIN HILL AV", "BOSTON"))
    assert record is not None
    assert record.parcel_key == "0501234000"
    assert record.owner_occupied is True
    assert record.is_absentee is False


def test_dallas_mailing_differs_marks_absentee(monkeypatch):
    _patch_enrich(
        monkeypatch,
        {
            "owner_name": "SHAMLIN GEORGE C",
            "parcel_key": "000001234567",
            "mailing_address": "1450 N DAYTON ST, CHICAGO, 60622",
            "record_year": 2025,
            "match_method": "exact_address",
            "match_score": 1.0,
        },
    )
    record = asyncio.run(resolve_owner("2206 LANARK AVE", "DALLAS"))
    assert record is not None
    assert record.is_absentee is True


def test_boston_single_candidate_fallback_is_gone():
    """Regressao: unico candidato com rua diferente NAO pode virar owner."""
    svc = OwnerEnrichment()
    cfg = CITY_DATASETS["BOSTON"]
    out = svc._match_ckan(
        [{"OWNER": "WRONG NEIGHBOUR", "full_address": "999 OTHER ST"}],
        cfg,
        "10",
        "MAIN ST",
        "10 MAIN ST",
    )
    assert out is None


def test_boston_exact_match_still_works():
    svc = OwnerEnrichment()
    cfg = CITY_DATASETS["BOSTON"]
    out = svc._match_ckan(
        [{"OWNER": "RIGHT OWNER", "full_address": "10 MAIN ST"}],
        cfg,
        "10",
        "MAIN ST",
        "10 MAIN ST",
    )
    assert out is not None
    assert out["owner_name"] == "RIGHT OWNER"
    assert out["match_method"] == "exact_address"


def test_chicago_config_reads_record_year_for_staleness():
    """Regressao Fase A: `year_col` so' ordena; `record_year_col` alimenta stale."""
    cfg = CITY_DATASETS["CHICAGO"]
    assert cfg["record_year_col"] == "year"
    out = OwnerEnrichment()._build_result(
        {
            "owner_address_name": "OLD OWNER LLC",
            "prop_address_full": "10 N STATE ST",
            "year": "2011",
        },
        cfg,
        "10 N STATE ST",
        match_method="exact_address",
    )
    assert out["record_year"] == 2011
    record = build_record(address="10 N STATE ST", city="CHICAGO", raw=out)
    assert record.stale is True


def test_street_substring_is_low_confidence():
    assert classify_confidence("street_substring", 0.7, None) == CONFIDENCE_LOW


def test_mailing_match_normalizes_suffixes():
    assert mailing_matches_property("199 SAVIN HILL AV", "199 SAVIN HILL AVE") is True
    assert mailing_matches_property("10 MAIN ST", "99 OTHER ST") is False


def test_build_record_never_invents_owner():
    assert build_record(address="10 MAIN ST", city="BOSTON", raw={}) is None


@pytest.mark.parametrize("method", ["bbl", "exact_address"])
def test_exact_methods_are_high(method):
    assert classify_confidence(method, 1.0, "x") == CONFIDENCE_HIGH

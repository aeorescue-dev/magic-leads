"""Resolucao de responsaveis de entidades: fail-closed e sem homonimos."""
from __future__ import annotations

import asyncio

from backend.config import settings
from backend.services.corporate_officers import (
    OfficerRecord,
    _normalize_name,
    _pick_officer,
    resolve_officer,
)


def test_disabled_returns_none(monkeypatch):
    monkeypatch.setattr(settings, "SOS_OFFICERS_ENABLED", False, raising=False)
    assert asyncio.run(resolve_officer("ACME HOLDINGS LLC", "NYC", "NY")) is None


def test_enabled_without_key_returns_none(monkeypatch):
    monkeypatch.setattr(settings, "SOS_OFFICERS_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "OPENCORPORATES_API_KEY", "", raising=False)
    assert asyncio.run(resolve_officer("ACME HOLDINGS LLC", "NYC", "NY")) is None


def test_pick_officer_prefers_decision_role():
    company = {
        "officers": [
            {"officer": {"name": "CLERK PERSON", "position": "Clerk"}},
            {"officer": {"name": "REAL MANAGER", "position": "Managing Member"}},
        ]
    }
    picked = _pick_officer(company)
    assert picked["name"] == "REAL MANAGER"


def test_pick_officer_ignores_empty_names():
    assert _pick_officer({"officers": [{"officer": {"name": "  "}}]}) is None


def test_normalize_company_name_strips_suffixes():
    assert _normalize_name("ACME HOLDINGS LLC") == "ACME HOLDINGS"


def test_officer_record_shape():
    rec = OfficerRecord(
        name="JANE DOE",
        role="Member",
        source="opencorporates:us_ny",
        company_name="ACME HOLDINGS LLC",
        jurisdiction="us_ny",
    )
    assert rec.name == "JANE DOE"
    assert rec.jurisdiction == "us_ny"

"""Testes do pipeline de Chicago: ZIP, watermark, permits e territórios."""

from __future__ import annotations

import pytest

from backend.services import phase1_enrichment
from backend.services.db import get_connection
from backend.services.opportunity_workflow import opportunity_workflow
from backend.services.zip_lookup import resolve_chicago_zip


@pytest.fixture(autouse=True)
def _clean():
    conn = get_connection()
    try:
        conn.execute("DELETE FROM opportunity_workflow")
        conn.execute("DELETE FROM phase1_watermarks")
        conn.commit()
    finally:
        conn.close()
    yield


def _violation(
    record: str,
    address: str,
    *,
    modified: str,
    lat: str = "41.88",
    lng: str = "-87.63",
) -> dict:
    return {
        "id": record,
        "address": address,
        "violation_description": "Roof structure",
        "violation_code": "1",
        "violation_status": "OPEN",
        "violation_date": modified[:10],
        "violation_last_modified_date": modified,
        "inspection_status": "FAILED",
        "latitude": lat,
        "longitude": lng,
    }


def test_resolve_zip_by_centroid_and_contact():
    zip_code, source = resolve_chicago_zip(lat=41.88567, lng=-87.62528)
    assert (zip_code, source) == ("60601", "centroid")

    zip_code, source = resolve_chicago_zip(
        address="RUA QUE NAO EXISTE 999", contact_zip="60601"
    )
    assert (zip_code, source) == ("60601", "contact")

    zip_code, source = resolve_chicago_zip(
        address="RUA QUE NAO EXISTE 999", contact_zip="75201"
    )
    assert (zip_code, source) == (None, "unresolved")


def test_violations_use_watermark_and_resolve_zip(monkeypatch):
    rows = [
        _violation("v1", "1 ALPHA ST", modified="2026-11-01T00:00:00"),
        _violation("v2", "2 BETA AVE", modified="2026-11-02T00:00:00"),
        _violation("v3", "3 GAMMA RD", modified="2026-11-03T00:00:00"),
    ]
    calls: list[dict] = []

    def fake_socrata(source, params):
        calls.append(params)
        offset = int(params.get("$offset", 0))
        limit = int(params.get("$limit", 1000))
        return rows[offset : offset + limit]

    monkeypatch.setattr(phase1_enrichment, "socrata", fake_socrata)
    monkeypatch.setattr(
        phase1_enrichment,
        "resolve_chicago_zip",
        lambda **_: ("60601", "centroid"),
    )

    items = phase1_enrichment.phase1_enrichment.fetch_chicago_violations(limit=3)

    assert len(items) == 3
    assert all(item["zip_code"] == "60601" for item in items)
    assert all(item["zip_source"] == "centroid" for item in items)
    assert calls and calls[0]["$offset"] == 0
    watermark = phase1_enrichment._get_watermark(
        phase1_enrichment.CHI_VIOLATIONS_WATERMARK
    )
    assert watermark == "2026-11-03T00:00:00"


def test_chicago_permits_become_authorized_work(monkeypatch):
    rows = [
        {
            "id": "1",
            "permit_": "P1",
            "permit_type": "Renovation",
            "issue_date": "2026-11-18",
            "street_number": "100",
            "street_direction": "W",
            "street_name": "Main St",
            "work_description": "Replace roof",
            "contact_1_zipcode": "60601",
            "latitude": "41.88",
            "longitude": "-87.63",
            "reported_cost": "10000",
        }
    ]
    monkeypatch.setattr(phase1_enrichment, "socrata", lambda *_, **__: rows)
    monkeypatch.setattr(
        phase1_enrichment,
        "resolve_chicago_zip",
        lambda **_: ("60601", "centroid"),
    )

    items = phase1_enrichment.phase1_enrichment.fetch_chicago_permits(
        limit=10, days=30
    )

    assert len(items) == 1
    item = items[0]
    assert item["city"] == "Chicago"
    assert item["zip_code"] == "60601"
    assert item["zip_source"] == "centroid"
    assert item["signal_type"] == "authorized_work"
    assert item["category"] == "Roof"
    assert item["job_value"] == 10000


def test_territories_keep_unmapped_rows_and_niches():
    opportunity_workflow.create_opportunity(
        source_kind="preventive",
        source_record_id="chi-no-zip",
        address="100 W MAIN ST",
        city="Chicago",
        state="IL",
        zip_code=None,
        category="Plumbing",
        severity="high",
        signal_type="legal_obligation",
    )

    result = opportunity_workflow.territories(city="Chicago", days=30)

    assert result["totals"]["count"] == 1
    assert result["totals"]["zones"] == 0
    assert result["totals"]["unmapped"] == 1
    assert result["zones"] == []
    assert result["niches"] == [{"key": "Plumbing", "n": 1}]


def test_create_opportunity_persists_zip_source():
    row = opportunity_workflow.create_opportunity(
        source_kind="preventive",
        source_record_id="chi-zip-source",
        address="200 W MAIN ST",
        city="Chicago",
        state="IL",
        zip_code="60601",
        zip_source="centroid",
        category="Roof",
        severity="high",
        signal_type="legal_obligation",
    )

    assert row["zip_code"] == "60601"
    assert row["zip_source"] == "centroid"

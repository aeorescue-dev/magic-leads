"""Agregação territorial (ZIP x nicho) — testes do serviço."""

from __future__ import annotations

import pytest

from backend.services.db import get_connection
from backend.services.opportunity_workflow import opportunity_workflow


@pytest.fixture(autouse=True)
def _clean_workflow():
    conn = get_connection()
    try:
        conn.execute("DELETE FROM opportunity_workflow")
        conn.commit()
    finally:
        conn.close()
    yield


def _create(
    *,
    record: str,
    address: str,
    city: str = "Boston",
    zip_code: str | None = "02124",
    category: str = "Structure",
    severity: str = "high",
    received_at: str | None = None,
    compliance_deadline: str | None = None,
) -> dict:
    return opportunity_workflow.create_opportunity(
        source_kind="preventive",
        source_record_id=record,
        source_type="pre_inspection",
        address=address,
        city=city,
        state="MA" if city == "Boston" else "TX",
        zip_code=zip_code,
        category=category,
        severity=severity,
        received_at=received_at,
        compliance_deadline=compliance_deadline,
    )


def test_territories_groups_by_zip_and_niche():
    _create(record="t1", address="10 Alpha St", category="Structure", severity="critical")
    _create(record="t2", address="12 Alpha St", category="Structure", severity="medium")
    _create(record="t3", address="20 Beta Ave", zip_code="02128", category="Plumbing")
    _create(record="t4", address="30 Gamma Rd", city="Dallas", category="Roof")

    result = opportunity_workflow.territories(city="boston", days=30)

    assert result["totals"]["zones"] == 2
    assert result["totals"]["count"] == 3
    assert result["totals"]["critical"] == 1
    assert [zone["zip"] for zone in result["zones"]] == ["02124", "02128"]

    first = result["zones"][0]
    assert first["total"] == 2
    assert first["niches"] == [{"key": "Structure", "n": 2}]
    assert first["critical"] == 1

    top = result["niches"][0]
    assert top == {"key": "Structure", "n": 2}


def test_territories_ignores_rows_without_zip_and_other_cities():
    _create(record="t5", address="1 No Zip St", zip_code=None)
    _create(record="t6", address="2 No Zip St", zip_code="   ")
    _create(record="t7", address="3 Dallas St", city="Dallas", zip_code="75214")

    boston = opportunity_workflow.territories(city="Boston", days=30)
    dallas = opportunity_workflow.territories(city="Dallas", days=30)

    assert boston["totals"]["count"] == 0
    assert boston["zones"] == []
    assert dallas["totals"]["count"] == 1
    assert dallas["zones"][0]["zip"] == "75214"


def test_territories_filters_window_and_category():
    _create(record="t8", address="40 Old Rd", category="Roof")
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE opportunity_workflow SET received_at = datetime('now', '-60 days') "
            "WHERE source_record_id = 't8'"
        )
        conn.commit()
    finally:
        conn.close()

    recent = opportunity_workflow.territories(city="Boston", days=30)
    older = opportunity_workflow.territories(city="Boston", days=90)

    assert all(zone["total"] for zone in recent["zones"])
    assert older["totals"]["count"] == recent["totals"]["count"] + 1

    only_roof = opportunity_workflow.territories(
        city="Boston", days=90, category="Roof"
    )
    assert only_roof["totals"]["count"] == 1
    assert only_roof["zones"][0]["niches"] == [{"key": "Roof", "n": 1}]


def test_territories_flags_fresh_recent_or_near_deadline():
    _create(record="fr1", address="1 Fresh St")
    _create(
        record="fr2",
        address="2 Deadline Ave",
        compliance_deadline="2020-01-01",  # data fixa antiga -> vencida, conta
    )
    _create(record="fr3", address="3 Stale Rd")
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE opportunity_workflow SET received_at = datetime('now', '-5 days') "
            "WHERE source_record_id IN ('fr2', 'fr3')"
        )
        conn.commit()
    finally:
        conn.close()

    result = opportunity_workflow.territories(city="Boston", days=30)

    zone = result["zones"][0]
    assert zone["total"] == 3
    assert zone["fresh"] == 2
    assert result["totals"]["fresh"] == 2


def test_territories_requires_city():
    try:
        opportunity_workflow.territories(city="   ")
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_list_filters_by_neighborhood_zips():
    _create(record="z1", address="1 Alpha St", zip_code="02124")
    _create(record="z2", address="2 Beta Ave", zip_code="02125")
    _create(record="z3", address="3 Gamma Rd", zip_code="02128")

    result = opportunity_workflow.list(
        kind="preventive", city="Boston", zips=["02124", "02125"]
    )

    assert result["total"] == 2
    assert {row["zip_code"] for row in result["opportunities"]} == {
        "02124",
        "02125",
    }

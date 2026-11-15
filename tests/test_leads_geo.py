"""Agregação geográfica e filtro por bairro no feed de leads."""

from __future__ import annotations

import pytest

from backend.services.db import db_service, get_connection, init_db


def _insert_lead(
    *,
    external_id: str,
    city: str,
    neighborhood: str | None,
    zip_code: str | None,
    category: str = "Roof",
    lat: float | None = 42.3,
    lng: float | None = -71.0,
) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO leads "
            "(external_id, source_type, address, city, state, issue_category, "
            "date_reported, is_feed_ok, signal_type, signal_status, lead_status, "
            "neighborhood, zip_code, lat, lng, urgency_level) "
            "VALUES (?, 'dev', ?, ?, 'MA', ?, datetime('now'), 1, "
            "'open_request', 'open', 'available', ?, ?, ?, ?, 'medium')",
            (
                external_id,
                f"{external_id} Street",
                city,
                category,
                neighborhood,
                zip_code,
                lat,
                lng,
            ),
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture(autouse=True)
def _clean_leads():
    init_db()
    conn = get_connection()
    try:
        conn.execute("DELETE FROM leads")
        conn.commit()
    finally:
        conn.close()
    yield


def test_geo_summary_groups_by_neighborhood_then_zip():
    _insert_lead(external_id="g1", city="Boston", neighborhood="Dorchester", zip_code="02124")
    _insert_lead(external_id="g2", city="Boston", neighborhood="Dorchester", zip_code="02124")
    _insert_lead(external_id="g3", city="Boston", neighborhood=None, zip_code="02128")
    _insert_lead(external_id="g4", city="Boston", neighborhood=None, zip_code=None)

    result = db_service._service.get_leads_geo_summary(
        city="Boston", days=7, user_id=5
    )

    assert result["total"] == 4
    groups = {(g["kind"], g["key"]): g["n"] for g in result["groups"]}
    assert groups[("nb", "Dorchester")] == 2
    assert groups[("zip", "02128")] == 1
    assert groups[("none", "")] == 1


def test_geo_summary_respects_city_and_filters():
    _insert_lead(external_id="h1", city="Boston", neighborhood="Roxbury", zip_code="02119")
    _insert_lead(
        external_id="h2",
        city="Boston",
        neighborhood="Dorchester",
        zip_code="02124",
        category="Plumbing",
    )
    _insert_lead(external_id="h3", city="Dallas", neighborhood=None, zip_code="75214")

    boston = db_service._service.get_leads_geo_summary(
        city="Boston", days=7, user_id=5
    )
    assert boston["total"] == 2
    assert {g["key"] for g in boston["groups"]} == {"Roxbury", "Dorchester"}

    plumbing = db_service._service.get_leads_geo_summary(
        city="Boston", days=7, user_id=5, category="Plumbing"
    )
    assert plumbing["total"] == 1
    assert plumbing["groups"][0]["key"] == "Dorchester"


def test_feed_filters_by_neighborhood_zips_and_no_geo():
    _insert_lead(external_id="f1", city="Boston", neighborhood="Dorchester", zip_code="02124")
    _insert_lead(external_id="f2", city="Boston", neighborhood="Dorchester", zip_code="02125")
    _insert_lead(external_id="f3", city="Boston", neighborhood="Roxbury", zip_code="02119")
    _insert_lead(external_id="f4", city="Boston", neighborhood=None, zip_code="02128")
    _insert_lead(external_id="f5", city="Boston", neighborhood=None, zip_code=None)

    by_nb, total_nb = db_service._service.get_leads_feed(
        city="Boston", neighborhoods=["Dorchester"], days=7, user_id=5
    )
    assert total_nb == 2
    assert {row["external_id"] for row in by_nb} == {"f1", "f2"}

    by_zip, total_zip = db_service._service.get_leads_feed(
        city="Boston", zips=["02119", "02128"], days=7, user_id=5
    )
    assert total_zip == 2
    assert {row["external_id"] for row in by_zip} == {"f3", "f4"}

    no_geo, total_none = db_service._service.get_leads_feed(
        city="Boston", no_geo=True, days=7, user_id=5
    )
    assert total_none == 1
    assert no_geo[0]["external_id"] == "f5"

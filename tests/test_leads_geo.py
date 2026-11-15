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


def test_geo_summary_counts_fresh_under_24h():
    _insert_lead(external_id="fr1", city="Boston", neighborhood="Dorchester", zip_code="02124")
    _insert_lead(external_id="fr2", city="Boston", neighborhood="Dorchester", zip_code="02124")
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE leads SET created_at = datetime('now', '-48 hours') "
            "WHERE external_id = 'fr2'"
        )
        conn.commit()
    finally:
        conn.close()

    result = db_service._service.get_leads_geo_summary(
        city="Boston", days=7, user_id=5
    )

    assert result["total"] == 2
    group = next(g for g in result["groups"] if g["key"] == "Dorchester")
    assert group["n"] == 2
    assert group["fresh"] == 1


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

    # ZIP só entra na zona quando a linha NÃO tem bairro (espelha o GROUP BY).
    by_zip, total_zip = db_service._service.get_leads_feed(
        city="Boston", zips=["02119", "02128"], days=7, user_id=5
    )
    assert total_zip == 1
    assert {row["external_id"] for row in by_zip} == {"f4"}

    # Zona agregada (bairro + ZIPs sem bairro) tem de bater com a soma exata.
    union, total_union = db_service._service.get_leads_feed(
        city="Boston",
        neighborhoods=["Dorchester"],
        zips=["02124", "02125"],
        days=7,
        user_id=5,
    )
    assert total_union == 2
    assert {row["external_id"] for row in union} == {"f1", "f2"}

    no_geo, total_none = db_service._service.get_leads_feed(
        city="Boston", no_geo=True, days=7, user_id=5
    )
    assert total_none == 1
    assert no_geo[0]["external_id"] == "f5"


def test_geo_summary_matches_feed_with_deadline_owner_layer_and_search():
    _insert_lead(external_id="d1", city="Boston", neighborhood="Dorchester", zip_code="02124")
    _insert_lead(external_id="d2", city="Boston", neighborhood="Dorchester", zip_code="02124")
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE leads SET sla_target_dt = datetime('now', '+2 days'), "
            "owner_name = 'CITY OF BOSTON' WHERE external_id = 'd2'"
        )
        conn.commit()
    finally:
        conn.close()

    summary = db_service._service.get_leads_geo_summary(
        city="Boston", days=7, user_id=5, deadline_only=True
    )
    feed, total = db_service._service.get_leads_feed(
        city="Boston", days=7, user_id=5, deadline_only=True
    )
    assert summary["total"] == total == 1
    assert feed[0]["external_id"] == "d2"

    private_summary = db_service._service.get_leads_geo_summary(
        city="Boston", days=7, user_id=5, owner_type="private"
    )
    private_feed, private_total = db_service._service.get_leads_feed(
        city="Boston", days=7, user_id=5, owner_type="private"
    )
    # d1 não tem proprietário: "private" exige nome e não-institucional.
    assert private_summary["total"] == private_total == 0

    unknown_summary = db_service._service.get_leads_geo_summary(
        city="Boston", days=7, user_id=5, owner_type="unknown"
    )
    assert unknown_summary["total"] == 1

    institutional_summary = db_service._service.get_leads_geo_summary(
        city="Boston", days=7, user_id=5, owner_type="institutional"
    )
    assert institutional_summary["total"] == 1

    search_summary = db_service._service.get_leads_geo_summary(
        city="Boston", days=7, user_id=5, search="street"
    )
    assert search_summary["total"] == 2

    layer_summary = db_service._service.get_leads_geo_summary(
        city="Boston", days=7, user_id=5, layer="permit"
    )
    assert layer_summary["total"] == 0

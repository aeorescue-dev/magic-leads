"""Mapa vivo público: agregação, privacidade, cache e índice parcial."""

from __future__ import annotations

import json

import pytest

from backend.services import public_map
from backend.services.db import get_connection, init_db


def _insert(
    *,
    external_id: str,
    city: str = "Boston",
    state: str | None = None,
    neighborhood: str | None = None,
    zip_code: str | None = "02124",
    category: str = "Roof",
    description: str | None = None,
    lat: float | None = 42.3,
    lng: float | None = -71.0,
    age_hours: int = 0,
    case_status: str = "open",
) -> None:
    state = state or {"Dallas": "TX", "Chicago": "IL", "NYC": "NY"}.get(city, "MA")
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO leads "
            "(external_id, source_type, address, city, state, issue_category, "
            "issue_description, date_reported, created_at, is_feed_ok, "
            "is_qualified, is_junk, case_status, signal_type, signal_status, "
            "lead_status, neighborhood, zip_code, lat, lng, urgency_level) "
            "VALUES (?, 'dev', ?, ?, ?, ?, ?, datetime('now'), "
            "datetime('now', ?), 1, 0, 0, ?, 'open_request', "
            "'open', 'available', ?, ?, ?, ?, 'medium')",
            (
                external_id,
                f"{external_id} Street",
                city,
                state,
                category,
                description,
                f"-{age_hours} hours",
                case_status,
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
    public_map.reset_cache()
    conn = get_connection()
    try:
        conn.execute("DELETE FROM leads")
        conn.commit()
    finally:
        conn.close()
    yield
    public_map.reset_cache()


def _city(payload: dict, label: str) -> dict:
    return next(item for item in payload["cities"] if item["label"] == label)


def test_map_groups_labels_and_applies_privacy_floor():
    for index in range(6):
        _insert(
            external_id=f"d{index}",
            neighborhood="Dorchester",
            zip_code="02124",
        )
    for index in range(3):
        _insert(external_id=f"z{index}", neighborhood=None, zip_code="02124")
    for index in range(2):
        _insert(external_id=f"r{index}", neighborhood="Roxbury", zip_code="02119")
    _insert(external_id="nog", neighborhood=None, zip_code=None)

    payload = public_map.get_live_map()
    boston = _city(payload, "Boston")

    assert boston["totals"]["count"] == 12
    zones = {zone["label"]: zone for zone in boston["zones"]}
    assert zones["Dorchester"]["count"] == 9
    # Piso de privacidade: Roxbury (2) e "Other areas" (1) não aparecem.
    assert "Roxbury" not in zones
    assert boston["totals"]["other"] == 3
    assert all(zone["count"] >= public_map.MIN_ZONE_COUNT for zone in boston["zones"])


def test_map_fresh_requires_three_and_city_total_keeps_all():
    for index in range(5):
        _insert(
            external_id=f"old{index}",
            neighborhood="Dorchester",
            age_hours=48,
        )
    for index in range(2):
        _insert(external_id=f"new{index}", neighborhood="Dorchester")
    for index in range(5):
        _insert(external_id=f"hot{index}", neighborhood="Roxbury", age_hours=48)
    for index in range(3):
        _insert(external_id=f"hotnew{index}", neighborhood="Roxbury")

    boston = _city(public_map.get_live_map(), "Boston")
    zones = {zone["label"]: zone for zone in boston["zones"]}

    assert zones["Dorchester"]["fresh"] == 0  # 2 frescos: abaixo do piso
    assert zones["Roxbury"]["fresh"] == 3
    assert boston["totals"]["fresh"] == 5


def test_map_merges_zip_codes_for_boston_and_nyc():
    for index in range(3):
        _insert(external_id=f"nb{index}", neighborhood="Dorchester", zip_code="02124")
    for index in range(3):
        _insert(external_id=f"zp{index}", neighborhood=None, zip_code="02124")
    for index in range(5):
        _insert(
            external_id=f"bx{index}",
            city="NYC",
            neighborhood="BRONX",
            zip_code="10458",
            state="NY",
        )

    payload = public_map.get_live_map()
    boston = {zone["label"]: zone for zone in _city(payload, "Boston")["zones"]}
    nyc = {zone["label"]: zone for zone in _city(payload, "New York")["zones"]}

    assert boston["Dorchester"]["count"] == 6
    assert nyc["Bronx"]["count"] == 5


def test_map_caps_zones_and_keeps_other_count():
    for index in range(65):
        for repeat in range(5):
            _insert(
                external_id=f"cap{index}-{repeat}",
                neighborhood=f"Zone {index:02d}",
                zip_code="02124",
            )

    boston = _city(public_map.get_live_map(), "Boston")

    assert len(boston["zones"]) == public_map.MAX_ZONES_PER_CITY
    assert boston["totals"]["count"] == 325
    assert boston["totals"]["other"] == 25
    assert boston["totals"]["zones"] == 60


def test_map_payload_has_no_private_fields_and_rounds_coordinates():
    for index in range(6):
        _insert(external_id=f"priv{index}", neighborhood="Dorchester")

    payload = public_map.get_live_map()
    serialized = json.dumps(payload).lower()
    for forbidden in (
        "address",
        "owner",
        "phone",
        "description",
        "external_id",
        "lead_id",
        '"id"',
        "street",
        "bbl",
        "bin",
    ):
        assert forbidden not in serialized, forbidden

    for city in payload["cities"]:
        for zone in city["zones"]:
            if zone["lat"] is not None:
                assert round(zone["lat"], 3) == zone["lat"]
            if zone["lng"] is not None:
                assert round(zone["lng"], 3) == zone["lng"]


def test_map_excludes_unqualified_junk_and_closed():
    for index in range(5):
        _insert(external_id=f"ok{index}", neighborhood="Dorchester")
    for index in range(5):
        _insert(
            external_id=f"bad{index}",
            neighborhood="Roxbury",
            category="Unknown",
        )
    for index in range(5):
        _insert(
            external_id=f"junk{index}",
            neighborhood="Mattapan",
            description="abandoned vehicle",
        )
    for index in range(5):
        _insert(
            external_id=f"closed{index}",
            neighborhood="South End",
            case_status="closed",
        )

    boston = _city(public_map.get_live_map(), "Boston")
    assert boston["totals"]["count"] == 5
    assert [zone["label"] for zone in boston["zones"]] == ["Dorchester"]


def test_map_public_labels_per_city():
    for index in range(5):
        _insert(external_id=f"bos{index}", neighborhood=None, zip_code="02128")
    for index in range(5):
        _insert(
            external_id=f"dal{index}",
            city="Dallas",
            neighborhood=None,
            zip_code="75214",
            state="TX",
        )
    for index in range(5):
        _insert(
            external_id=f"chi{index}",
            city="Chicago",
            neighborhood=None,
            zip_code="60617",
            state="IL",
        )

    payload = public_map.get_live_map()
    labels = {
        city["label"]: [zone["label"] for zone in city["zones"]]
        for city in payload["cities"]
    }
    assert "East Boston" in labels["Boston"]
    assert "East Dallas" in labels["Dallas"]
    assert "Area 60617" in labels["Chicago"]


def test_map_hides_other_areas_and_keeps_count_in_other():
    for index in range(6):
        _insert(
            external_id=f"other{index}",
            neighborhood=None,
            zip_code=None,
        )

    boston = _city(public_map.get_live_map(), "Boston")

    assert boston["totals"]["count"] == 6
    assert boston["totals"]["zones"] == 0
    assert boston["totals"]["other"] == 6
    assert boston["zones"] == []


def test_map_cache_reuses_payload(monkeypatch):
    _insert(external_id="cache1", neighborhood="Dorchester")
    first = public_map.get_live_map()

    def explode():
        raise AssertionError("cache não devia recalcular")

    monkeypatch.setattr(public_map, "_compute", explode)
    second = public_map.get_live_map()
    assert second["generated_at"] == first["generated_at"]

    public_map.reset_cache()
    monkeypatch.undo()
    third = public_map.get_live_map()
    assert third["generated_at"] >= first["generated_at"]


def test_public_map_index_is_partial_and_used():
    init_db()
    conn = get_connection()
    try:
        index = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' "
            "AND name='idx_leads_public_geo'"
        ).fetchone()
        assert index is not None
        sql = index["sql"]
        assert "created_at" in sql
        assert "is_qualified = 1" in sql
        assert "COALESCE(is_junk, 0) = 0" in sql

        # O plano em produção (135k linhas) escolhe este índice; aqui forçamos
        # o uso para provar que a forma exata da query é servida pelo índice
        # parcial sem tocar na tabela (a escolha do planner depende de estatísticas).
        plan = [
            row["detail"]
            for row in conn.execute(
                "EXPLAIN QUERY PLAN "
                "SELECT l.created_at, l.issue_category, l.neighborhood, "
                "l.zip_code, l.lat, l.lng, COUNT(*) "
                "FROM leads l INDEXED BY idx_leads_public_geo "
                "WHERE l.is_qualified = 1 AND COALESCE(l.is_junk, 0) = 0 "
                "AND l.date_reported IS NOT NULL "
                "AND datetime(l.date_reported) >= datetime('now','-7 days') "
                "AND LOWER(COALESCE(l.case_status, '')) NOT IN "
                "('closed','resolved','solved','archived','duplicated') "
                "AND l.issue_category IN ('Roof','Plumbing') "
                "AND l.city COLLATE NOCASE IN ('NYC') "
                "GROUP BY l.neighborhood, l.zip_code"
            )
        ]
    finally:
        conn.close()

    assert any("idx_leads_public_geo" in detail for detail in plan), plan


def test_map_without_data_returns_four_empty_cities():
    payload = public_map.get_live_map()
    assert len(payload["cities"]) == 4
    assert all(city["totals"]["count"] == 0 for city in payload["cities"])

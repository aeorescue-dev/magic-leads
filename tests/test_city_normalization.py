"""Normalização de cidades não pode apagar linhas canónicas."""

from __future__ import annotations

import pytest

from backend.services.db import canonical_city, get_connection, init_db


@pytest.fixture(autouse=True)
def _clean():
    init_db()
    conn = get_connection()
    try:
        conn.execute("DELETE FROM leads")
        conn.commit()
    finally:
        conn.close()
    yield


def _insert(external_id: str, city: str, address: str) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO leads "
            "(external_id, source_type, address, city, state, issue_category, "
            "date_reported, is_feed_ok, signal_type, lead_status) "
            "VALUES (?, 'dev', ?, ?, 'MA', 'Roof', datetime('now'), 1, "
            "'open_request', 'available')",
            (external_id, address, city),
        )
        conn.commit()
    finally:
        conn.close()


def test_canonical_city_variants():
    assert canonical_city("CHICAGO") == "Chicago"
    assert canonical_city("Chicago") == "Chicago"
    assert canonical_city(" new york ") == "NYC"
    assert canonical_city("Brooklyn") == "Brooklyn"
    assert canonical_city("Boston") == "Boston"


def test_init_db_keeps_canonical_rows_and_merges_variants():
    _insert("c1", "Boston", "10 Alpha Street")
    _insert("c2", "Boston", "20 Beta Street")
    _insert("c0", "Chicago", "10 Alpha Street")
    _insert("c3", "CHICAGO", "10 Alpha Street")  # duplicado exato da canónica
    _insert("c4", "CHICAGO", "30 Gamma Street")  # sem duplicado: renomeia

    init_db()

    conn = get_connection()
    try:
        boston = conn.execute(
            "select count(*) c from leads where city='Boston'"
        ).fetchone()["c"]
        chicago = conn.execute(
            "select count(*) c from leads where city='Chicago'"
        ).fetchone()["c"]
        variants = conn.execute(
            "select count(*) c from leads where upper(trim(city))='CHICAGO' "
            "and city <> 'Chicago'"
        ).fetchone()["c"]
        dup = conn.execute(
            "select count(*) c from (select address, city, count(*) n "
            "from leads group by address, city having n > 1)"
        ).fetchone()["c"]
    finally:
        conn.close()

    assert boston == 2, "normalização não pode apagar linhas canónicas"
    assert chicago == 2
    assert variants == 0
    assert dup == 0

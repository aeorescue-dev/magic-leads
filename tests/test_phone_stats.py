"""P2: percentagem de confiança do telefone com >=30 amostras reais."""
from __future__ import annotations

import pytest

from backend.main import (
    PHONE_STATS_MIN_SAMPLES,
    _phone_confidence_stats,
    _phone_stats_cache,
    _to_lead_response,
)
from backend.services.db import db_service, get_connection

CITY = "P2CITY"
CLASS = "p2test"


def _call(outcome: str, *, city: str = CITY, owner_class: str = CLASS, days_ago: int = 1):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO searchbug_calls (called_at, outcome, billed, city, owner_class) "
            "VALUES (datetime('now', ?), ?, 1, ?, ?)",
            (f"-{days_ago} days", outcome, city, owner_class),
        )
        conn.commit()
    finally:
        conn.close()


def _clean():
    conn = get_connection()
    try:
        conn.execute(
            "DELETE FROM searchbug_calls WHERE city = ? OR owner_class = ?", (CITY, CLASS)
        )
        conn.commit()
    finally:
        conn.close()
    _phone_stats_cache.clear()


@pytest.fixture(autouse=True)
def _isolated():
    _clean()
    yield
    _clean()


def test_stats_ignore_cache_guard_and_transport():
    _call("success")
    _call("success")
    _call("no_results")
    _call("name_mismatch")
    # Nao sao tentativas reais de encontrar o numero:
    _call("cache_hit")
    _call("cache_negative")
    _call("guard_skipped")
    _call("transport_error")

    stats = db_service._service.get_phone_success_stats(CITY, CLASS)
    assert stats == {"samples": 4, "successes": 2}


def test_pct_hidden_below_threshold_and_shown_at_threshold():
    for _ in range(9):
        _call("success")
    _call("no_results")

    below = _phone_confidence_stats(CITY, CLASS)
    assert below["pct"] is None
    assert below["samples"] == 10

    # Completa ate' 30 amostras (20 com 10 sucessos): 19/30 = 63%.
    for i in range(20):
        _call("success" if i < 10 else "no_results")

    # A cache de 10 min serve o resultado anterior; limpa-se para simular a
    # passagem do tempo (em producao o numero atualiza sozinho).
    _phone_stats_cache.clear()
    at_threshold = _phone_confidence_stats(CITY, CLASS)
    assert at_threshold["samples"] == PHONE_STATS_MIN_SAMPLES
    assert at_threshold["pct"] == 63
    assert at_threshold["scope"] == "city"


def test_falls_back_to_class_when_city_has_few_samples():
    # 5 amostras na cidade, 30 na classe (outra cidade) -> usa a classe.
    for _ in range(5):
        _call("success")
    for _ in range(24):
        _call("success", city="OTHER-CITY")
    _call("no_results", city="OTHER-CITY")

    stats = _phone_confidence_stats(CITY, CLASS)
    assert stats["samples"] == 30
    assert stats["pct"] == 97  # 29/30
    assert stats["scope"] == "class"


def test_response_exposes_pct_only_with_enough_samples():
    for i in range(30):
        _call("success" if i < 21 else "no_results", owner_class="private")
    _phone_stats_cache.clear()

    lead = {
        "id": 1,
        "external_id": "p2-1",
        "source_type": "311",
        "address": "123 MAIN STREET",
        "city": CITY,
        "state": "NY",
        "zip_code": "11201",
        "issue_category": "Roof",
        "issue_description": "roof leak",
        "date_reported": "2026-10-01T00:00:00",
        "urgency_level": "medium",
        "owner_name": "JOHN SMITH",
        "lead_status": "available",
    }
    resp = _to_lead_response(dict(lead))
    assert resp.phone_success_pct == 70  # 21/30
    assert resp.phone_sample_size == 30

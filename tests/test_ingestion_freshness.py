"""Fase C — frescura de ingestão na Control Tower.

O scraper pode parar em silêncio (mudança de schema, fonte vazia). Este check
classifica a idade do último run concluído e falha quando a captura pára.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.services import control_tower as ct
from backend.services.db import get_connection

PREFIX = "pytest-ct-ing-"


@pytest.fixture(autouse=True)
def clean_runs():
    def _clean() -> None:
        conn = get_connection()
        try:
            conn.execute("DELETE FROM scraper_runs WHERE run_id LIKE ?", (f"{PREFIX}%",))
            conn.commit()
        finally:
            conn.close()

    _clean()
    yield
    _clean()


def _ts(hours_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )


def _insert(
    suffix: str,
    *,
    status: str,
    hours_ago: float = 1.0,
    inserted: int = 10,
    error: str | None = None,
    finished: bool = True,
    started: bool = True,
) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO scraper_runs "
            "(run_id, trigger, started_at, finished_at, status, inserted, total_raw, "
            " cities_covered, error, note) "
            "VALUES (?, 'pytest', ?, ?, ?, ?, 0, 1, ?, NULL)",
            (
                PREFIX + suffix,
                _ts(hours_ago + 0.5) if started else None,
                _ts(hours_ago) if finished else None,
                status,
                inserted,
                error,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def test_recent_run_is_ok():
    _insert("ok", status="success", hours_ago=1)
    check = ct._check_ingestion_freshness()
    assert check["name"] == "ingestion"
    assert check["status"] == "ok", check
    assert "10 inseridos" in check["detail"]


def test_one_missed_window_is_warn():
    _insert("warn", status="success", hours_ago=12)
    check = ct._check_ingestion_freshness()
    assert check["status"] == "warn", check


def test_two_missed_windows_is_fail():
    _insert("fail", status="success", hours_ago=16)
    check = ct._check_ingestion_freshness()
    assert check["status"] == "fail", check


def test_recent_error_after_success_is_fail():
    _insert("old-ok", status="success", hours_ago=2)
    _insert("err", status="error", hours_ago=0.5, error="schema changed")
    check = ct._check_ingestion_freshness()
    assert check["status"] == "fail", check
    assert "schema changed" in check["detail"]


def test_partial_run_counts_as_completed():
    _insert("partial", status="partial", hours_ago=2)
    check = ct._check_ingestion_freshness()
    assert check["status"] == "ok", check
    assert "partial" in check["detail"]


def test_stuck_running_is_warn():
    _insert("stuck", status="running", hours_ago=3, finished=False)
    check = ct._check_ingestion_freshness()
    assert check["status"] == "warn", check
    assert "preso" in check["detail"]


def test_missing_finish_date_is_warn():
    _insert("nodate", status="success", hours_ago=1, finished=False, started=False)
    check = ct._check_ingestion_freshness()
    assert check["status"] == "warn", check
    assert "sem data" in check["detail"]


def test_thresholds_are_configurable(monkeypatch):
    monkeypatch.setenv("SCRAPER_INTERVAL_HOURS", "12")
    warn_h, fail_h = ct._ingestion_thresholds()
    assert warn_h == 21.0
    assert fail_h == 30.0

    monkeypatch.setenv("INGESTION_WARN_HOURS", "4")
    monkeypatch.setenv("INGESTION_FAIL_HOURS", "8")
    assert ct._ingestion_thresholds() == (4.0, 8.0)

"""Regras de cadência e frescura do scraper (P0, auditoria 01/11/2026)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.services import scrape_guard as sg

NOW = datetime(2026, 11, 1, 21, 0, tzinfo=timezone.utc)


def _iso(dt):
    return dt.replace(tzinfo=None).isoformat()


# ------------------------------------------------------------------ cadência
def test_never_ran_fires_immediately():
    assert sg.seconds_until_next_scrape(NOW, None, None, 6) == 0.0


def test_overdue_run_fires_immediately():
    """Deploy reiniciou o processo: o slot vencido não é perdido."""
    last = _iso(NOW - timedelta(hours=8))
    assert sg.seconds_until_next_scrape(NOW, last, last, 6) == 0.0


def test_waits_until_the_slot_not_six_hours_from_boot():
    last = _iso(NOW - timedelta(hours=2))
    delay = sg.seconds_until_next_scrape(
        NOW, last, last, 6, max_wake_seconds=10**6
    )
    assert delay == pytest.approx(4 * 3600)


def test_wakes_at_most_every_fifteen_minutes():
    last = _iso(NOW - timedelta(minutes=5))
    delay = sg.seconds_until_next_scrape(
        NOW, last, last, 6, max_wake_seconds=900
    )
    assert delay == 900


def test_failed_run_retries_after_retry_window():
    last_success = _iso(NOW - timedelta(hours=7))
    last_run = _iso(NOW - timedelta(minutes=5))  # run falhado há 5 min
    delay = sg.seconds_until_next_scrape(
        NOW, last_success, last_run, 6, retry_minutes=30, max_wake_seconds=10**6
    )
    assert delay == pytest.approx(25 * 60)


def test_naive_now_from_utcnow_is_coerced():
    """`utcnow()` devolve naive; a aritmética com datas da BD é aware (UTC)."""
    naive_now = NOW.replace(tzinfo=None)
    last = _iso(NOW - timedelta(hours=2))
    delay = sg.seconds_until_next_scrape(
        naive_now, last, last, 6, max_wake_seconds=10**6
    )
    assert delay == pytest.approx(4 * 3600)
    assert sg.freshness_problems(naive_now, {"NYC": last}, [], interval_hours=6)


# --------------------------------------------------------------- zero streak
def test_zero_insert_streak_counts_consecutive_runs():
    runs = [
        {"status": "success", "inserted": 0},
        {"status": "partial", "inserted": 0},
        {"status": "success", "inserted": 12},
    ]
    assert sg.zero_insert_streak(runs) == 2


def test_zero_insert_streak_stops_at_error_run():
    runs = [
        {"status": "success", "inserted": 0},
        {"status": "error", "inserted": 0},
        {"status": "success", "inserted": 0},
    ]
    assert sg.zero_insert_streak(runs) == 1


# ------------------------------------------------------------ freshness
def test_stale_city_is_flagged_with_age():
    city_last = {
        "NYC": _iso(NOW - timedelta(hours=3)),
        "BOSTON": _iso(NOW - timedelta(hours=30)),
    }
    runs = [{"status": "success", "inserted": 5, "started_at": _iso(NOW - timedelta(hours=1))}]
    problems = sg.freshness_problems(NOW, city_last, runs, interval_hours=6)
    codes = [p["code"] for p in problems]
    assert sg.CODE_CITY_STALE in codes
    stale = [p for p in problems if p["code"] == sg.CODE_CITY_STALE]
    assert len(stale) == 1
    assert stale[0]["city"] == "BOSTON"
    assert stale[0]["context"]["age_hours"] == 30.0


def test_missing_last_date_is_flagged():
    problems = sg.freshness_problems(
        NOW,
        {"DALLAS": None},
        [{"status": "success", "inserted": 3, "started_at": _iso(NOW)}],
        interval_hours=6,
        stale_cities=["DALLAS"],
    )
    assert [p["code"] for p in problems] == [sg.CODE_CITY_STALE]


def test_zero_inserts_and_overdue_are_flagged():
    runs = [
        {"status": "success", "inserted": 0, "started_at": _iso(NOW - timedelta(hours=12))},
        {"status": "success", "inserted": 0, "started_at": _iso(NOW - timedelta(hours=18))},
    ]
    problems = sg.freshness_problems(
        NOW,
        {"NYC": _iso(NOW - timedelta(hours=1))},
        runs,
        interval_hours=6,
        overdue_grace_hours=4.5,
    )
    codes = {p["code"] for p in problems}
    assert sg.CODE_ZERO_INSERTS in codes
    assert sg.CODE_OVERDUE in codes


def test_healthy_pipeline_has_no_problems():
    runs = [
        {"status": "success", "inserted": 21, "started_at": _iso(NOW - timedelta(hours=1))}
    ]
    problems = sg.freshness_problems(
        NOW,
        {"NYC": _iso(NOW - timedelta(hours=1)), "CHICAGO": _iso(NOW - timedelta(hours=2))},
        runs,
        interval_hours=6,
    )
    assert problems == []


# ------------------------------------------------------------------ force
def test_force_only_with_problem_and_cooldown():
    problem = [{"code": sg.CODE_CITY_STALE, "city": "BOSTON"}]
    recent = _iso(NOW - timedelta(minutes=10))
    assert not sg.should_force_collection(NOW, recent, problem, min_hours_between_forces=2)
    old = _iso(NOW - timedelta(hours=3))
    assert sg.should_force_collection(NOW, old, problem, min_hours_between_forces=2)
    assert not sg.should_force_collection(NOW, old, [], min_hours_between_forces=2)

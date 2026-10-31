"""Fase E — higiene de memória e runs presos.

`_scrape_runs` crescia sem limite e `_SESSIONS` era um dicionário morto que
nunca era lido. Runs em `running` sobreviviam a restarts para sempre.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import backend.main as main_module
from backend.services.db import get_connection

PREFIX = "pytest-hygiene-"


def test_scrape_runs_dict_is_pruned_to_cap():
    main_module._scrape_runs.clear()
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for i in range(main_module._MAX_SCRAPE_RUNS + 5):
        main_module._remember_scrape_run(
            {
                "run_id": f"{PREFIX}{i:03d}",
                "started_at": (base + timedelta(minutes=i)).isoformat(),
                "running": False,
            }
        )
    assert len(main_module._scrape_runs) == main_module._MAX_SCRAPE_RUNS
    # O mais antigo saiu; o mais recente ficou.
    assert f"{PREFIX}000" not in main_module._scrape_runs
    assert f"{PREFIX}{main_module._MAX_SCRAPE_RUNS + 4:03d}" in main_module._scrape_runs
    main_module._scrape_runs.clear()


def test_scrape_runs_ignores_state_without_run_id():
    main_module._scrape_runs.clear()
    main_module._remember_scrape_run({"running": True})
    assert main_module._scrape_runs == {}


def _insert_run(suffix: str, *, status: str, started_hours_ago: float) -> None:
    started = (datetime.now(timezone.utc) - timedelta(hours=started_hours_ago)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO scraper_runs "
            "(run_id, trigger, started_at, finished_at, status, inserted, total_raw, "
            " cities_covered, error, note) "
            "VALUES (?, 'pytest', ?, NULL, ?, 0, 0, 0, NULL, NULL)",
            (PREFIX + suffix, started, status),
        )
        conn.commit()
    finally:
        conn.close()


def test_mark_stale_runs_closes_only_old_running():
    stale_id = PREFIX + "stale"
    fresh_id = PREFIX + "fresh"
    conn = get_connection()
    try:
        conn.execute("DELETE FROM scraper_runs WHERE run_id LIKE ?", (f"{PREFIX}%",))
        conn.commit()
    finally:
        conn.close()

    _insert_run("stale", status="running", started_hours_ago=4)
    _insert_run("fresh", status="running", started_hours_ago=0.5)

    closed = main_module.db_service._service.mark_stale_scraper_runs(180)
    assert closed >= 1

    conn = get_connection()
    try:
        rows = {
            r["run_id"]: dict(r)
            for r in conn.execute(
                "SELECT * FROM scraper_runs WHERE run_id IN (?, ?)", (stale_id, fresh_id)
            ).fetchall()
        }
    finally:
        conn.close()

    assert rows[stale_id]["status"] == "error"
    assert rows[stale_id]["finished_at"] is not None
    assert rows[fresh_id]["status"] == "running"

    conn = get_connection()
    try:
        conn.execute("DELETE FROM scraper_runs WHERE run_id LIKE ?", (f"{PREFIX}%",))
        conn.commit()
    finally:
        conn.close()


def test_legacy_sessions_dict_is_gone():
    assert not hasattr(main_module, "_SESSIONS")

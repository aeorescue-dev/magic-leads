"""Deploy a meio de um run não pode deixar o scheduler preso num 'running'."""
from __future__ import annotations

from backend.services.db import db_service, get_connection


def test_mark_interrupted_scraper_runs():
    svc = db_service._service
    conn = get_connection()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO scraper_runs "
            "(run_id, trigger, status, started_at, inserted, total_raw) "
            "VALUES ('pytest-interrupted-run', 'scheduler', 'running', "
            "'2026-11-02T15:43:08', 0, 0)"
        )
        conn.commit()
    finally:
        conn.close()

    closed = svc.mark_interrupted_scraper_runs()
    assert closed >= 1

    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT status, error FROM scraper_runs WHERE run_id='pytest-interrupted-run'"
        ).fetchone()
        assert row["status"] == "error"
        assert "interrompido" in row["error"].lower()
        alert = conn.execute(
            "SELECT code FROM system_alerts WHERE code='SCRAPER_INTERRUPTED' "
            "AND message LIKE '%pytest-interrupted-run%' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        assert alert is not None
        conn.execute(
            "DELETE FROM scraper_runs WHERE run_id='pytest-interrupted-run'"
        )
        conn.commit()
    finally:
        conn.close()

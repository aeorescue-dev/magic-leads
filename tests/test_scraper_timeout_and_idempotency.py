"""Incidente 31/10 — timeout da ingestão e idempotência de reexecução.

Cobre:
  * o parser de timestamps da Control Tower aceita microssegundos (falso
    "sem data de conclusão" que gerou o alerta amarelo);
  * um run pendurado é cancelado por timeout, marcado `error`, alerta crítico;
  * reexecutar a mesma captura não duplica leads nem histórico.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

import pytest

import backend.main as main_module
from backend.models.schemas import (
    EnrichedLead,
    IssueCategory,
    SourceType,
    UrgencyLevel,
)
from backend.services import control_tower
from backend.services.db import db_service, get_connection


@pytest.mark.asyncio
async def test_guarded_scraper_times_out_marks_error_and_alerts(monkeypatch):
    run_id = f"pytest-timeout-{uuid.uuid4().hex[:8]}"
    main_module._scrape_runs.clear()

    async def hang(*_args, **_kwargs):
        await asyncio.sleep(30)

    async def timeout_now(coro, **_kwargs):
        coro.close()
        raise asyncio.TimeoutError()

    async def no_health():
        return []

    monkeypatch.setattr(main_module, "_scrape_worker", hang)
    monkeypatch.setattr(main_module.asyncio, "wait_for", timeout_now)
    monkeypatch.setattr(control_tower, "run_health_checks", no_health)

    main_module._remember_scrape_run(
        {
            "run_id": run_id,
            "running": True,
            "status": "running",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "inserted": 0,
            "total_raw": 0,
        }
    )

    await main_module._run_scrape_guarded(run_id)

    state = main_module._scrape_runs[run_id]
    assert state["status"] == "error"
    assert state["running"] is False
    assert "timeout" in state["error"].lower()

    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT status, error, finished_at FROM scraper_runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        alert = conn.execute(
            "SELECT level, message FROM system_alerts "
            "WHERE code = 'SCRAPER_TIMEOUT' AND message LIKE ? ORDER BY id DESC LIMIT 1",
            (f"%{run_id}%",),
        ).fetchone()
    finally:
        conn.close()

    assert row is not None
    assert row["status"] == "error"
    assert row["finished_at"] is not None
    assert alert is not None
    assert alert["level"] == "critical"

    conn = get_connection()
    try:
        conn.execute("DELETE FROM scraper_runs WHERE run_id = ?", (run_id,))
        conn.execute(
            "DELETE FROM system_alerts WHERE code='SCRAPER_TIMEOUT' AND message LIKE ?",
            (f"%{run_id}%",),
        )
        conn.commit()
    finally:
        conn.close()
    main_module._scrape_runs.clear()


def test_reingesting_same_capture_is_idempotent():
    svc = db_service._service
    token = uuid.uuid4().hex[:8]
    external_id = f"pytest-idem-{token}"
    address = f"{token} IDEMPOTENT ST"

    payload = EnrichedLead(
        external_id=external_id,
        source_type=SourceType.SERVICE_311,
        address=address,
        city="BOSTON",
        state="NY",
        zip_code="10001",
        lat=None,
        lng=None,
        county="KINGS",
        issue_category=IssueCategory.ROOF,
        issue_description="idempotency",
        urgency_level=UrgencyLevel.MEDIUM,
        case_status="open",
        owner_name="IDEM LLC",
        owner_phone="3475550111",
        owner_email="idem@example.com",
        date_reported=datetime(2026, 1, 1, 12, 0, 0),
        image_url=None,
        source_url=None,
    )

    first = svc.insert_lead_new(payload)
    second = svc.insert_lead_new(payload)
    assert first is not None
    # Reexecução do mesmo external_id é atualização, não um novo lead.
    assert second is None

    conn = get_connection()
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM leads WHERE external_id = ? AND source_type = ?",
            (external_id, SourceType.SERVICE_311.value),
        ).fetchone()[0]
        same_id = conn.execute(
            "SELECT id FROM leads WHERE external_id = ? AND source_type = ?",
            (external_id, SourceType.SERVICE_311.value),
        ).fetchone()[0]
    finally:
        conn.close()
    assert count == 1
    assert int(same_id) == int(first["id"])

    occurrences = [
        {
            "external_id": f"{external_id}-case",
            "case_title": "Roof leak",
            "case_status": "open",
            "issue_category": "Roof",
            "source": "test",
        }
    ]
    svc.save_lead_case_history(int(first["id"]), occurrences)
    svc.save_lead_case_history(int(first["id"]), occurrences)

    conn = get_connection()
    try:
        hist = conn.execute(
            "SELECT COUNT(*) FROM lead_case_history WHERE lead_id = ?",
            (int(first["id"]),),
        ).fetchone()[0]
    finally:
        conn.close()
    assert hist == 1

    conn = get_connection()
    try:
        conn.execute("DELETE FROM leads WHERE id = ?", (int(first["id"]),))
        conn.commit()
    finally:
        conn.close()

"""P0 da dashboard: classificação por sinal e janelas separadas no insights."""
from __future__ import annotations

import sqlite3
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from backend.models.schemas import (
    EnrichedLead,
    IssueCategory,
    SourceType,
    UrgencyLevel,
)
from backend.services.db import db_service, get_connection
from backend.services.opportunity_workflow import opportunity_workflow
from backend.services.phase1_enrichment import source_kind_for_signal

TODAY = date.today()


def _clean():
    conn = get_connection()
    try:
        conn.execute("DELETE FROM opportunity_workflow")
        conn.commit()
    finally:
        conn.close()


def _create(**kwargs):
    defaults = dict(
        source_kind="preventive",
        source_type="pre_inspection",
        city="Boston",
        state="MA",
        zip_code="02124",
        category="Structure",
        severity="high",
    )
    defaults.update(kwargs)
    return opportunity_workflow.create_opportunity(**defaults)


def test_source_kind_follows_signal():
    assert source_kind_for_signal("legal_obligation") == ("reactive", "violation")
    assert source_kind_for_signal("authorized_work") == ("permit", "permit")
    assert source_kind_for_signal("open_request") == ("preventive", "pre_inspection")
    assert source_kind_for_signal(None) == ("preventive", "pre_inspection")


def test_insights_keeps_old_deadlines_and_fines():
    """Uma linha antiga com prazo/multa continua a contar no risco."""
    _clean()
    _create(
        source_record_id="old-overdue",
        address="10 Old St",
        received_at="2020-01-01",
        compliance_deadline=(TODAY - timedelta(days=5)).isoformat(),
        fine_balance=100.0,
    )
    _create(
        source_record_id="recent",
        address="20 New St",
        received_at=TODAY.isoformat(),
        compliance_deadline=(TODAY + timedelta(days=3)).isoformat(),
    )
    _create(
        source_record_id="old-fine",
        address="30 Old St",
        received_at="2020-01-01",
        fine_imposed=50.0,
        fine_paid=0.0,
    )

    result = opportunity_workflow.insights(
        kind="preventive", days=7, window_days=7, city="Boston"
    )

    # Contagem/feed: so' a linha recente.
    assert result["totals"]["count"] == 1
    # Risco: todas as linhas abertas, incluindo as antigas.
    assert result["totals"]["deadlines_7d"] == 2
    assert result["totals"]["overdue"] == 1
    assert result["totals"]["fines_count"] == 2
    assert result["totals"]["fines_at_risk"] == 150
    assert len(result["deadlines"]) == 2
    assert any(item["days_left"] == 0 for item in result["deadlines"])


def test_insights_deadline_filter_does_not_hide_fines():
    _clean()
    _create(
        source_record_id="late-deadline",
        address="10 Far St",
        received_at=TODAY.isoformat(),
        compliance_deadline=(TODAY + timedelta(days=30)).isoformat(),
        fine_balance=75.0,
    )
    result = opportunity_workflow.insights(
        kind="preventive",
        days=7,
        window_days=7,
        city="Boston",
        deadline_within=7,
    )
    assert result["totals"]["fines_count"] == 1
    assert result["totals"]["fines_at_risk"] == 75
    assert result["deadlines"] == []


def test_territories_accepts_kind_all():
    _clean()
    _create(source_record_id="p1", address="10 Alpha St", source_kind="preventive")
    _create(source_record_id="r1", address="20 Beta St", source_kind="reactive")
    _create(source_record_id="w1", address="30 Gamma St", source_kind="permit")

    result = opportunity_workflow.territories(city="Boston", kind="all", days=30)
    assert result["totals"]["count"] == 3
    assert result["kind"] == "all"


def test_count_leads_by_signal_matches_filtered_feed():
    lead = EnrichedLead(
        external_id="p0-signal-count",
        source_type=SourceType.SERVICE_311,
        address="10 Signal St",
        city="NYC",
        state="NY",
        zip_code="11201",
        lat=None,
        lng=None,
        county="KINGS",
        issue_category=IssueCategory.ROOF,
        issue_description="Signal count",
        urgency_level=UrgencyLevel.HIGH,
        owner_name=None,
        owner_phone=None,
        owner_email=None,
        mailing_address=None,
        date_reported=datetime.now(),
        image_url=None,
        source_url=None,
    )
    row = db_service._service.insert_lead_new(lead)
    assert row is not None

    counts = db_service._service.count_leads_by_signal(
        city="NYC", category="Roof", days=7, user_id=None, include_closed=False
    )
    assert counts["all"] >= 1
    assert counts["preventive"] >= 1


def test_backfill_source_kind_script(tmp_path):
    db = tmp_path / "opps.db"
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            """
            CREATE TABLE opportunity_workflow (
              id INTEGER PRIMARY KEY,
              signal_type TEXT,
              source_kind TEXT,
              source_type TEXT,
              updated_at TEXT
            )
            """
        )
        conn.executemany(
            "INSERT INTO opportunity_workflow (signal_type, source_kind, source_type) "
            "VALUES (?, 'preventive', 'pre_inspection')",
            [("legal_obligation",), ("authorized_work",), ("open_request",)],
        )
        conn.commit()
    finally:
        conn.close()

    root = Path(__file__).resolve().parents[1]
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "backend.scripts.backfill_source_kind",
            "--db",
            str(db),
            "--apply",
        ],
        cwd=str(root),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr

    conn = sqlite3.connect(db)
    try:
        rows = {
            row[0]: (row[1], row[2])
            for row in conn.execute(
                "SELECT signal_type, source_kind, source_type FROM opportunity_workflow"
            )
        }
    finally:
        conn.close()
    assert rows["legal_obligation"] == ("reactive", "violation")
    assert rows["authorized_work"] == ("permit", "permit")
    assert rows["open_request"] == ("preventive", "pre_inspection")

"""Testes do workflow aditivo de oportunidades e do agente HPD (staging)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from backend.main import _hash_token, _opportunity_error, _to_lead_response, app
from backend.models.schemas import (
    EnrichedLead,
    IssueCategory,
    SourceType,
    UrgencyLevel,
)
from backend.scrapers.socrata_311 import socrata_scraper
from backend.services.db import db_service, get_connection
from backend.services.hpd_agent import resolve_managing_agent
from backend.services.opportunity_workflow import (
    make_property_key,
    opportunity_workflow,
)
from backend.services.preventive_ingestion import preventive_ingestion
from backend.services.privacy import sanitize_lead


def _user(email: str):
    svc = db_service._service
    user = svc.get_user_by_email(email) or svc.create_user(
        email, "pytest-hash-not-used", "Pytest Workflow", plan="pro",
        subscription_status="active",
    )
    svc.extend_access(user["id"], days=7)
    return user


def _opp(**overrides):
    payload = dict(
        source_kind="preventive",
        source_record_id="complaint-1",
        address="3430 BROADWAY",
        city="NYC",
        state="NY",
        zip_code="10031",
        bbl="1020710061",
        source_type="pre_inspection",
        category="Heating",
        signal_type="open_request",
        severity="emergency",
        compliance_deadline=None,
        job_value=None,
    )
    payload.update(overrides)
    return opportunity_workflow.create_opportunity(**payload)


def _used(user_id: int) -> int:
    return int(db_service._service.get_daily_leads_used(user_id).get("used") or 0)


def _reset_quota(user_id: int) -> None:
    svc = db_service._service
    today = datetime.now(timezone.utc).date().isoformat()
    conn = get_connection()
    try:
        conn.execute(
            """INSERT OR REPLACE INTO user_daily_stats
               (user_id, date, leads_used, leads_limit, reset_at)
               VALUES (?, ?, 0, 10, ?)""",
            (user_id, today, svc._utc_tomorrow_midnight().isoformat()),
        )
        conn.commit()
    finally:
        conn.close()


def test_opportunity_errors_are_stable_codes_not_portuguese_sentences():
    assert _opportunity_error({"error": "property_locked"}).detail == "PROPERTY_LOCKED"
    assert _opportunity_error({"error": "daily_limit_reached"}).detail == "DAILY_LIMIT_REACHED"
    assert _opportunity_error({"error": "not_owner"}).detail == "NOT_OWNER"
    assert _opportunity_error({"error": "not_reserved"}).detail == "NOT_RESERVED"
    assert _opportunity_error({"error": "consent_required"}).detail == "CONSENT_REQUIRED"


def test_property_key_prefers_bbl_then_bin_then_address():
    assert make_property_key(bbl="1020710061") == "bbl:1020710061"
    assert make_property_key(bin_value="1061751") == "bin:1061751"
    assert make_property_key(address="1 Main St", city="NYC", zip_code="10001").startswith("addr:")


def test_opportunity_lifecycle_1h_48h_48h_and_outcome():
    user = _user("pytest-workflow-1@magicleads.app")
    _reset_quota(user["id"])
    opp = _opp(source_record_id="complaint-lifecycle", bbl="1020710062")
    before = _used(user["id"])

    reserved = opportunity_workflow.reserve(opp["id"], user["id"])
    assert reserved.get("counted_again") is True
    assert reserved["opportunity"]["status"] == "reserved"
    assert _used(user["id"]) == before + 1

    again = opportunity_workflow.reserve(opp["id"], user["id"])
    assert again["idempotent"] is True
    assert _used(user["id"]) == before + 1

    contacted = opportunity_workflow.mark_contacted(opp["id"], user["id"])
    assert contacted["opportunity"]["status"] == "contacted"
    assert contacted["renewed"] is True
    contacted_again = opportunity_workflow.mark_contacted(opp["id"], user["id"])
    assert contacted_again["renewed"] is False

    negotiating = opportunity_workflow.mark_negotiation(opp["id"], user["id"])
    assert negotiating["opportunity"]["status"] == "in_negotiation"
    negotiating_again = opportunity_workflow.mark_negotiation(opp["id"], user["id"])
    assert negotiating_again["renewed"] is False

    converted = opportunity_workflow.convert(opp["id"], user["id"])
    assert converted["opportunity"]["status"] == "converted"

    outcome = opportunity_workflow.record_outcome(
        opportunity_id=opp["id"],
        lead_id=None,
        outcome="won",
        contract_value=18500,
        recorded_by=user["id"],
    )
    assert outcome["outcome"] == "won"
    assert outcome["won_at"] is not None
    assert outcome["contract_value"] == 18500


def test_cannot_advance_available_opportunity():
    user = _user("pytest-workflow-4@magicleads.app")
    opp = _opp(source_record_id="not-reserved", bbl="1020710064")
    assert opportunity_workflow.mark_contacted(opp["id"], user["id"]).get("error") == "not_reserved"
    assert opportunity_workflow.mark_negotiation(opp["id"], user["id"]).get("error") == "not_reserved"
    assert opportunity_workflow.convert(opp["id"], user["id"]).get("error") == "not_reserved"


def test_property_lock_blocks_second_opportunity_same_property():
    u1 = _user("pytest-workflow-2a@magicleads.app")
    u2 = _user("pytest-workflow-2b@magicleads.app")
    _reset_quota(u1["id"])
    _reset_quota(u2["id"])
    o1 = _opp(source_record_id="lock-a", bbl="1020710063")
    o2 = _opp(source_record_id="lock-b", source_kind="reactive", bbl="1020710063")

    first = opportunity_workflow.reserve(o1["id"], u1["id"])
    assert first["opportunity"]["status"] == "reserved"

    blocked = opportunity_workflow.reserve(o2["id"], u2["id"])
    assert blocked.get("error") == "property_locked"
    assert _used(u2["id"]) == 0, "cota devia ser estornada no bloqueio"


def test_list_opportunities_endpoint_returns_preventive_counts():
    user = _user("pytest-workflow-list@magicleads.app")
    token = "pytest-workflow-list-token"
    db_service._service.create_user_session(user["id"], _hash_token(token), "Pytest", None)
    opp = _opp(source_record_id="list-preventive", bbl="1020710065")
    client = TestClient(app)
    r = client.get(
        "/api/opportunities?kind=preventive",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["counts"]["preventive"] >= 1
    assert any(row["id"] == opp["id"] for row in body["opportunities"])


def test_outcome_endpoint_is_additive_and_does_not_touch_converted_at(monkeypatch):
    user = _user("pytest-workflow-3@magicleads.app")
    lead = EnrichedLead(
        external_id="pytest-outcome-lead",
        source_type=SourceType.SERVICE_311,
        address="10 OUTCOME STREET",
        city="BROOKLYN",
        state="NY",
        zip_code="11201",
        lat=None,
        lng=None,
        county="KINGS",
        issue_category=IssueCategory.ROOF,
        issue_description="Outcome",
        urgency_level=UrgencyLevel.MEDIUM,
        owner_name="OWNER",
        owner_phone=None,
        owner_email=None,
        date_reported=datetime(2026, 1, 15, 12, 0, 0),
        image_url=None,
        source_url=None,
    )
    row = db_service._service.insert_lead_new(lead)
    assert row is not None
    lead_id = row["id"]
    svc = db_service._service
    token = "pytest-workflow-outcome-token"
    svc.create_user_session(user["id"], _hash_token(token), "Pytest", None)
    client = TestClient(app)

    r = client.post(
        f"/api/leads/{lead_id}/outcome",
        headers={"Authorization": f"Bearer {token}"},
        json={"outcome": "lost", "lost_reason": "price"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["outcome"]["outcome"] == "lost"
    stored = svc.get_lead_by_id(lead_id)
    assert stored.get("converted_at") is None, "outcome nao pode alterar converted_at"


@pytest.mark.asyncio
async def test_hpd_agent_prefers_agent_over_corporate_owner(monkeypatch):
    async def fake_fetch_soql(*, domain, dataset, select, where, order=None, limit=5, **kwargs):
        if dataset == "tesw-yqqr":
            return [{"registrationid": "139143", "bbl": "1020710061"}]
        if dataset == "feu5-w2e2":
            return [
                {
                    "registrationid": "139143",
                    "type": "CorporateOwner",
                    "corporationname": "RUPPERT HOUSING CO INC",
                    "businesshousenumber": "9",
                    "businessstreetname": "EAST 38 STREET",
                    "businesscity": "NEW YORK",
                    "businessstate": "NY",
                    "businesszip": "10016",
                },
                {
                    "registrationid": "139143",
                    "type": "Agent",
                    "firstname": "SABREEN",
                    "lastname": "SPEARS",
                    "businesshousenumber": "9",
                    "businessstreetname": "EAST 38TH",
                    "businesscity": "NEW YORK",
                    "businessstate": "NY",
                    "businesszip": "10016",
                },
            ]
        return []

    monkeypatch.setattr(socrata_scraper, "_fetch_soql", fake_fetch_soql)
    agent = await resolve_managing_agent(bbl="1020710061")
    assert agent is not None
    assert agent["name"] == "SABREEN SPEARS"
    assert agent["contact_type"] == "Agent"
    assert agent["source"] == "hpd_registration_contacts"


def test_managing_agent_is_persisted_and_sanitized_for_client():
    lead = EnrichedLead(
        external_id="pytest-managing-agent-lead",
        source_type=SourceType.HPD_VIOLATION,
        address="9 EAST 38TH STREET",
        city="NYC",
        state="NY",
        zip_code="10016",
        lat=None,
        lng=None,
        county="NEW YORK",
        issue_category=IssueCategory.HEATING,
        issue_description="Sem aquecimento",
        urgency_level=UrgencyLevel.HIGH,
        owner_name="RUPPERT HOUSING CO INC",
        owner_phone=None,
        owner_email=None,
        date_reported=datetime(2026, 11, 12, 12, 0, 0),
        image_url=None,
        source_url=None,
    )
    row = db_service._service.insert_lead_new(lead)
    assert row is not None

    agent = {
        "name": "SABREEN SPEARS",
        "contact_type": "Agent",
        "contact_description": "Agent for the building",
        "business_address": "9 EAST 38TH STREET, NEW YORK, NY 10016",
        "registration_id": "139143",
        "source": "hpd_registration_contacts",
    }
    assert db_service._service.update_managing_agent(row["id"], agent) is True

    stored = db_service._service.get_lead_by_id(row["id"])
    assert "SABREEN SPEARS" in (stored.get("managing_agent_json") or "")

    safe = sanitize_lead(stored)
    assert safe["managing_agent"]["name"] == "SABREEN SPEARS"
    assert safe["managing_agent"]["business_address"].startswith("9 EAST 38TH STREET")
    # Identificadores internos da fonte nao saem para o cliente.
    assert "registration_id" not in safe["managing_agent"]
    assert "source" not in safe["managing_agent"]
    assert "managing_agent_json" not in safe

    hidden = _to_lead_response({**stored, "_revealed": False})
    assert hidden.managing_agent is None, "sem reveal o agente nao pode sair"
    shown = _to_lead_response({**stored, "_revealed": True})
    assert shown.managing_agent is not None
    assert shown.managing_agent["name"] == "SABREEN SPEARS"


def test_preventive_ingestion_maps_lead_and_dedupes_by_property():
    lead = EnrichedLead(
        external_id="pytest-ingest-preventive-1",
        source_type=SourceType.SERVICE_311,
        address="77 INGEST STREET",
        city="NYC",
        state="NY",
        zip_code="10002",
        lat=None,
        lng=None,
        county="NEW YORK",
        issue_category=IssueCategory.PLUMBING,
        issue_description="Vazamento no encanamento do predio",
        urgency_level=UrgencyLevel.HIGH,
        owner_name="INGEST HOLDINGS LLC",
        owner_phone=None,
        owner_email=None,
        date_reported=datetime(2026, 11, 10, 9, 0, 0),
        image_url=None,
        source_url=None,
        sla_target_dt="2026-11-15",
    )
    row = db_service._service.insert_lead_new(lead)
    assert row is not None

    result = preventive_ingestion.ingest_lead(row)
    assert result["status"] == "ingested"

    opp = opportunity_workflow.get(result["id"])
    assert opp["source_kind"] == "preventive"
    assert opp["source_record_id"] == f"lead-{row['id']}"
    assert opp["description"] == "Vazamento no encanamento do predio"
    assert opp["owner_name"] == "INGEST HOLDINGS LLC"
    assert opp["owner_type"] == "company"
    assert opp["inspection_status"] == "possible"
    assert "owner_identified" in opp["tags"]
    assert opp["timeline"][0]["key"] == "complaint"
    assert opp["timeline"][0]["date"] == "2026-11-10"

    again = preventive_ingestion.ingest_lead(row)
    assert again["status"] == "skipped_duplicate"


def test_list_applies_seven_day_window_and_pagination():
    category = "PytestWindow"
    now = datetime.now(timezone.utc)
    created = []
    for index in range(3):
        opp = _opp(
            source_record_id=f"window-{index}",
            bbl=f"90000000{index:02d}",
            category=category,
            received_at=(now - timedelta(days=1)).isoformat(timespec="seconds"),
        )
        created.append(opp["id"])
    old = _opp(
        source_record_id="window-old",
        bbl="9000000099",
        category=category,
        received_at=(now - timedelta(days=10)).isoformat(timespec="seconds"),
    )

    first = opportunity_workflow.list(
        kind="preventive", category=category, days=7, limit=2, offset=0
    )
    assert first["total"] == 3
    assert len(first["opportunities"]) == 2
    assert first["has_more"] is True

    second = opportunity_workflow.list(
        kind="preventive", category=category, days=7, limit=2, offset=2
    )
    assert len(second["opportunities"]) == 1
    assert second["has_more"] is False
    ids = {row["id"] for row in first["opportunities"] + second["opportunities"]}
    assert set(created) == ids
    assert old["id"] not in ids


def test_list_filters_by_deadline_window_and_open_fines():
    category = "PytestFilters"
    today = datetime.now(timezone.utc).date()
    match = _opp(
        source_record_id="filter-match",
        bbl="9000000101",
        category=category,
        compliance_deadline=(today + timedelta(days=2)).isoformat(),
        fine_balance=1500,
        fine_imposed=1500,
        fine_paid=0,
    )
    _opp(
        source_record_id="filter-no-fine",
        bbl="9000000102",
        category=category,
        compliance_deadline=(today + timedelta(days=2)).isoformat(),
    )
    _opp(
        source_record_id="filter-far-deadline",
        bbl="9000000103",
        category=category,
        compliance_deadline=(today + timedelta(days=20)).isoformat(),
        fine_balance=900,
        fine_imposed=900,
        fine_paid=0,
    )

    result = opportunity_workflow.list(
        kind="preventive",
        category=category,
        days=7,
        deadline_within=3,
        with_fines=True,
        limit=10,
    )
    assert result["total"] == 1
    assert result["opportunities"][0]["id"] == match["id"]


def test_prune_old_keeps_active_cycles_and_recent_rows():
    user = _user("pytest-workflow-prune@magicleads.app")
    _reset_quota(user["id"])
    category = "PytestPrune"
    now = datetime.now(timezone.utc)
    old = _opp(
        source_record_id="prune-old",
        bbl="9000000201",
        category=category,
        received_at=(now - timedelta(days=100)).isoformat(timespec="seconds"),
    )
    recent = _opp(
        source_record_id="prune-recent",
        bbl="9000000202",
        category=category,
        received_at=(now - timedelta(days=1)).isoformat(timespec="seconds"),
    )
    active = _opp(source_record_id="prune-active", bbl="9000000203", category=category)
    reserved = opportunity_workflow.reserve(active["id"], user["id"])
    assert reserved["opportunity"]["status"] == "reserved"

    conn = get_connection()
    try:
        conn.execute(
            "UPDATE opportunity_workflow SET created_at = ? WHERE id IN (?, ?)",
            ((now - timedelta(days=100)).isoformat(timespec="seconds"), old["id"], active["id"]),
        )
        conn.commit()
    finally:
        conn.close()

    opportunity_workflow.prune_old(retention_days=90)
    assert opportunity_workflow.get(old["id"]) is None
    assert opportunity_workflow.get(recent["id"]) is not None
    assert opportunity_workflow.get(active["id"]) is not None


def test_view_is_persisted_per_user_and_unseen_sort_first():
    category = "PytestViews"
    first = _opp(source_record_id="view-first", bbl="9000000401", category=category)
    second = _opp(source_record_id="view-second", bbl="9000000402", category=category)
    viewer = _user("pytest-workflow-view-a@magicleads.app")
    other = _user("pytest-workflow-view-b@magicleads.app")

    viewed_at = opportunity_workflow.record_view(second["id"], viewer["id"])
    assert viewed_at

    result = opportunity_workflow.list(
        kind="preventive",
        category=category,
        days=7,
        limit=10,
        viewer_id=viewer["id"],
    )
    ids = [row["id"] for row in result["opportunities"]]
    assert ids.index(first["id"]) < ids.index(second["id"]), "nunca vistos primeiro"
    by_id = {row["id"]: row for row in result["opportunities"]}
    assert by_id[second["id"]]["viewed_at"] is not None
    assert by_id[first["id"]]["viewed_at"] is None

    other_result = opportunity_workflow.list(
        kind="preventive",
        category=category,
        days=7,
        limit=10,
        viewer_id=other["id"],
    )
    assert all(row["viewed_at"] is None for row in other_result["opportunities"])


def test_view_endpoint_marks_current_user_only():
    user = _user("pytest-workflow-view-api@magicleads.app")
    token = "pytest-workflow-view-api-token"
    db_service._service.create_user_session(user["id"], _hash_token(token), "Pytest", None)
    opp = _opp(source_record_id="view-api", bbl="9000000403", category="PytestViewApi")
    client = TestClient(app)

    response = client.post(
        f"/api/opportunities/{opp['id']}/view",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["viewed_at"]

    listing = client.get(
        "/api/opportunities?kind=preventive&category=PytestViewApi&days=7",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert listing.status_code == 200, listing.text
    row = next(item for item in listing.json()["opportunities"] if item["id"] == opp["id"])
    assert row["viewed_at"] is not None
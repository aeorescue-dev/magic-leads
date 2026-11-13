"""Testes do workflow aditivo de oportunidades e do agente HPD (staging)."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from backend.main import _hash_token, app
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

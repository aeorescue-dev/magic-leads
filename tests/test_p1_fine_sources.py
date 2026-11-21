"""P1: fontes de multa de Chicago/Boston, 311 Chicago e source_payload."""
from __future__ import annotations

from datetime import date, timedelta

from backend.services import phase1_enrichment as pe
from backend.services.db import get_connection
from backend.services.opportunity_workflow import opportunity_workflow


def test_chicago_311_maps_open_request(monkeypatch):
    monkeypatch.setattr(
        pe,
        "socrata",
        lambda name, params: [
            {
                "sr_number": "SR-1",
                "created_date": "2026-11-18T10:00:00.000",
                "sr_type": "Rodent",
                "street_address": "123 N MAIN ST",
                "zip_code": "60601",
                "status": "Open",
            }
        ],
    )
    items = pe.phase1_enrichment.fetch_chicago_311(limit=10)
    assert len(items) == 1
    item = items[0]
    assert item["signal_type"] == "open_request"
    assert item["city"] == "Chicago"
    assert item["compliance_deadline"] is None
    assert item["source_payload"][0]["source"] == "chi_311"
    assert item["source_payload"][0]["row"]["sr_number"] == "SR-1"


def test_chicago_fines_map_imposed_and_balance(monkeypatch):
    monkeypatch.setattr(pe, "resolve_chicago_zip", lambda **kw: ("60601", "coords"))

    def fake_socrata(name, params):
        if name == "chi_ordinance_fines":
            return [
                {
                    "address": "6839 S JEFFERY BLVD",
                    "imposed_fine": "1000",
                    "hearing_date": "2022-03-02T00:00:00.000",
                    "violation_date": "2021-12-14T09:00:00.000",
                    "violation_description": "Restore exit lighting",
                    "id": "ord-1",
                }
            ]
        if name == "chi_vacant_fines":
            return [
                {
                    "property_address": "2107 N SAWYER",
                    "total_fines": "100",
                    "current_amount_due": "-140",
                    "total_paid": "280",
                    "last_hearing_date": "2011-07-01T14:30:00.000",
                    "issued_date": "2011-06-01T00:00:00.000",
                    "violation_type": "Duty to secure",
                    "violation_number": "P002513827",
                }
            ]
        return []

    monkeypatch.setattr(pe, "socrata", fake_socrata)
    items = pe.phase1_enrichment.fetch_chicago_fines(limit=10)
    by_address = {item["address"]: item for item in items}

    ordinance = by_address["6839 S JEFFERY BLVD"]
    assert ordinance["fine_imposed"] == 1000
    assert ordinance["fine_balance"] == 1000
    assert ordinance["hearing_date"] == "2022-03-02"
    assert ordinance["compliance_deadline"] is None
    assert ordinance["source_payload"][0]["source"] == "chi_ordinance_fines"

    vacant = by_address["2107 N SAWYER"]
    assert vacant["fine_imposed"] == 100
    assert vacant["fine_paid"] == 280
    assert vacant["fine_balance"] == 0  # current_amount_due negativo -> 0
    assert vacant["hearing_date"] == "2011-07-01"


def test_chicago_fines_dedupe_same_nov_number(monkeypatch):
    monkeypatch.setattr(pe, "resolve_chicago_zip", lambda **kw: ("60601", "x"))

    def fake_socrata(name, params):
        if name == "chi_ordinance_fines":
            return [
                {
                    "address": "10 DEDUPE ST",
                    "imposed_fine": "1000",
                    "hearing_date": "2022-03-02T00:00:00.000",
                    "violation_date": "2021-12-14T09:00:00.000",
                    "violation_description": "Code A",
                    "nov_number": "N1",
                    "id": "1",
                },
                {
                    "address": "10 DEDUPE ST",
                    "imposed_fine": "1000",
                    "hearing_date": "2022-03-02T00:00:00.000",
                    "violation_date": "2021-12-14T09:00:00.000",
                    "violation_description": "Code B",
                    "nov_number": "N1",
                    "id": "2",
                },
            ]
        return []

    monkeypatch.setattr(pe, "socrata", fake_socrata)
    items = pe.phase1_enrichment.fetch_chicago_fines(limit=10)
    assert len(items) == 1
    assert items[0]["fine_imposed"] == 1000
    assert items[0]["fine_balance"] == 1000


def test_boston_code_enforcement_maps_value(monkeypatch):
    monkeypatch.setattr(
        pe,
        "ckan_datastore",
        lambda resource_id, params: [
            {
                "case_no": "CE950765",
                "ticket_no": "U9C3CF17",
                "status": "Open",
                "status_dttm": "2026-11-19 17:10:00",
                "code": "1",
                "value": "25",
                "description": "Improper storage trash",
                "violation_stno": "64",
                "violation_street": "Beach",
                "violation_suffix": "ST",
                "violation_zip": "02111",
            }
        ],
    )
    items = pe.phase1_enrichment.fetch_boston_code_enforcement(limit=10)
    assert len(items) == 1
    item = items[0]
    assert item["signal_type"] == "legal_obligation"
    assert item["fine_imposed"] == 25
    assert item["fine_balance"] == 25
    assert item["compliance_deadline"] is None
    assert item["source_payload"][0]["source"] == "bos_code_enforcement"


def test_boston_code_enforcement_dedupe_same_case(monkeypatch):
    row = {
        "case_no": "CE1",
        "ticket_no": "T1",
        "status": "Open",
        "status_dttm": "2026-11-19 17:10:00",
        "code": "1",
        "value": "25",
        "description": "Trash",
        "violation_stno": "64",
        "violation_street": "Beach",
        "violation_suffix": "ST",
        "violation_zip": "02111",
    }
    monkeypatch.setattr(pe, "ckan_datastore", lambda *args, **kwargs: [row, dict(row)])
    items = pe.phase1_enrichment.fetch_boston_code_enforcement(limit=10)
    assert len(items) == 1
    assert items[0]["fine_imposed"] == 25


def test_insights_fines_available_by_city():
    dallas = opportunity_workflow.insights(kind="preventive", city="Dallas")
    chicago = opportunity_workflow.insights(kind="preventive", city="Chicago")
    boston = opportunity_workflow.insights(kind="preventive", city="Boston")
    assert dallas["totals"]["fines_available"] is False
    assert chicago["totals"]["fines_available"] is True
    assert boston["totals"]["fines_available"] is True


def test_territories_applies_severity_fines_and_deadline_filters():
    conn = get_connection()
    try:
        conn.execute("DELETE FROM opportunity_workflow")
        conn.commit()
    finally:
        conn.close()
    today = date.today()
    opportunity_workflow.create_opportunity(
        source_kind="preventive",
        source_record_id="territory-critical",
        source_type="pre_inspection",
        address="10 Filter St",
        city="Boston",
        state="MA",
        zip_code="02124",
        category="Structure",
        severity="critical",
        compliance_deadline=(today + timedelta(days=3)).isoformat(),
        fine_balance=100.0,
        fine_imposed=100.0,
        received_at=today.isoformat(),
    )
    opportunity_workflow.create_opportunity(
        source_kind="preventive",
        source_record_id="territory-low",
        source_type="pre_inspection",
        address="20 Filter St",
        city="Boston",
        state="MA",
        zip_code="02124",
        category="Structure",
        severity="low",
        received_at=today.isoformat(),
    )
    result = opportunity_workflow.territories(
        city="Boston",
        kind="all",
        days=30,
        severity="critical",
        deadline_within=7,
        with_fines=True,
    )
    assert result["totals"]["count"] == 1


def test_one_failing_source_does_not_abort_the_run(monkeypatch):
    service = pe.phase1_enrichment

    def boom(limit=0):
        raise RuntimeError("503 Service Unavailable")

    item = {
        "property_key": "resilience-test",
        "address": "123 N MAIN ST",
        "city": "Chicago",
        "state": "IL",
        "zip_code": "60601",
        "signal_type": "open_request",
        "severity": "medium",
        "category": "Rodent",
        "description": "Rodent",
        "compliance_deadline": None,
        "history": [],
        "tags": [],
    }
    monkeypatch.setattr(service, "fetch_chicago_311", boom)
    monkeypatch.setattr(service, "fetch_chicago_violations", lambda limit=0: [item])
    monkeypatch.setattr(service, "fetch_pluto", lambda bbls: {})

    out = service.build_candidates(
        hpd_complaints=0,
        hpd_deadlines=0,
        ecb=0,
        chi_violations=10,
        chi_311=10,
        chi_fines=0,
        permit_rows=0,
    )
    assert [c["address"] for c in out] == ["123 N MAIN ST"]
    assert "503" in service._last_source_errors["chi_311"]


def test_source_payload_is_persisted_in_db():
    conn = get_connection()
    try:
        conn.execute("DELETE FROM opportunity_workflow")
        conn.commit()
    finally:
        conn.close()
    row = opportunity_workflow.create_opportunity(
        source_kind="reactive",
        source_record_id="payload-test",
        source_type="violation",
        address="10 Payload St",
        city="Boston",
        state="MA",
        zip_code="02124",
        category="Structure",
        severity="high",
        signal_type="legal_obligation",
        source_payload=[{"source": "test", "row": {"fine": 25}}],
    )
    conn = get_connection()
    try:
        stored = conn.execute(
            "SELECT source_payload FROM opportunity_workflow WHERE id = ?", (row["id"],)
        ).fetchone()["source_payload"]
    finally:
        conn.close()
    assert "test" in stored
    assert "25" in stored

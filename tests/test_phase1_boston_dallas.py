from datetime import datetime, timedelta, timezone

from backend.services import phase1_enrichment as pe
from backend.services.phase1_enrichment import Phase1EnrichmentService
from backend.services.phase1_scheduler import Phase1Scheduler


def _recent(days: int = 5) -> str:
    return (datetime.now(timezone.utc).date() - timedelta(days=days)).isoformat()


def test_boston_violations_mapping(monkeypatch):
    monkeypatch.setattr(
        pe,
        "ckan_datastore",
        lambda resource_id, params: [
            {
                "case_no": "V948835",
                "status": "Open",
                "status_dttm": "2026-11-09 08:08:28",
                "code": "116",
                "description": "Unsafe Structures",
                "violation_stno": "478",
                "violation_street": "Blue Hill",
                "violation_suffix": "AVE",
                "violation_zip": "02121",
            }
        ],
    )
    items = Phase1EnrichmentService().fetch_boston_violations(10)
    assert len(items) == 1
    item = items[0]
    assert item["city"] == "Boston"
    assert item["signal_type"] == "open_request"
    assert item["category"] == "Structure"
    assert item["severity"] == "critical"
    assert item["zip_code"] == "02121"
    assert item["compliance_deadline"] is None


def test_boston_311_skips_closed_and_generic(monkeypatch):
    rows = [
        {
            "case_id": "BCS-1",
            "case_topic": "Litter & Debris",
            "case_status": "In progress",
            "open_date": "2026-11-14T10:49:43",
            "target_close_date": "2026-11-17T10:49:43",
            "full_address": "1 Main St, Boston, MA 02118",
            "zip_code": 2118,
        },
        {
            "case_id": "BCS-2",
            "case_topic": "Needle Pickup",
            "case_status": "Submit",
            "open_date": "2026-11-14T10:48:53",
            "full_address": "2 Main St, Boston, MA 02118",
            "zip_code": 2118,
        },
        {
            "case_id": "BCS-3",
            "case_topic": "Litter & Debris",
            "case_status": "Closed",
            "open_date": "2026-11-14T10:48:53",
            "full_address": "3 Main St, Boston, MA 02118",
            "zip_code": 2118,
        },
    ]
    monkeypatch.setattr(pe, "ckan_datastore", lambda resource_id, params: rows)
    items = Phase1EnrichmentService().fetch_boston_311(10)
    assert len(items) == 1
    assert items[0]["category"] == "Debris"
    assert items[0]["compliance_deadline"] == "2026-11-17"


def test_boston_permits_window_and_roof(monkeypatch):
    rows = [
        {
            "permitnumber": "SF1",
            "worktype": "SOL",
            "permittypedescr": "Short Form Bldg Permit",
            "description": "Solar Panels",
            "issued_date": f"{_recent(5)}T13:57:30",
            "status": "Open",
            "address": "117 Vogel ST",
            "zip": "02132",
            "declared_valuation": "$3,000.00",
        },
        {
            "permitnumber": "OLD1",
            "description": "Old roof",
            "issued_date": f"{_recent(40)}T13:57:30",
            "address": "1 Old ST",
            "zip": "02132",
        },
    ]
    monkeypatch.setattr(pe, "ckan_datastore", lambda resource_id, params: rows)
    items = Phase1EnrichmentService().fetch_boston_permits(10, days=30)
    assert len(items) == 1
    assert items[0]["category"] == "Roof"
    assert items[0]["signal_type"] == "authorized_work"
    assert items[0]["job_value"] == 3000.0


def test_dallas_code_mapping(monkeypatch):
    rows = [
        {
            "service_request_number": "26-1",
            "service_request_type": "Substandard Structure - CCS",
            "department": "Code Compliance",
            "status": "New",
            "created_date": "2026-11-13T23:48:01.000",
            "overall_service_request_due_date": "2026-12-07T23:59:00.000",
            "address": "5301 REIGER AVE, DALLAS, TX, 75214",
        }
    ]
    monkeypatch.setattr(pe, "socrata", lambda name, params: rows)
    items = Phase1EnrichmentService().fetch_dallas_code(10)
    assert len(items) == 1
    item = items[0]
    assert item["city"] == "Dallas"
    assert item["zip_code"] == "75214"
    assert item["category"] == "Structure"
    assert item["compliance_deadline"] == "2026-12-07"


def test_dallas_311_requires_trade_match(monkeypatch):
    rows = [
        {
            "service_request_number": "26-2",
            "service_request_type": "High Weeds - CCS",
            "status": "New",
            "created_date": "2026-11-13T23:48:01.000",
            "address": "10 WEED ST, DALLAS, TX, 75201",
        },
        {
            "service_request_number": "26-3",
            "service_request_type": "Other - CCS",
            "status": "New",
            "created_date": "2026-11-13T23:48:01.000",
            "address": "20 OTHER ST, DALLAS, TX, 75201",
        },
    ]
    monkeypatch.setattr(pe, "socrata", lambda name, params: rows)
    items = Phase1EnrichmentService().fetch_dallas_311(10)
    assert len(items) == 1
    assert items[0]["category"] == "Grass"


def test_dallas_permits_parse_us_date(monkeypatch):
    rows = [
        {
            "permit_number": "RES-1",
            "permit_type": "Residential Electrical Permit",
            "issued_date": datetime.now(timezone.utc).strftime("%m/%d/%y"),
            "work_description": "Roof Mount Solar",
            "value": 12500,
            "street_address": "13316 ROARING SPRINGS LN",
            "zip_code": "75240",
        },
        {
            "permit_number": "OLD-1",
            "permit_type": "Old",
            "issued_date": "01/01/20",
            "work_description": "Old work",
            "street_address": "1 OLD ST",
            "zip_code": "75240",
        },
    ]
    monkeypatch.setattr(pe, "socrata", lambda name, params: rows)
    items = Phase1EnrichmentService().fetch_dallas_permits(10, days=30)
    assert len(items) == 1
    assert items[0]["category"] == "Roof"
    assert items[0]["job_value"] == 12500.0


def test_city_coverage_alert(monkeypatch):
    from backend.services.db import db_service

    service = db_service._service
    recorded = []
    monkeypatch.setattr(service, "get_preventive_city_counts", lambda: {"NYC": 10, "Boston": 0})
    monkeypatch.setattr(
        service,
        "get_leads_today_by_city",
        lambda: {"NYC": 100, "Boston": 445, "Dallas": 0},
    )
    monkeypatch.setattr(service, "has_recent_system_alert", lambda code, hours: False)
    monkeypatch.setattr(
        service,
        "record_system_alert",
        lambda level, code, message, context=None: recorded.append((level, code, context)),
    )
    result = Phase1Scheduler()._check_city_coverage()
    codes = [code for _, code, _ in recorded]
    assert "PREVENTIVE_CITY_EMPTY:BOSTON" in codes
    assert "PREVENTIVE_CITY_EMPTY:NYC" not in codes
    assert "PREVENTIVE_CITY_EMPTY:DALLAS" not in codes
    assert result["alerts"] == ["PREVENTIVE_CITY_EMPTY:BOSTON"]

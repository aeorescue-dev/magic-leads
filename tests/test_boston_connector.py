"""Conector Boston: mapeamento do schema NEW SYSTEM e compatibilidade legado."""
from backend.main import _boston_lead_from_record, _parse_ckan_dt


def test_new_system_schema_maps_to_raw_lead():
    record = {
        "case_id": "BCS-00379291",
        "open_date": "2026-11-06T14:11:29",
        "case_topic": "Unsatisfactory Living Conditions",
        "service_name": "Unsatisfactory Living Conditions",
        "assigned_department": "Inspectional Services",
        "assigned_team": "ISD Code Enforcement",
        "case_status": "In progress",
        "closure_reason": None,
        "close_date": None,
        "target_close_date": "2026-11-07T14:11:29",
        "on_time": "ONTIME",
        "report_source": "BOS311",
        "full_address": "451 Saratoga St 3, Boston, MA 02128",
        "zip_code": 2128,
        "neighborhood": "East Boston",
        "ward": 1,
        "precinct": 3,
        "longitude": -71.033,
        "latitude": 42.377,
    }
    lead = _boston_lead_from_record(record)
    assert lead is not None
    assert lead.external_id == "BCS-00379291"
    assert lead.city == "Boston"
    assert lead.zip_code == "02128"
    assert lead.issue_description.startswith("Unsatisfactory")
    assert lead.case_title.startswith("Unsatisfactory")
    assert lead.department == "Inspectional Services"
    assert lead.queue == "ISD Code Enforcement"
    assert lead.case_status == "In progress"
    assert lead.source == "BOS311"
    assert lead.neighborhood == "East Boston"
    assert lead.created_at.isoformat().startswith("2026-11-06T14:11:29")


def test_legacy_schema_still_maps():
    record = {
        "case_enquiry_id": "101006777238",
        "open_dt": "2026-11-05T11:30:59",
        "case_title": "Electrical",
        "reason": "Electrical",
        "type": "Electrical",
        "department": "ISD",
        "location": "2 Columbus Ave  Boston  MA  02116",
        "location_zipcode": "02116",
        "case_status": "Open",
    }
    lead = _boston_lead_from_record(record)
    assert lead is not None
    assert lead.external_id == "101006777238"
    assert lead.address.startswith("2 Columbus Ave")
    assert lead.zip_code == "02116"


def test_ckan_dates_are_timezone_aware():
    parsed = _parse_ckan_dt("2026-11-06T14:11:29")
    assert parsed is not None
    assert parsed.tzinfo is not None
    assert parsed.isoformat().startswith("2026-11-06T14:11:29")

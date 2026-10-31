"""
Testes unitarios dedicados para as correcoes F1, F3, F4, F6 e is_intersection.
"""
from backend.scrapers.socrata_311 import Socrata311Scraper
from backend.services.outbound_templates import build_context, copy_count
from backend.utils.address import is_intersection


def test_is_intersection():
    assert is_intersection("INTERSECTION OF 5TH AVE & 34TH ST") is True
    assert is_intersection("BROADWAY & 5TH AVE") is True
    assert is_intersection("123 MAIN ST & 4TH") is False  # tem numero predial
    assert is_intersection("AT&T BUILDING") is False
    assert is_intersection(None) is False

def test_copy_count_exact():
    # F4 aprovado: numero exato sem piso artificial 40+
    assert copy_count(0) == "0"
    assert copy_count(5) == "5"
    assert copy_count(42) == "42"

def test_address_tail_public_notice():
    ctx = build_context(
        {"owner_name": "ACME", "address": "123 BROADWAY", "issue_category": "Roof"},
        "NYC", "roofing", 10
    )
    assert "active public record notice near 123 BROADWAY" in ctx["address_tail"]


def test_address_tail_omits_intersection():
    ctx = build_context(
        {"owner_name": "ACME", "address": "BROADWAY & 5TH AVENUE", "issue_category": "Roof"},
        "NYC", "roofing", 10
    )
    assert "BROADWAY" not in ctx["address_tail"]
    assert "across New York City" in ctx["address_tail"]


def test_socrata_indoor_boundary():
    scraper = Socrata311Scraper()
    # F1: "indoor" nao deve casar com "door" devido ao word boundary
    cat, matched = scraper._infer_category_ex("Indoor Air Quality")
    assert matched is False


def test_socrata_lead_word_boundary():
    from backend.scrapers.socrata_311 import IssueCategory
    scraper = Socrata311Scraper()
    cat, matched = scraper._infer_category_ex("Lead paint on the hallway wall")
    assert (cat, matched) == (IssueCategory.LEAD, True)
    # "lead" isolado (ex.: "lead singer") nao e' risco de chumbo
    cat2, matched2 = scraper._infer_category_ex("The lead singer was loud")
    assert cat2 != IssueCategory.LEAD


def test_catch_all_is_not_sendable():
    from backend.services.db import SENDABLE_EMAIL_STATUSES
    from backend.services.outbound_engine import is_sendable_contact

    assert "catch_all" not in SENDABLE_EMAIL_STATUSES
    assert "catch-all" not in SENDABLE_EMAIL_STATUSES
    assert is_sendable_contact({"email": "x@y.com", "email_status": "catch_all"}) is False
    assert is_sendable_contact({"email": "x@y.com", "email_status": "valid"}) is True


def test_greeting_without_contact_name_is_clean():
    ctx = build_context({"owner_name": "", "address": "1 MAIN ST", "issue_category": "Roof"},
                        "NYC", "roofing", 3)
    assert ctx["greeting"] == "Hi,"
    assert "Hi ," not in ctx["greeting"]


def test_contact_lead_channel_guards():
    from datetime import datetime

    from fastapi.testclient import TestClient

    from backend.main import _hash_token, app
    from backend.models.schemas import (
        EnrichedLead,
        IssueCategory,
        SourceType,
        UrgencyLevel,
    )
    from backend.services.db import db_service

    svc = db_service._service
    user = svc.get_user_by_email("pytest-channel-guards@magicleads.app") or svc.create_user(
        "pytest-channel-guards@magicleads.app", "pass", "Pytest Guard"
    )
    # A5: contacto exige acesso vigente; estes guards só fazem sentido para
    # um assinante ativo (senão a resposta é 402 antes de validar o canal).
    svc.extend_access(user["id"], days=7)
    token = "pytest_guard_token_123"
    svc.create_user_session(user["id"], _hash_token(token), "Pytest", None)

    # Lead 1: apenas morada predial, sem telefone/e-mail
    row1 = svc.insert_lead_new(EnrichedLead(
        external_id="pytest-guard-1",
        source_type=SourceType.SERVICE_311,
        address="100 MAIN STREET",
        city="NEW YORK", state="NY", zip_code="10001",
        lat=None, lng=None, county=None,
        issue_category=IssueCategory.ROOF,
        issue_description="Leak",
        urgency_level=UrgencyLevel.HIGH,
        owner_name="NO CONTACT LLC",
        owner_phone="", owner_email="",
        date_reported=datetime.now(),
        image_url=None, source_url=None,
    ))
    lid1 = row1["id"]

    # Lead 2: esquina sem telefone
    row2 = svc.insert_lead_new(EnrichedLead(
        external_id="pytest-guard-2",
        source_type=SourceType.SERVICE_311,
        address="BROADWAY & 5TH AVE",
        city="NEW YORK", state="NY", zip_code="10001",
        lat=None, lng=None, county=None,
        issue_category=IssueCategory.ROOF,
        issue_description="Leak",
        urgency_level=UrgencyLevel.HIGH,
        owner_name="CORNER LLC",
        owner_phone="", owner_email="",
        date_reported=datetime.now(),
        image_url=None, source_url=None,
    ))
    lid2 = row2["id"]

    client = TestClient(app)
    headers = {"Authorization": f"Bearer {token}"}

    # F5: canal sms exige telefone
    r_sms = client.post(f"/api/leads/{lid1}/contact", headers=headers, json={"channel": "sms"})
    assert r_sms.status_code == 400
    assert "telefone" in r_sms.json()["detail"].lower()

    # F5: canal email exige e-mail
    r_email = client.post(f"/api/leads/{lid1}/contact", headers=headers, json={"channel": "email"})
    assert r_email.status_code == 400
    assert "e-mail" in r_email.json()["detail"].lower()

    # F7: visit/mail em esquina e' 400
    r_visit = client.post(f"/api/leads/{lid2}/contact", headers=headers, json={"channel": "visit"})
    assert r_visit.status_code == 400
    assert "esquina" in r_visit.json()["detail"].lower()

    # Morada predial sem telefone/email aceita 'visit'
    r_visit_ok = client.post(f"/api/leads/{lid1}/contact", headers=headers, json={"channel": "visit"})
    assert r_visit_ok.status_code == 200
    assert r_visit_ok.json()["status"] == "ok"



"""Testes unitarios para o motor de descoberta e filtros de lead."""

from __future__ import annotations

from backend.services.company_discovery import (
    CompanyDiscovery,
    Fetcher,
    Resolver,
    SmtpProber,
    is_blocked_domain,
    registrable_domain,
)
from backend.services.lead_filter import (
    classify_owner_name,
    should_skip_discovery,
)


def test_lead_filter_classification():
    assert classify_owner_name("UNAVAILABLE OWNER") == "institutional"
    assert classify_owner_name("NYC HOUSING AUTHORITY") == "institutional"
    assert classify_owner_name("PARKCHESTER SOUTH CONDOMINIUM ASSOC") == "institutional"
    assert classify_owner_name("KINGSLEY CONSTRUCTION GROUP INC") == "company"
    assert classify_owner_name("SMITH, JOHN") == "person"
    assert classify_owner_name("") == "empty"

    assert should_skip_discovery("NYC HOUSING AUTHORITY") is True
    assert should_skip_discovery("KINGSLEY CONSTRUCTION GROUP INC") is False


def test_domain_normalization():
    assert registrable_domain("https://www.foo.com/path?query=1") == "foo.com"
    assert registrable_domain("sub.domain.co.uk") == "domain.co.uk"
    assert is_blocked_domain("yelp.com") is True
    assert is_blocked_domain("google.com") is True
    assert is_blocked_domain("kingsleyconstruction.com") is False


def test_company_discovery_heuristic_mocked():
    resolver = Resolver(
        a_record=lambda d: d == "kingsley.com",
        mx_records=lambda d: [(10, "mail.kingsley.com")] if d == "kingsley.com" else [],
        ns_records=lambda d: ["ns1.domaincontrol.com"],
    )
    fetcher = Fetcher(
        fetch=lambda url, timeout: {
            "status": 200,
            "url": url,
            "html": b"<html><title>Kingsley Construction NYC</title><body>Kingsley Construction 10001 NYC</body></html>",
        }
    )
    prober = SmtpProber(
        probe=lambda mx, recipients: {
            "error": None,
            "codes": {r: ("accepted" if "info" in r else "rejected") for r in recipients},
        }
    )

    disc = CompanyDiscovery(resolver=resolver, fetcher=fetcher, prober=prober, clock=lambda: 0.0)
    lead = {
        "owner_name": "Kingsley Construction",
        "city": "NYC",
        "state": "NY",
        "zip_code": "10001",
        "owner_phone": "2125550199",
    }

    res = disc.discover(lead, timeout=10.0)
    assert res["domain"] == "kingsley.com"
    assert res["domain_source"] == "heuristic"
    assert res["validation"]["accepted"] == ["info@kingsley.com"]

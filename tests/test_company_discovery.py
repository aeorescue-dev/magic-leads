"""Testes unitarios para o motor de descoberta e filtros de lead."""

from __future__ import annotations

from backend.services.company_discovery import (
    CompanyDiscovery,
    Fetcher,
    Resolver,
    SmtpProber,
    _default_a_record,
    _default_mx_records,
    is_blocked_domain,
    registrable_domain,
    slug_candidates,
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


def test_identity_gate_rejeita_diretorio_com_palavra_generica():
    """`OZ CONTRACTING` nao pode aceitar `contractingnyc.com` (diretorio)."""
    from backend.services.company_discovery import identity_ok

    assert identity_ok(
        {"owner_name": "OZ CONTRACTING LLC"}, "contractingnyc.com",
        "Contracting NYC - Find local contractors",
    ) is False
    assert identity_ok(
        {"owner_name": "Hogan Plumbing, Inc."}, "hoganplumbing.com",
        "Hogan Plumbing | Chicago",
    ) is True
    assert identity_ok(
        {"owner_name": "Walsh Group"}, "walshgroup.com",
        "Walsh Group - Construction Management",
    ) is True
    assert identity_ok(
        {"owner_name": "PMC Contracting"}, "pmcnyc.com", "PMC Contracting NYC"
    ) is True


def test_slug_candidates_keep_commercial_tokens():
    """`significant_tokens` remove GROUP/COMPANY; o slug tem de os reintroduzir."""
    assert "walshgroup" in slug_candidates("Walsh Group", "Chicago")
    assert "wightco" in slug_candidates("Wight & Company", "Chicago")
    assert "leopardo" in slug_candidates("Leopardo Companies", "Chicago")
    assert "turnerconstruction" in slug_candidates("Turner Construction", "NYC")


def test_dns_fallback_usa_doh_quando_resolver_falha(monkeypatch):
    """Sem nameserver no contentor, o fallback DoH tem de resolver A e MX."""
    import dns.resolver

    def boom(*a, **k):
        raise RuntimeError("Network is unreachable")

    monkeypatch.setattr(dns.resolver, "resolve", boom)
    monkeypatch.setattr(
        "socket.getaddrinfo",
        lambda *a, **k: (_ for _ in ()).throw(OSError("no dns")),
    )

    answers = {
        ("walshgroup.com", "A"): [{"type": 1, "data": "1.2.3.4"}],
        ("walshgroup.com", "MX"): [{"type": 15, "data": "10 walshgroup-com.mail.protection.outlook.com."}],
    }
    monkeypatch.setattr(
        "backend.services.company_discovery._doh_answer",
        lambda name, rtype: answers.get((name.lower(), rtype), []),
    )

    assert _default_a_record("walshgroup.com") is True
    assert _default_mx_records("walshgroup.com") == [
        (10, "walshgroup-com.mail.protection.outlook.com")
    ]


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

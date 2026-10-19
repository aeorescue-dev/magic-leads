"""Testes do adapter EmailListVerify (Outbound Frio - Fase 2).

Cobrem a regra anti-spam (so' e-mails comprovadamente `valid` seguem), o
billing em creditos (verify=1, find nome=5, dominio=10) e o fallback
fail-soft sem API key. Sem tocar a rede real (HTTP mockado).
"""

from __future__ import annotations

import pytest

from backend.services.enrichment_emaillistverify import (
    EmailListVerifyService,
    _candidate_status,
    _candidate_valid,
    _extract_contacts,
    _parse_verify_status,
    email_domain,
    normalize_email,
)

# ------------------------------------------------------------------ helpers


def test_normalize_email_and_domain_helpers():
    assert normalize_email(" Ops@Example.COM ") == "ops@example.com"
    assert normalize_email("nope") is None
    assert normalize_email(None) is None
    assert email_domain("ops@example.com") == "example.com"
    # Webmail publico nao identifica empresa -> None.
    assert email_domain("ops@gmail.com") is None
    assert email_domain(None) is None


def test_extract_contacts_handles_shapes():
    records = _extract_contacts([{"email": "a@x.com", "result": "ok"}])
    assert records and records[0]["email"] == "a@x.com"
    assert _extract_contacts({"data": [{"email": "b@x.com"}]})[0]["email"] == "b@x.com"
    assert _extract_contacts({"email": "c@x.com"})[0]["email"] == "c@x.com"
    assert _extract_contacts([{"no_email": True}]) == []
    assert _extract_contacts(None) == []


def test_parse_verify_status_handles_json_and_text():
    assert _parse_verify_status({"status": "ok"}, None) == "ok"
    assert _parse_verify_status({"result": "VALID"}, None) == "valid"
    assert _parse_verify_status(None, "ok\n") == "ok"
    assert _parse_verify_status(None, "") is None
    assert _parse_verify_status({"unknown_field": 1}, None) is None


def test_candidate_valid_requires_ok_and_confidence():
    assert _candidate_valid({"result": "ok", "confidence": "high"}) is True
    assert _candidate_valid({"result": "ok", "confidence": "medium"}) is True
    # Deliveravel mas confianca baixa/desconhecida -> rejeitado.
    assert _candidate_valid({"result": "ok", "confidence": "low"}) is False
    assert _candidate_valid({"result": "ok", "confidence": "unknown"}) is False
    # Nao-deliveravel -> rejeitado mesmo com confianca alta.
    assert _candidate_valid({"result": "invalid_mx", "confidence": "high"}) is False
    assert _candidate_valid({"result": "disposable", "confidence": "high"}) is False
    # Sem confianca explicita, confia na deliverabilidade.
    assert _candidate_valid({"result": "ok"}) is True
    assert _candidate_status({"result": "ok", "confidence": "high"}) == "valid"
    assert _candidate_status({"result": "invalid_mx"}) == "invalid_mx"


def _configured() -> EmailListVerifyService:
    svc = EmailListVerifyService()
    svc.api_key = "test-key"
    return svc


# ------------------------------------------------------------------ service


@pytest.mark.asyncio
async def test_service_unconfigured_is_fail_soft():
    svc = EmailListVerifyService()
    assert svc.configured is False
    result = await svc.find_and_verify(owner_email="ops@example.com")
    assert result.success is False
    assert result.outcome == "not_configured"
    assert result.billed_calls == 0
    await svc.aclose()


@pytest.mark.asyncio
async def test_service_accepts_valid_lead_email_and_bills_verify(monkeypatch):
    svc = _configured()

    async def fake_verify(email):
        return "ok", 200

    monkeypatch.setattr(svc, "verify_email", fake_verify)
    result = await svc.find_and_verify(owner_email="ops@x.com")
    assert result.success is True
    assert result.email == "ops@x.com"
    assert result.status == "valid"
    assert result.provider == "emaillistverify"
    assert result.billed_calls == svc.verify_credits
    assert result.spend_usd == pytest.approx(round(svc.verify_credits * svc.per_credit_usd, 4))
    await svc.aclose()


@pytest.mark.asyncio
async def test_service_rejects_non_valid_lead_email(monkeypatch):
    svc = _configured()

    async def fake_verify(email):
        return "invalid", 200

    monkeypatch.setattr(svc, "verify_email", fake_verify)
    # gmail -> sem dominio corporativo; nada mais a procurar.
    result = await svc.find_and_verify(owner_email="ops@gmail.com")
    assert result.success is False
    assert result.outcome == "invalid_email"
    assert result.status == "invalid"
    assert result.billed_calls == svc.verify_credits  # verificacao foi cobrada
    await svc.aclose()


@pytest.mark.asyncio
async def test_service_finds_valid_named_contact_and_bills_five(monkeypatch):
    svc = _configured()

    async def fake_find(first, last, domain):
        assert (first, last, domain) == ("Maria", "Souza", "x.com")
        return [{"email": "maria.souza@x.com", "confidence": "high", "result": "ok"}], 201

    monkeypatch.setattr(svc, "find_contact", fake_find)
    result = await svc.find_and_verify(
        owner_email=None, contact_name="Maria Souza", domain="x.com"
    )
    assert result.success is True
    assert result.email == "maria.souza@x.com"
    assert result.status == "valid"
    assert result.billed_calls == svc.find_credits_named
    assert result.spend_usd == pytest.approx(round(svc.find_credits_named * svc.per_credit_usd, 4))
    await svc.aclose()


@pytest.mark.asyncio
async def test_service_rejects_low_confidence_found(monkeypatch):
    svc = _configured()

    async def fake_find(first, last, domain):
        return [{"email": "maria.souza@x.com", "confidence": "low", "result": "ok"}], 201

    monkeypatch.setattr(svc, "find_contact", fake_find)
    result = await svc.find_and_verify(contact_name="Maria Souza", domain="x.com")
    assert result.success is False
    assert result.outcome == "invalid_email"
    assert result.billed_calls == 0
    await svc.aclose()


@pytest.mark.asyncio
async def test_service_no_domain_is_free_and_not_billed():
    svc = _configured()
    result = await svc.find_and_verify(
        owner_email=None, company_name="PRIME 80 LLC", contact_name="PRIME 80 LLC"
    )
    assert result.success is False
    assert result.outcome == "no_domain"
    assert result.billed_calls == 0
    await svc.aclose()


@pytest.mark.asyncio
async def test_service_provider_no_results_and_http_error(monkeypatch):
    svc = _configured()

    async def fake_empty(first, last, domain):
        return [], 201

    monkeypatch.setattr(svc, "find_contact", fake_empty)
    empty = await svc.find_and_verify(contact_name="Maria Souza", domain="x.com")
    assert empty.outcome == "provider_no_results"
    assert empty.billed_calls == 0

    async def fake_error(first, last, domain):
        return [], 500

    monkeypatch.setattr(svc, "find_contact", fake_error)
    error = await svc.find_and_verify(contact_name="Maria Souza", domain="y.com")
    assert error.outcome == "http_error"
    assert error.billed_calls == 0
    await svc.aclose()

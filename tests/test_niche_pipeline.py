"""Testes do classificador de nicho, do gate de envio e da rampa de warm-up.

Regra de negocio que estes testes protegem:
  * o nicho e' da EMPRESA, nunca do lote;
  * sem evidencia clara nao se envia (ambiguous/unknown);
  * o numero divulgado no copy e' o entregavel, nao o inventario bruto;
  * a rampa de warm-up sobe de forma conservadora e nunca ignora os tectos.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.services import niche_classifier as nc
from backend.services import outbound_engine as oe
from backend.services import outbound_templates as ot

# ------------------------------------------------------------ classificador

@pytest.mark.parametrize(
    "company,domain,expected",
    [
        ("Black Diamond Plumbing & Mechanical", "blackdiamondplumbing.com", "plumbing"),
        ("Deljo Heating & Cooling", "deljoheating.com", "hvac"),
        ("Northside Roofing", "northsideroof.com", "roofing"),
        ("Hudson Valley Electric", "hvelectric.com", "electrical"),
        ("Ace Renovations", "acerenovations.net", "remodeling"),
        ("Pepper Construction", "pepperconstruction.com", "general_contractors"),
        ("GreenLawn Services", "greenlawnservices.com", "landscaping"),
        ("Mold Doctors", "molddoctors.com", "restoration"),
    ],
)
def test_classifier_confirms_clear_companies(company, domain, expected):
    r = nc.classify(company, domain=domain)
    assert r["status"] == "confirmed"
    assert r["niche"] == expected


def test_classifier_uses_site_text_for_generic_names():
    # "Skender" so' e' identificavel pelo site ("The Premier Construction Experience")
    r = nc.classify(
        "Skender",
        domain="skender.com",
        text="Skender | The Premier Construction Experience",
    )
    assert r["status"] == "confirmed"
    assert r["niche"] == "general_contractors"


def test_classifier_quarantines_weak_evidence():
    """Sem evidencia suficiente nao se inventa nicho (nem se envia)."""
    r = nc.classify("Smith and Sons", domain="smithandsons.com")
    assert r["status"] in ("ambiguous", "unknown")
    assert r["niche"] is None
    assert nc.is_sendable(r["niche"], r["status"]) is False


def test_classifier_unknown_company_never_sendable():
    r = nc.classify("Keystone Partners", domain="keystonepartners.com")
    assert r["status"] == "unknown"
    assert nc.is_sendable(r["niche"], r["status"]) is False


def test_gate_rejects_niche_outside_catalogue():
    assert nc.is_sendable("plumbing", "confirmed") is True
    assert nc.is_sendable("plumbing", "ambiguous") is False
    assert nc.is_sendable("unknown_vendor", "confirmed") is False
    assert nc.is_sendable(None, "confirmed") is False


# ------------------------------------------------------------------- copy

def _ctx(company, domain, city, niche, count, top=None):
    lead = {
        "id": 1,
        "address": f"B2B contact - info@{domain}",
        "city": city,
        "state": "IL",
        "issue_category": ot.NICHES[niche]["label"],
        "owner_name": company,
    }
    contact = {"company_name": company, "contact_name": None}
    return ot.build_context(
        lead, city, niche, count, contact=contact, top_categories=top
    )


def test_subject_is_mobile_short_and_keeps_the_niche():
    ctx = _ctx("Black Diamond Plumbing", "blackdiamondplumbing.com", "CHICAGO",
               "plumbing", 2536)
    subject = ot.render_email("plumbing", ctx)["subject"]
    assert len(subject) <= ot.SUBJECT_MAX
    assert "plumbing" in subject.lower()
    assert "Chicago" in subject


def test_subject_never_loses_niche_on_long_numbers():
    for niche in ot.NICHES:
        ctx = _ctx("Acme", "acme.com", "NYC", niche, 12521)
        subject = ot.render_email(niche, ctx)["subject"]
        assert len(subject) <= ot.SUBJECT_MAX, (niche, subject)
        trade = ot.NICHES[niche]["subject_trade"].lower()
        assert trade in subject.lower(), (niche, subject)


def test_hook_never_has_we_currently_have():
    ctx = _ctx("Acme Plumbing", "acmeplumbing.com", "CHICAGO", "plumbing", 12)
    body = ot.render_email("plumbing", ctx)["body"]
    assert "We currently have" not in body
    assert body.splitlines()[2].startswith("12 active plumbing projects")


def test_cta_is_single_word():
    ctx = _ctx("Acme", "acme.com", "DALLAS", "hvac", 18)
    body = ot.render_email("hvac", ctx)["body"]
    assert 'Reply with "send"' in body


def test_no_internal_or_b2b_placeholders_in_body():
    ctx = _ctx("Skender", "skender.com", "CHICAGO", "general_contractors", 10)
    body = ot.render_email("general_contractors", ctx)["body"]
    for forbidden in ("B2B contact", "311", "public record", "IssueCategory"):
        assert forbidden not in body


def test_composition_only_uses_attractive_services():
    # "Debris" e "Lead" sao internos: nao podem aparecer na clausula
    clause = ot.composition_clause(
        [("Debris", 800), ("Lead", 200)], 1000, exclude="construction"
    )
    assert clause == ""
    clause2 = ot.composition_clause(
        [("Plumbing", 700), ("Lead", 300)], 1000, exclude="plumbing"
    )
    assert "burst pipes" in clause2
    assert "lead" not in clause2.lower()


# --------------------------------------------------------------- warm-up

def _cfg(**kw):
    base = {
        "warmup_enabled": "1",
        "per_mailbox_daily_cap": "25",
        "warmup_ramp": "1,1,1,2,3,5,8,12",
    }
    base.update(kw)
    return base


def test_ramp_day_zero_to_two_is_one():
    cfg = _cfg()
    now = datetime.now(timezone.utc)
    for days in (0, 1, 2):
        started = (now - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        mb = {"daily_cap": 1, "warmup_started_at": started}
        assert oe.effective_mailbox_cap(mb, cfg, now) == 1


def test_ramp_scales_after_day_three():
    cfg = _cfg()
    now = datetime.now(timezone.utc)
    esperado = {3: 2, 4: 3, 5: 5, 6: 8, 7: 12, 30: 1}
    for days, cap in esperado.items():
        started = (now - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        mb = {"daily_cap": 1, "warmup_started_at": started}
        got = oe.effective_mailbox_cap(mb, cfg, now)
        if days == 30:
            # rampa terminada -> vale o daily_cap da caixa (1)
            assert got == 1
        else:
            assert got == cap, (days, got)


def test_ramp_respects_per_mailbox_ceiling():
    cfg = _cfg(per_mailbox_daily_cap="4")
    now = datetime.now(timezone.utc)
    started = (now - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
    mb = {"daily_cap": 25, "warmup_started_at": started}
    assert oe.effective_mailbox_cap(mb, cfg, now) == 4


def test_warmup_disabled_uses_mailbox_cap():
    cfg = _cfg(warmup_enabled="0")
    now = datetime.now(timezone.utc)
    mb = {"daily_cap": 25, "warmup_started_at": None}
    assert oe.effective_mailbox_cap(mb, cfg, now) == 25

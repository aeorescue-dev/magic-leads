"""Compliance do outbound: opt-out assinado, rodape CAN-SPAM e copy v2."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.services import outbound_templates as ot
from backend.services import unsubscribe as unsub
from backend.services.db import db_service

CLIENT = TestClient(app)


@pytest.fixture()
def secret(monkeypatch):
    monkeypatch.setattr(unsub.settings, "UNSUBSCRIBE_SECRET", "test-secret", raising=False)
    monkeypatch.setattr(unsub.settings, "PUSH_CLICK_SECRET", "", raising=False)
    monkeypatch.setattr(unsub.settings, "CRON_SECRET", "", raising=False)
    return "test-secret"


def test_token_roundtrip_e_assinatura(secret):
    token = unsub.make_token("Owner@Example.com")
    assert token and "." in token
    assert unsub.verify_token(token) == "owner@example.com"
    assert unsub.verify_token(token[:-1] + ("0" if token[-1] != "0" else "1")) is None
    assert unsub.verify_token("garbage") is None


def test_sem_segredo_nao_ha_token(monkeypatch):
    monkeypatch.setattr(unsub.settings, "UNSUBSCRIBE_SECRET", "", raising=False)
    monkeypatch.setattr(unsub.settings, "PUSH_CLICK_SECRET", "", raising=False)
    monkeypatch.setattr(unsub.settings, "CRON_SECRET", "", raising=False)
    assert unsub.make_token("a@b.com") == ""
    assert unsub.unsubscribe_url("a@b.com").endswith("/unsubscribe")


def test_endpoint_unsubscribe_suprime_email(secret):
    email = "optout-pytest@example.com"
    db_service._service.add_suppression(email, "email", "reset")  # limpa estado
    token = unsub.make_token(email)
    resp = CLIENT.get(f"/unsubscribe?token={token}")
    assert resp.status_code == 200
    assert "unsubscribed" in resp.text.lower()
    assert db_service._service.is_suppressed(email) is True


def test_endpoint_unsubscribe_rejeita_token_invalido():
    resp = CLIENT.get("/unsubscribe?token=fora")
    assert resp.status_code == 400
    resp = CLIENT.post("/unsubscribe?token=fora")
    assert resp.status_code == 400


def test_copy_v2_tem_rodape_legal_e_exclusividade_real():
    ctx = ot.build_context(
        {"owner_name": "KELSO-BURNETT CO.", "address": "B2B contact - x", "city": "CHICAGO"},
        "CHICAGO", "general_contractors", 12,
        contact={"company_name": "KELSO-BURNETT CO."},
    )
    mail = ot.render_email("general_contractors", ctx)
    body = mail["body"]
    assert "Hi Kelso-Burnett Co. team," in body
    assert ot.SENDER_POSTAL_ADDRESS in body
    assert "Unsubscribe: https://www.magicleads.app/unsubscribe" in body
    assert "one contractor at a time" in body
    assert "first come, first served" in body
    assert "homeowner" not in body.lower()
    assert "never shared" not in body.lower()


def test_friendly_company_nao_capitaliza_conjuncoes():
    from backend.services.outbound_templates import _friendly_company

    assert _friendly_company("KELSO-BURNETT CO.") == "Kelso-Burnett Co."
    assert (
        _friendly_company("123 REMODELING AND ROOFING LLC")
        == "123 Remodeling and Roofing LLC"
    )
    assert _friendly_company("Acme Roofing") == "Acme Roofing"


def test_singular_quando_ha_um_projeto():
    """`copy_count` tem piso 1: a frase nao pode dizer '1 projects'."""
    ctx = ot.build_context(
        {"owner_name": "Acme Roofing", "address": "1 MAIN ST", "issue_category": "Roof"},
        "NYC", "roofing", 1,
    )
    mail = ot.render_email("roofing", ctx)
    assert "1 roofing project open in NYC" in mail["subject"]
    assert "1 active roofing project in New York City" in mail["body"]
    assert "1 roofing projects" not in mail["body"]

    ctx2 = ot.build_context(
        {"owner_name": "Acme Roofing", "address": "1 MAIN ST", "issue_category": "Roof"},
        "NYC", "roofing", 1, category_override=ot.offer_category("roofing"),
    )
    ctx2["url"] = ot.sequence_url("NYC", "roofing", 2)
    step2 = ot.render_sequence_email("step2_offer", ctx2)
    assert "1 roofing project in New York City" in step2["subject"]
    assert "1 verified roofing project in New York City" in step2["body"]


def test_step2_usa_contagem_dinamica_e_categoria_do_nicho():
    ctx = ot.build_context(
        {"owner_name": "Hogan Plumbing", "address": "B2B contact - x", "city": "CHICAGO"},
        "CHICAGO", "plumbing", 37,
        category_override=ot.offer_category("plumbing"),
    )
    ctx["url"] = ot.sequence_url("CHICAGO", "plumbing", 2)
    mail = ot.render_sequence_email("step2_offer", ctx)
    assert "37" in mail["subject"]
    assert "plumbing" in mail["subject"]
    assert "300" not in mail["body"]
    assert "37 verified plumbing projects in Chicago" in mail["body"]
    assert "$120" in mail["body"]
    assert ot.SENDER_POSTAL_ADDRESS in mail["body"]

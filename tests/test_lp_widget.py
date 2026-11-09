"""Testes do serviço do widget de captação (Fase 0/1).

Nenhum teste toca no banco de desenvolvimento/produção: o `conftest.py` já
aponta `LEADS_DB_PATH` para um SQLite temporário; aqui isolamos novamente por
teste para garantir que as tabelas `lp_*` nascem limpas.
"""

import pytest

from backend.config import settings
from backend.services import db, lp_widget


@pytest.fixture(autouse=True)
def _lp_widget_isolation(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "lp_widget_test.db"))
    monkeypatch.setattr(settings, "EMAIL_API_KEY", "", raising=False)
    monkeypatch.setattr(settings, "EMAIL_FROM", "", raising=False)
    monkeypatch.setattr(settings, "LP_WIDGET_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "LP_WIDGET_SLA_HOURS", 4, raising=False)
    lp_widget._initialized = False
    yield
    lp_widget._initialized = False


def _create(**overrides):
    payload = {
        "email": "owner@example.com",
        "intent": "vs_ads",
        "message": "I'm spending $70 a day on Ads and barely converting.",
        "name": "Mike",
        "company": "Mike Roofing",
        "city": "Dallas",
        "trade": "Roofing",
        "consent_email": True,
        "locale": "en",
    }
    payload.update(overrides)
    return lp_widget.create_thread(**payload)


def test_create_thread_and_public_view_hides_internal_fields():
    created = _create()

    assert created["token"]
    assert created["id"] > 0
    assert created["sla_hours"] == 4
    # Sem EMAIL_API_KEY, o ack é fail-soft.
    assert created["ack_sent"] is False

    public = lp_widget.get_thread_public(created["token"])
    assert public is not None
    assert public["id"] == created["id"]
    assert public["status"] == "new"
    assert "email" not in public
    assert public["messages"][0]["role"] == "lead"
    assert public["messages"][0]["text"].startswith("I'm spending")


def test_reply_keeps_pt_br_and_exposes_only_english_to_lead():
    created = _create()

    result = lp_widget.reply(
        created["id"],
        body_pt="Olá! O passe custa $120 por semana e pode cancelar quando quiser.",
        body_en="Hi! The pass is $120 a week and you can cancel anytime.",
        admin_id=1,
    )
    assert result["ok"] is True
    assert result["email_sent"] is False  # sem EMAIL_API_KEY no teste

    admin = lp_widget.get_thread_admin(created["id"])
    assert admin is not None
    last = admin["messages"][-1]
    assert last["body_pt"].startswith("Olá!")
    assert last["body_en"].startswith("Hi!")
    assert last["email_status"] == "failed"

    public = lp_widget.get_thread_public(created["token"])
    assert public is not None
    assert public["messages"][-1]["role"] == "team"
    assert public["messages"][-1]["text"].startswith("Hi!")
    assert "Olá!" not in str(public)


def test_lead_follow_up_reopens_thread():
    created = _create()
    lp_widget.reply(
        created["id"],
        body_pt="Resposta interna",
        body_en="English reply",
        admin_id=1,
    )

    follow = lp_widget.add_lead_message(created["token"], "One more question.")
    assert follow is not None
    assert follow["ok"] is True

    public = lp_widget.get_thread_public(created["token"])
    assert public is not None
    assert public["status"] == "new"
    assert public["messages"][-1]["role"] == "lead"
    assert public["messages"][-1]["text"] == "One more question."


def test_invalid_token_is_none():
    assert lp_widget.get_thread_public("not-a-real-token") is None
    assert lp_widget.add_lead_message("not-a-real-token", "hello") is None


def test_consent_and_email_are_required():
    with pytest.raises(ValueError):
        _create(consent_email=False)
    with pytest.raises(ValueError):
        _create(email="not-an-email")


def test_list_threads_filters_by_status():
    created = _create()
    lp_widget.reply(
        created["id"],
        body_pt="Interno",
        body_en="Sent",
        admin_id=1,
    )

    replied = lp_widget.list_threads(status="replied")
    assert len(replied) == 1
    assert replied[0]["id"] == created["id"]
    assert replied[0]["message_count"] == 2

    assert lp_widget.list_threads(status="new") == []

"""Testes do serviço do widget de captação (Fase 0/1).

Nenhum teste toca no banco de desenvolvimento/produção: o `conftest.py` já
aponta `LEADS_DB_PATH` para um SQLite temporário; aqui isolamos novamente por
teste para garantir que as tabelas `lp_*` nascem limpas.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

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
    monkeypatch.setenv("LP_UPLOAD_DIR", str(tmp_path / "lp_uploads"))
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


def test_save_inbound_translation():
    created = _create()
    public = lp_widget.get_thread_public(created["token"])
    assert public is not None
    inbound_id = public["messages"][0]["id"]

    result = lp_widget.update_message_translation(
        created["id"], inbound_id, "Tradução revista pela equipa."
    )
    assert result is not None
    assert result["ok"] is True

    admin = lp_widget.get_thread_admin(created["id"])
    assert admin is not None
    assert admin["messages"][0]["body_pt"] == "Tradução revista pela equipa."


def test_save_translation_rejects_wrong_thread():
    created = _create()
    other = _create(email="other@example.com")
    public = lp_widget.get_thread_public(created["token"])
    assert public is not None
    inbound_id = public["messages"][0]["id"]

    assert (
        lp_widget.update_message_translation(
            other["id"], inbound_id, "Não devia gravar"
        )
        is None
    )


def test_enrich_thread_prefills_translation_and_drafts(monkeypatch):
    created = _create(
        message="Hello, I spend 70 a day on Ads and barely convert."
    )

    def fake_translate(text: str, source: str, target: str):
        if target == "pt":
            return "Olá, tradução PT-BR.", "fake"
        return "Hello, English draft.", "fake"

    monkeypatch.setattr(lp_widget.lp_ai, "translate", fake_translate)
    result = lp_widget.enrich_thread(created["id"])

    assert result["ok"] is True
    assert result["status"] == "ready"
    assert result["lead_lang"] == "en"

    admin = lp_widget.get_thread_admin(created["id"])
    assert admin is not None
    assert admin["messages"][0]["body_pt"].startswith("Olá")
    assert admin["draft_pt"]
    assert admin["draft_out"] == "Hello, English draft."
    assert admin["draft_out_lang"] == "en"
    assert admin["ai_status"] == "ready"
    assert admin["ai_provider"] == "fake"


def test_translate_draft_uses_lead_language(monkeypatch):
    created = _create()

    monkeypatch.setattr(
        lp_widget.lp_ai,
        "translate",
        lambda text, source, target: ("Translated reply", "fake"),
    )
    result = lp_widget.translate_draft(created["id"], "Olá, resposta da equipa")

    assert result is not None
    assert result["body_out"] == "Translated reply"
    assert result["lang"] == "en"

    admin = lp_widget.get_thread_admin(created["id"])
    assert admin is not None
    assert admin["draft_pt"] == "Olá, resposta da equipa"
    assert admin["draft_out"] == "Translated reply"
    assert admin["ai_status"] == "ready"


def test_enrich_thread_detects_portuguese_text(monkeypatch):
    created = _create(
        message=(
            "Qual é a diferença entre a Magic Leads e o Angi? "
            "Os leads não são partilhados?"
        )
    )

    monkeypatch.setattr(
        lp_widget.lp_ai,
        "translate",
        lambda text, source, target: (text, "identity"),
    )
    result = lp_widget.enrich_thread(created["id"])

    assert result["ok"] is True
    assert result["lead_lang"] == "pt"

    admin = lp_widget.get_thread_admin(created["id"])
    assert admin is not None
    assert admin["lead_lang"] == "pt"
    assert admin["draft_out_lang"] == "pt"
    assert admin["messages"][0]["body_pt"] == admin["messages"][0]["body"]


def test_create_thread_stores_trade_code_and_source():
    created = _create(trade_code="Roof", lead_source="referral")
    admin = lp_widget.get_thread_admin(created["id"])
    assert admin is not None
    assert admin["trade_code"] == "Roof"
    assert admin["lead_source"] == "referral"


def test_attachment_roundtrip():
    created = _create()
    data = b"\x89PNG\r\n\x1a\n" + b"0" * 32

    result = lp_widget.save_attachment(
        created["id"],
        direction="inbound",
        filename="foto.png",
        content_type="image/png",
        data=data,
    )
    assert result is not None
    assert result["id"] > 0
    assert result["size_bytes"] == len(data)

    admin = lp_widget.get_thread_admin(created["id"])
    assert admin is not None
    assert len(admin["attachments"]) == 1
    assert admin["attachments"][0]["filename"] == "foto.png"

    public = lp_widget.get_thread_public(created["token"])
    assert public is not None
    assert len(public["attachments"]) == 1

    stored = lp_widget.get_attachment(created["id"], result["id"])
    assert stored is not None
    assert stored["content_type"] == "image/png"


def test_status_and_period_filters():
    created = _create()
    result = lp_widget.set_thread_status(created["id"], "archived")
    assert result is not None
    assert result["status"] == "archived"

    assert len(lp_widget.list_threads(status="archived")) == 1
    assert len(lp_widget.list_threads(status="new")) == 0
    assert len(lp_widget.list_threads(period="today")) == 1
    assert len(lp_widget.list_threads(period="week")) == 1


def test_history_by_email():
    first = _create(email="same@example.com")
    second = _create(
        email="same@example.com",
        message="Second question about pricing and exclusivity.",
    )

    admin = lp_widget.get_thread_admin(second["id"])
    assert admin is not None
    assert len(admin["history"]) == 1
    assert admin["history"][0]["id"] == first["id"]


def test_acknowledgment_uses_lead_language(monkeypatch):
    sent: list[dict] = []

    def fake_send(to, subject, text, **kwargs):
        sent.append({"to": to, "subject": subject, "text": text})
        return True

    monkeypatch.setattr(lp_widget, "send_email", fake_send)

    lp_widget._send_ack(
        {"id": 7, "email": "lead@example.com", "name": "Carlos", "lead_lang": "es"},
        "tok",
    )
    lp_widget._send_ack(
        {"id": 8, "email": "lead@example.com", "name": "Fábio", "lead_lang": "pt"},
        "tok",
    )
    lp_widget._send_ack(
        {"id": 9, "email": "lead@example.com", "name": "Mike", "lead_lang": "en"},
        "tok",
    )

    assert sent[0]["text"].startswith("Hola Carlos,")
    assert sent[0]["subject"].startswith("Hemos recibido")
    assert sent[1]["text"].startswith("Olá Fábio,")
    assert sent[1]["subject"].startswith("Recebemos")
    assert sent[2]["text"].startswith("Hi Mike,")
    assert sent[2]["subject"].startswith("We received")


def test_reply_email_uses_lead_language(monkeypatch):
    created = _create(
        message=(
            "Hola, necesito informacion sobre los precios y la disponibilidad "
            "en Dallas esta semana, por favor."
        )
    )
    sent: list[dict] = []

    def fake_send(to, subject, text, **kwargs):
        sent.append({"to": to, "subject": subject, "text": text})
        return True

    monkeypatch.setattr(lp_widget, "send_email", fake_send)

    result = lp_widget.reply(
        created["id"],
        body_pt="Temos oportunidades em Dallas esta semana.",
        body_en="Tenemos oportunidades en Dallas esta semana.",
    )

    assert result is not None
    assert len(sent) == 1
    assert sent[0]["text"] == "Tenemos oportunidades en Dallas esta semana."
    assert sent[0]["subject"].startswith("Re: tu pregunta")


def test_availability_auto_business_hours(monkeypatch):
    monkeypatch.setattr(settings, "LP_WIDGET_TZ", "America/New_York", raising=False)
    monkeypatch.setattr(settings, "LP_WIDGET_BUSINESS_START", 8, raising=False)
    monkeypatch.setattr(settings, "LP_WIDGET_BUSINESS_END", 18, raising=False)
    monkeypatch.setattr(settings, "LP_WIDGET_BUSINESS_DAYS", "0,1,2,3,4", raising=False)
    lp_widget._initialized = False

    et = ZoneInfo("America/New_York")
    monday_morning = datetime(2026, 11, 9, 10, 0, tzinfo=et)
    monday_evening = datetime(2026, 11, 9, 19, 0, tzinfo=et)
    saturday = datetime(2026, 11, 14, 12, 0, tzinfo=et)

    online = lp_widget.get_availability(monday_morning)
    assert online["status"] == "online"
    assert online["mode"] == "auto"

    offline = lp_widget.get_availability(monday_evening)
    assert offline["status"] == "offline"
    assert offline["next_open_at"] is not None
    next_open = datetime.fromisoformat(offline["next_open_at"])
    assert next_open.astimezone(et).hour == 8
    assert next_open.astimezone(et).day == 10

    weekend = lp_widget.get_availability(saturday)
    assert weekend["status"] == "offline"
    weekend_next = datetime.fromisoformat(weekend["next_open_at"])
    assert weekend_next.astimezone(et).weekday() == 0
    assert weekend_next.astimezone(et).hour == 8


def test_availability_manual_override():
    result = lp_widget.set_availability("offline", admin_id=42)
    assert result["status"] == "offline"
    assert result["mode"] == "offline"
    assert result["updated_by"] == 42

    result = lp_widget.set_availability("online", admin_id=42)
    assert result["status"] == "online"
    assert result["mode"] == "online"

    result = lp_widget.set_availability("auto", admin_id=42)
    assert result["mode"] == "auto"

    with pytest.raises(ValueError):
        lp_widget.set_availability("always")


def test_ack_includes_offline_notice(monkeypatch):
    sent: list[dict] = []

    def fake_send(to, subject, text, **kwargs):
        sent.append({"to": to, "subject": subject, "text": text})
        return True

    monkeypatch.setattr(lp_widget, "send_email", fake_send)

    lp_widget._send_ack(
        {"id": 12, "email": "lead@example.com", "name": "Mike", "lead_lang": "en"},
        "tok",
        availability={
            "status": "offline",
            "next_open_at": "2026-11-10T08:00:00-05:00",
        },
    )

    assert "outside business hours" in sent[0]["text"]
    assert "next business day" in sent[0]["text"]
    assert "Nov 10" in sent[0]["text"]


def test_create_thread_returns_availability(monkeypatch):
    monkeypatch.setattr(lp_widget, "send_email", lambda *args, **kwargs: True)
    lp_widget.set_availability("offline")

    created = _create()
    assert created["availability"]["status"] == "offline"

    admin = lp_widget.get_thread_admin(created["id"])
    assert admin is not None
    assert admin["status"] == "new"

"""Regressão do ciclo de vida de leads (regra aprovada):

    Reserva 1h  ->  Contactar 48h  ->  Negociar 48h  ->  Convertido (terminal)

Invariantes fixados aqui:

* Reserva (com consentimento) cria uma janela de 1h (`stage_expires_at`).
* `Contactar` abre uma janela NOVA de 48h; re-clicar NÃO estica o prazo.
* `Negociar` abre outra janela NOVA de 48h (não herda o resto da anterior);
  re-clicar NÃO estica.
* `Converter` é terminal: `stage_expires_at` fica NULL e o lead sai do feed
  público de descoberta.
* Estagnação (48h vencidas em `contacted`/`in_negotiation`) devolve o lead ao
  pool geral, marca o reveal como devolvido e NÃO estorna o crédito.
* D2: o acesso aos dados do proprietário NÃO expira na virada do dia UTC —
  sobrevive enquanto o reveal estiver ativo (`returned_to_pool = 0`).
* D3: re-reservar um lead já engajado é no-op de estado (não reverte
  `contacted/in_negotiation/converted` -> `reserved`) e não debita de novo.
* D1: a visibilidade usa POSSE, não `lead_status == 'reserved'`; um lead do
  próprio utilizador aparece como `reserved_by_me` mesmo depois de contactado,
  e nunca como `available` para terceiros.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import backend.main as main_module
from backend.main import _hash_token, _to_lead_response, app
from backend.models.schemas import (
    EnrichedLead,
    IssueCategory,
    SourceType,
    UrgencyLevel,
)
from backend.services.db import db_service, get_connection

EMAIL = "pytest-lead-lifecycle@magicleads.app"
_EXT = {"n": 0}
STAGE_HOURS = 48

OWNER_NAME = "LIFECYCLE OWNER"
OWNER_PHONE = "3475559999"


def _make_lead() -> int:
    _EXT["n"] += 1
    payload = EnrichedLead(
        external_id=f"pytest-lifecycle-{_EXT['n']}",
        source_type=SourceType.SERVICE_311,
        address=f"{_EXT['n']} LIFECYCLE STREET",
        city="BROOKLYN",
        state="NY",
        zip_code="11201",
        lat=None,
        lng=None,
        county="KINGS",
        issue_category=IssueCategory.ROOF,
        issue_description="Building collapse - teste de ciclo de vida",
        urgency_level=UrgencyLevel.HIGH,
        owner_name=OWNER_NAME,
        owner_phone=OWNER_PHONE,
        owner_email="lifecycle@example.com",
        date_reported=datetime(2026, 1, 15, 12, 0, 0),
        image_url=None,
        source_url=None,
    )
    row = db_service._service.insert_lead_new(payload)
    assert row is not None
    return row["id"]


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00").replace(" ", "T"))


@pytest.fixture(scope="module")
def user_and_client():
    svc = db_service._service
    user = svc.get_user_by_email(EMAIL) or svc.create_user(
        EMAIL, "pytest-hash-not-used", "Pytest Lifecycle", plan="pro",
        subscription_status="active",
    )
    assert user is not None
    user_id = user["id"]
    token = "pytest-lead-lifecycle-token"
    svc.create_user_session(user_id, _hash_token(token), "Pytest", None)
    svc.extend_access(user_id, days=7)
    return TestClient(app), {"Authorization": f"Bearer {token}"}, user_id


@pytest.fixture(autouse=True)
def _reset_quota(user_and_client):
    """Zera a cota diária a cada teste: evita dependência de ordem."""
    _, _, user_id = user_and_client
    conn = get_connection()
    try:
        conn.execute("DELETE FROM user_daily_stats WHERE user_id = ?", (user_id,))
        conn.commit()
    finally:
        conn.close()
    yield


def _reveal(user_id: int, lead_id: int, key: str | None = None) -> dict:
    res = db_service._service.reveal_lead(user_id, lead_id, key or f"pytest-lc-{lead_id}")
    assert res and not res.get("error"), res
    return res


def _lead(lead_id: int) -> dict:
    row = db_service._service.get_lead_by_id(lead_id)
    assert row is not None
    return row


def _force_stage_expiry(lead_id: int, past_minutes: int = 5) -> None:
    """Empurra a janela da fase para o passado, para exercitar o sweeper."""
    when = (datetime.utcnow() - timedelta(minutes=past_minutes)).strftime("%Y-%m-%d %H:%M:%S")
    conn = get_connection()
    try:
        conn.execute("UPDATE leads SET stage_expires_at = ? WHERE id = ?", (when, lead_id))
        conn.commit()
    finally:
        conn.close()


def _reveal_row(user_id: int, lead_id: int) -> dict:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM lead_reveals WHERE user_id = ? AND lead_id = ? ORDER BY id DESC LIMIT 1",
            (user_id, lead_id),
        ).fetchone()
        return dict(row) if row else {}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Prazos por fase
# ---------------------------------------------------------------------------
def test_reserve_creates_1h_window(user_and_client):
    _, _, user_id = user_and_client
    lead_id = _make_lead()
    _reveal(user_id, lead_id)

    lead = _lead(lead_id)
    assert lead["lead_status"] == "reserved"
    expires = _parse(lead["stage_expires_at"])
    assert expires is not None, "reserva não definiu stage_expires_at"
    delta = expires - datetime.utcnow()
    assert timedelta(minutes=50) < delta <= timedelta(minutes=61), delta


def test_contact_opens_48h_window(user_and_client):
    _, _, user_id = user_and_client
    lead_id = _make_lead()
    _reveal(user_id, lead_id)

    db_service._service.record_contact(lead_id, user_id, "sms")
    lead = _lead(lead_id)
    assert lead["lead_status"] == "contacted"
    delta = _parse(lead["stage_expires_at"]) - datetime.utcnow()
    assert timedelta(hours=STAGE_HOURS - 1) < delta <= timedelta(hours=STAGE_HOURS), delta


def test_reclick_contact_does_not_extend_window(user_and_client):
    _, _, user_id = user_and_client
    lead_id = _make_lead()
    _reveal(user_id, lead_id)

    db_service._service.record_contact(lead_id, user_id, "sms")
    first = _lead(lead_id)["stage_expires_at"]

    db_service._service.record_contact(lead_id, user_id, "call")
    second = _lead(lead_id)["stage_expires_at"]
    assert first == second, "re-clicar em Contactar esticou o prazo (anti-abuso violado)"


def test_negotiate_opens_new_48h_window(user_and_client):
    _, _, user_id = user_and_client
    lead_id = _make_lead()
    _reveal(user_id, lead_id)
    db_service._service.record_contact(lead_id, user_id, "sms")

    # Curto-circuito: janela de contacto quase a expirar.
    _force_stage_expiry(lead_id, past_minutes=1)
    db_service._service.mark_negotiation(lead_id, user_id)

    lead = _lead(lead_id)
    assert lead["lead_status"] == "in_negotiation"
    delta = _parse(lead["stage_expires_at"]) - datetime.utcnow()
    assert timedelta(hours=STAGE_HOURS - 1) < delta <= timedelta(hours=STAGE_HOURS), delta


def test_reclick_negotiate_does_not_extend_window(user_and_client):
    _, _, user_id = user_and_client
    lead_id = _make_lead()
    _reveal(user_id, lead_id)
    db_service._service.record_contact(lead_id, user_id, "sms")
    db_service._service.mark_negotiation(lead_id, user_id)
    first = _lead(lead_id)["stage_expires_at"]

    db_service._service.mark_negotiation(lead_id, user_id)
    assert _lead(lead_id)["stage_expires_at"] == first


def test_convert_is_terminal(user_and_client):
    _, _, user_id = user_and_client
    lead_id = _make_lead()
    _reveal(user_id, lead_id)
    db_service._service.record_contact(lead_id, user_id, "sms")
    db_service._service.mark_negotiation(lead_id, user_id)

    db_service._service.convert_lead(lead_id, user_id)
    lead = _lead(lead_id)
    assert lead["lead_status"] == "converted"
    assert lead["converted_by"] == user_id
    assert lead["stage_expires_at"] is None, "conversão não limpou o prazo (não é terminal)"


# ---------------------------------------------------------------------------
# Estagnação (48h)
# ---------------------------------------------------------------------------
def test_contact_stagnation_returns_to_pool_without_refund(user_and_client):
    _, _, user_id = user_and_client
    lead_id = _make_lead()
    _reveal(user_id, lead_id)
    db_service._service.record_contact(lead_id, user_id, "sms")
    used_before = db_service._service.get_daily_leads_used(user_id).get("used")

    _force_stage_expiry(lead_id)
    db_service._service.check_reveal_watchdogs()

    lead = _lead(lead_id)
    assert lead["lead_status"] == "available"
    assert lead["reserved_by"] is None
    assert _reveal_row(user_id, lead_id)["returned_to_pool"] == 1
    assert _reveal_row(user_id, lead_id)["refunded"] in (0, None), "estagnação estornou crédito"
    assert db_service._service.get_daily_leads_used(user_id).get("used") == used_before


def test_negotiation_stagnation_returns_to_pool(user_and_client):
    _, _, user_id = user_and_client
    lead_id = _make_lead()
    _reveal(user_id, lead_id)
    db_service._service.record_contact(lead_id, user_id, "sms")
    db_service._service.mark_negotiation(lead_id, user_id)

    _force_stage_expiry(lead_id)
    db_service._service.check_reveal_watchdogs()

    lead = _lead(lead_id)
    assert lead["lead_status"] == "available"
    assert lead["reserved_by"] is None
    assert _reveal_row(user_id, lead_id)["returned_to_pool"] == 1


def test_engaged_leads_are_not_touched_by_1h_watchdog(user_and_client):
    """Um lead contactado com prazo de 48h NÃO pode voltar ao pool pelo job de 1h."""
    _, _, user_id = user_and_client
    lead_id = _make_lead()
    _reveal(user_id, lead_id)
    db_service._service.record_contact(lead_id, user_id, "sms")

    # 61 min desde a reserva, sem tocar no prazo da fase (48h).
    conn = get_connection()
    try:
        past = (datetime.utcnow() - timedelta(minutes=61)).strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("UPDATE lead_reveals SET revealed_at = ? WHERE lead_id = ? AND user_id = ?", (past, lead_id, user_id))
        conn.execute("UPDATE leads SET reserved_until = ? WHERE id = ?", (past, lead_id))
        conn.commit()
    finally:
        conn.close()

    db_service._service.check_reveal_watchdogs()
    assert _lead(lead_id)["lead_status"] == "contacted", "watchdog de 1h clobberou um lead engajado"


# ---------------------------------------------------------------------------
# Release -> re-reserva (o release devolve o reveal ao pool)
# ---------------------------------------------------------------------------
def test_release_returns_reveal_to_pool_and_allows_rereserve(user_and_client):
    """Liberar devolve o reveal ao pool: re-reservar volta a criar hold e a contar.

    Bug em produção: o release marcava o lead como available mas NÃO tocava em
    `lead_reveals.returned_to_pool`; ao re-reservar, o ramo de idempotência do
    `reveal_lead` achava o reveal "ativo" e devolvia o lead available SEM criar
    hold (o frontend abria o guia com countdown 00:00).
    """
    _, _, user_id = user_and_client
    lead_id = _make_lead()
    _reveal(user_id, lead_id)
    assert _lead(lead_id)["lead_status"] == "reserved"

    db_service._service.release_lead(lead_id, user_id, reason="other", note="teste")
    assert _lead(lead_id)["lead_status"] == "available"
    assert _reveal_row(user_id, lead_id)["returned_to_pool"] == 1, (
        "release não devolveu o reveal ao pool: re-reserva ficaria presa no no-op"
    )

    again = db_service._service.reveal_lead(user_id, lead_id, f"pytest-rereserve-{lead_id}")
    assert again and not again.get("error"), again
    assert again.get("idempotent") is not True, "re-reserva após release não criou novo reveal"
    lead = _lead(lead_id)
    assert lead["lead_status"] == "reserved", lead["lead_status"]
    assert lead["stage_expires_at"], "re-reserva após release não abriu nova janela de fase"


# ---------------------------------------------------------------------------
# D2 — acesso não expira na virada do dia UTC
# ---------------------------------------------------------------------------
def test_access_survives_utc_day_change(user_and_client):
    _, _, user_id = user_and_client
    lead_id = _make_lead()
    _reveal(user_id, lead_id)

    # Simula reveal criado "ontem".
    conn = get_connection()
    try:
        yesterday = (datetime.utcnow().date() - timedelta(days=1)).isoformat()
        conn.execute(
            "UPDATE lead_reveals SET revealed_date = ? WHERE lead_id = ? AND user_id = ?",
            (yesterday, lead_id, user_id),
        )
        conn.commit()
    finally:
        conn.close()

    active = db_service._service.get_revealed_ids(user_id, [lead_id])
    assert lead_id in active, "acesso pago expirou na virada do dia UTC (D2)"

    lead = _lead(lead_id)
    lead["_revealed"] = True
    assert _to_lead_response(dict(lead)).owner_phone == OWNER_PHONE


def test_next_day_reserve_does_not_recharge(user_and_client):
    _, _, user_id = user_and_client
    lead_id = _make_lead()
    res = _reveal(user_id, lead_id)
    assert res.get("counted_again") is True or res.get("idempotent") is not True
    used_after_first = db_service._service.get_daily_leads_used(user_id).get("used")

    conn = get_connection()
    try:
        yesterday = (datetime.utcnow().date() - timedelta(days=1)).isoformat()
        conn.execute(
            "UPDATE lead_reveals SET revealed_date = ? WHERE lead_id = ? AND user_id = ?",
            (yesterday, lead_id, user_id),
        )
        conn.commit()
    finally:
        conn.close()

    again = db_service._service.reveal_lead(user_id, lead_id, f"pytest-nextday-{lead_id}")
    assert again and not again.get("error"), again
    assert again.get("counted_again") is False, "re-reserva no dia seguinte debitou de novo (D2)"
    assert db_service._service.get_daily_leads_used(user_id).get("used") == used_after_first


# ---------------------------------------------------------------------------
# D3 — re-reservar não reverte o estado engajado nem debita de novo
# ---------------------------------------------------------------------------
def test_reserve_does_not_revert_engaged_state(user_and_client):
    _, _, user_id = user_and_client
    lead_id = _make_lead()
    _reveal(user_id, lead_id)
    db_service._service.record_contact(lead_id, user_id, "sms")

    again = db_service._service.reveal_lead(user_id, lead_id, f"pytest-revert-{lead_id}")
    assert again and not again.get("error"), again
    assert again.get("counted_again") is False
    assert _lead(lead_id)["lead_status"] == "contacted", "re-reserva reverteu contacted -> reserved (D3)"


def test_reserve_does_not_revert_converted(user_and_client):
    _, _, user_id = user_and_client
    lead_id = _make_lead()
    _reveal(user_id, lead_id)
    db_service._service.record_contact(lead_id, user_id, "sms")
    db_service._service.convert_lead(lead_id, user_id)

    again = db_service._service.reveal_lead(user_id, lead_id, f"pytest-conv-{lead_id}")
    assert again and not again.get("error"), again
    assert again.get("counted_again") is False
    assert _lead(lead_id)["lead_status"] == "converted", "re-reserva reverteu conversão (D3)"


# ---------------------------------------------------------------------------
# D1 — visibilidade por posse
# ---------------------------------------------------------------------------
def test_visibility_is_reserved_by_me_after_contact(user_and_client):
    _, _, user_id = user_and_client
    lead_id = _make_lead()
    _reveal(user_id, lead_id)
    db_service._service.record_contact(lead_id, user_id, "sms")

    lead = dict(_lead(lead_id))
    asyncio.run(main_module._annotate_visibility([lead], {"id": user_id}))
    resp = _to_lead_response(lead)
    assert resp.visibility_status == "reserved_by_me", resp.visibility_status
    assert resp.owner_phone == OWNER_PHONE
    assert resp.stage_expires_at is not None
    assert resp.my_status == "negotiating"


def test_engaged_lead_never_shows_available_to_others(user_and_client):
    _, _, user_id = user_and_client
    lead_id = _make_lead()
    _reveal(user_id, lead_id)
    db_service._service.record_contact(lead_id, user_id, "sms")

    # Terceiro (sem posse) — a resposta NUNCA pode dizer "available".
    lead = dict(_lead(lead_id))
    asyncio.run(main_module._annotate_visibility([lead], None))
    resp = _to_lead_response(lead)
    assert resp.visibility_status == "reserved_by_other", resp.visibility_status
    assert resp.owner_phone is None


def test_public_feed_hides_others_engaged_leads(user_and_client):
    _, _, user_a = user_and_client
    lead_id = _make_lead()
    _reveal(user_a, lead_id)
    db_service._service.record_contact(lead_id, user_a, "sms")

    # B é terceiro: não deve ver o lead ocupado nem em "available".
    holder = dict(_lead(lead_id))
    third_party = dict(_lead(lead_id))
    out = main_module._filter_public_leads([holder], {"id": user_a + 999})
    assert out == [], "feed criou vazamento de lead engajado para terceiros"

    # O dono continua vendo o lead em andamento.
    mine = main_module._filter_public_leads([third_party], {"id": user_a})
    assert len(mine) == 1


def test_converted_lead_leaves_public_feed_for_everyone(user_and_client):
    _, _, user_a = user_and_client
    lead_id = _make_lead()
    _reveal(user_a, lead_id)
    db_service._service.record_contact(lead_id, user_a, "sms")
    db_service._service.convert_lead(lead_id, user_a)

    converted = dict(_lead(lead_id))
    assert converted["lead_status"] == "converted"
    out = main_module._filter_public_leads([converted], {"id": user_a})
    assert out == [], "lead convertido não saiu do feed de descoberta"

    # Mas continua disponível nos Meus Leads com visibilidade do dono.
    asyncio.run(main_module._annotate_visibility([converted], {"id": user_a}))
    resp = _to_lead_response(converted)
    assert resp.visibility_status == "reserved_by_me"
    assert resp.my_status == "converted"
    assert resp.owner_phone == OWNER_PHONE

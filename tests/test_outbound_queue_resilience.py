"""Resiliência da fila outbound: head-of-line, spillover e diagnóstico.

Regressões cobertas:
  * uma cidade com envio desligado NÃO pode parar o tick das outras;
  * uma cidade sem caixa própria usa caixas globais/outras com folga;
  * o `/outbound/status` e a Control Tower explicam o bloqueio (cap/warm-up,
    quiet hours, cidade desligada) em vez de só dizer "queue_age falhou".
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from backend.services import control_tower
from backend.services import outbound_engine as engine_module
from backend.services.db import get_connection
from backend.services.gmail import SendResult
from backend.services.outbound_engine import (
    OutboundEngine,
    mailbox_matches_city,
    next_utc_midnight,
)

NOW = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)


@pytest.fixture()
def clean_engine() -> OutboundEngine:
    conn = get_connection()
    try:
        for table in (
            "outbound_messages",
            "outbound_batches",
            "outbound_contacts",
            "sending_mailboxes",
            "outbound_daily_counters",
        ):
            conn.execute(f"DELETE FROM {table}")
        conn.commit()
    finally:
        conn.close()
    return OutboundEngine()


def _svc():
    return engine_module.db_service._service


def _config(**values: str) -> None:
    svc = _svc()
    # Base limpa e determinística: sem warm-up e sem quiet hours.
    svc.set_outbound_config("warmup_enabled", values.pop("warmup_enabled", "0"))
    svc.set_outbound_config("per_mailbox_daily_cap", "25")
    svc.set_outbound_config("quiet_hours_start", "00:00")
    svc.set_outbound_config("quiet_hours_end", "00:00")
    for key, value in values.items():
        svc.set_outbound_config(key, value)


def _mailbox(email: str, city: str = "", daily_cap: int = 5) -> dict:
    _svc().upsert_sending_mailbox(
        email=email,
        provider="gmail",
        transport="gmail_api",
        display_name="MagicLeads",
        city=city,
        daily_cap=daily_cap,
        enabled=1,
        warmup_state="warm",
        auth_ref=json.dumps({"client_id": "c", "client_secret": "s", "refresh_token": "r"}),
    )
    return [m for m in _svc().list_sending_mailboxes(enabled_only=True) if m["email"] == email][0]


def _lead(city: str, external_id: str, address: str) -> int:
    from backend.models.schemas import (
        EnrichedLead,
        IssueCategory,
        SourceType,
        UrgencyLevel,
    )

    row = _svc().insert_lead_new(
        EnrichedLead(
            external_id=external_id,
            source_type=SourceType.SERVICE_311,
            address=address,
            city=city,
            state="NY",
            zip_code="10001",
            lat=None,
            lng=None,
            county="KINGS",
            issue_category=IssueCategory.ROOF,
            issue_description="outbound resilience",
            urgency_level=UrgencyLevel.MEDIUM,
            case_status="open",
            owner_name="VITORIO CONTRACTING LLC",
            owner_phone="3475550111",
            owner_email="seed@example.com",
            date_reported=datetime(2026, 1, 15, 12, 0, 0),
            image_url=None,
            source_url=None,
        )
    )
    assert row is not None
    return row["id"]


def _contact(lead_id: int, email: str, city: str) -> dict:
    contact = _svc().upsert_outbound_contact(
        lead_id=lead_id,
        email=email,
        city=city,
        state="NY",
        company_name="VITORIO CONTRACTING LLC",
        email_source="manual",
        email_status="valid",
    )
    _svc().set_contact_niche(contact["id"], "general_contractors", "confirmed")
    _svc().set_lead_niche(lead_id, "general_contractors", "confirmed")
    return contact


def _queue(city: str, email: str) -> dict:
    msg = _svc().enqueue_outbound_message(
        batch_id=None,
        contact_id=None,
        city=city,
        to_email=email,
        subject="Quick question",
        body_hash="h",
    )
    assert msg is not None
    return msg


class FakeGmail:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send(self, mailbox, to_email, subject, body, from_name=None):
        self.sent.append(to_email)
        return SendResult(success=True, provider_id="fake", http_status=200)


def test_mailbox_city_match_rules():
    assert mailbox_matches_city("", "CHICAGO")
    assert mailbox_matches_city("CHICAGO", "chicago")
    assert mailbox_matches_city("NYC", "CHICAGO") is False
    # Mensagem sem cidade aceita qualquer caixa (lotes antigos).
    assert mailbox_matches_city("NYC", "")


def test_next_utc_midnight_is_next_day():
    assert next_utc_midnight(NOW) == "2026-11-01 00:00:00"


@pytest.mark.asyncio
async def test_disabled_city_does_not_block_other_cities(clean_engine, monkeypatch):
    """Head-of-line: a mensagem mais antiga é de uma cidade desligada."""
    _config(send_enabled="1", warmup_enabled="0")
    _svc().set_outbound_config("send_enabled", "0", city="CHICAGO")
    _mailbox("global@example.com")

    chi_lead = _lead("CHICAGO", "res-chi-1", "1 CHICAGO AVE")
    bos_lead = _lead("BOSTON", "res-bos-1", "1 BOSTON AVE")
    _contact(chi_lead, "chi@vitorio.com", "CHICAGO")
    _contact(bos_lead, "bos@vitorio.com", "BOSTON")

    _queue("CHICAGO", "chi@vitorio.com")   # id menor: viria primeiro
    _queue("BOSTON", "bos@vitorio.com")

    fake = FakeGmail()
    monkeypatch.setattr(engine_module, "gmail_sender", fake)
    monkeypatch.setattr(engine_module, "is_quiet_hours", lambda *a, **k: False)

    result = await clean_engine.process_queue(now=NOW)
    assert fake.sent == ["bos@vitorio.com"], result
    assert result["sent"] == 1
    assert result["deferred"] >= 1
    assert result["blocked_cities"]["CHICAGO"] == "city_send_disabled"
    # A mensagem de Chicago continua na fila, não foi apagada nem falhada.
    assert _svc().count_outbound_messages(status="queued", batch_id=None) == 1


@pytest.mark.asyncio
async def test_spillover_uses_idle_mailbox_from_another_city(clean_engine, monkeypatch):
    """Cidade sem caixa própria usa uma caixa global/outra com folga."""
    _config(send_enabled="1", warmup_enabled="0")
    _mailbox("nyc-box@example.com", city="NYC")

    bos_lead = _lead("BOSTON", "res-bos-2", "2 BOSTON AVE")
    _contact(bos_lead, "bos2@vitorio.com", "BOSTON")
    _queue("BOSTON", "bos2@vitorio.com")

    fake = FakeGmail()
    monkeypatch.setattr(engine_module, "gmail_sender", fake)
    monkeypatch.setattr(engine_module, "is_quiet_hours", lambda *a, **k: False)

    result = await clean_engine.process_queue(now=NOW)
    assert fake.sent == ["bos2@vitorio.com"], result
    assert result["sent"] == 1


@pytest.mark.asyncio
async def test_send_exception_does_not_kill_the_tick(clean_engine, monkeypatch):
    """Uma exceção da Gmail marca a mensagem failed e o tick continua."""
    _config(send_enabled="1", warmup_enabled="0")
    _mailbox("boom@example.com")

    first = _lead("BOSTON", "res-bos-5", "5 BOSTON AVE")
    second = _lead("BOSTON", "res-bos-6", "6 BOSTON AVE")
    _contact(first, "boom@vitorio.com", "BOSTON")
    _contact(second, "ok@vitorio.com", "BOSTON")
    _queue("BOSTON", "boom@vitorio.com")
    _queue("BOSTON", "ok@vitorio.com")

    class FlakyGmail:
        def __init__(self) -> None:
            self.sent: list[str] = []

        async def send(self, mailbox, to_email, subject, body, from_name=None):
            if to_email == "boom@vitorio.com":
                raise RuntimeError("gmail down")
            self.sent.append(to_email)
            return SendResult(success=True, provider_id="ok", http_status=200)

    fake = FlakyGmail()
    monkeypatch.setattr(engine_module, "gmail_sender", fake)
    monkeypatch.setattr(engine_module, "is_quiet_hours", lambda *a, **k: False)

    result = await clean_engine.process_queue(now=NOW)
    assert result["failed"] == 1
    assert result["sent"] == 1
    assert fake.sent == ["ok@vitorio.com"]


@pytest.mark.asyncio
async def test_reaper_runs_even_when_send_is_disabled(clean_engine, monkeypatch):
    """Deploy com envio desligado não deixa linhas presas em 'sending'."""
    _config(send_enabled="0")
    msg = _queue("BOSTON", "stale@vitorio.com")
    _svc().claim_outbound_message(msg["id"])  # queued -> sending
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE outbound_messages SET claimed_at='2026-10-30 00:00:00' WHERE id=?",
            (msg["id"],),
        )
        conn.commit()
    finally:
        conn.close()

    result = await clean_engine.process_queue(now=NOW)
    assert result["status"] == "disabled"
    assert result["blocked_reason"] == "send_enabled_off"
    assert _svc().get_outbound_message(msg["id"])["status"] == "failed"


@pytest.mark.asyncio
async def test_cap_por_caixa_e_respeitado_no_mesmo_tick(clean_engine, monkeypatch):
    """Regressão 995007d: o snapshot não podia ser copiado.

    Uma caixa com cap 1 e duas mensagens na mesma cidade tem de enviar UMA e
    deixar a outra na fila. Antes, `_pick_mailbox` devolvia `dict(pool[0])` e o
    consumo de folga não era visível ao próximo pedido do mesmo tick.
    """
    _config(send_enabled="1", warmup_enabled="0")
    _mailbox("cap1@example.com", daily_cap=1)

    first = _lead("BOSTON", "cap-bos-1", "1 CAP AVE")
    second = _lead("BOSTON", "cap-bos-2", "2 CAP AVE")
    _contact(first, "one@vitorio.com", "BOSTON")
    _contact(second, "two@vitorio.com", "BOSTON")
    _queue("BOSTON", "one@vitorio.com")
    _queue("BOSTON", "two@vitorio.com")

    fake = FakeGmail()
    monkeypatch.setattr(engine_module, "gmail_sender", fake)
    monkeypatch.setattr(engine_module, "is_quiet_hours", lambda *a, **k: False)

    result = await clean_engine.process_queue(now=NOW)
    assert result["sent"] == 1, result
    assert len(fake.sent) == 1
    assert result.get("blocked_reason") == "mailbox_cap"
    assert _svc().count_outbound_messages(status="queued", batch_id=None) == 1


@pytest.mark.asyncio
async def test_duas_caixas_cap1_alternam_sem_overshoot(clean_engine, monkeypatch):
    """Com duas caixas cap 1, cada uma envia uma — e nenhuma envia duas."""
    _config(send_enabled="1", warmup_enabled="0")
    _mailbox("a@example.com", daily_cap=1)
    _mailbox("b@example.com", daily_cap=1)

    for i in range(1, 4):
        lead = _lead("BOSTON", f"cap2-bos-{i}", f"{i} CAP TWO AVE")
        _contact(lead, f"c{i}@vitorio.com", "BOSTON")
        _queue("BOSTON", f"c{i}@vitorio.com")

    fake = FakeGmail()
    monkeypatch.setattr(engine_module, "gmail_sender", fake)
    monkeypatch.setattr(engine_module, "is_quiet_hours", lambda *a, **k: False)

    result = await clean_engine.process_queue(now=NOW)
    assert result["sent"] == 2, result
    assert len(fake.sent) == 2
    assert _svc().count_outbound_messages(status="queued", batch_id=None) == 1


def test_mailbox_health_conta_enviados_e_falhas(clean_engine):
    _config(send_enabled="1", warmup_enabled="0")
    box = _mailbox("health@example.com", daily_cap=5)
    msg = _queue("BOSTON", "health@vitorio.com")
    _svc().update_outbound_message(
        msg["id"],
        status="sent",
        mailbox_id=box["id"],
        sent_at=NOW.strftime("%Y-%m-%d %H:%M:%S"),
    )
    bad = _queue("BOSTON", "bad@vitorio.com")
    _svc().update_outbound_message(
        bad["id"], status="failed", mailbox_id=box["id"], error="boom"
    )

    rows = _svc().outbound_mailbox_health(48)
    row = next(r for r in rows if r["email"] == "health@example.com")
    assert row["sent"] == 1
    assert row["failed"] == 1
    assert row["last_error"] == "boom"


@pytest.mark.asyncio
async def test_status_reports_mailbox_cap_blocker(clean_engine, monkeypatch):
    _config(send_enabled="1", warmup_enabled="0")
    box = _mailbox("cap@example.com", daily_cap=1)

    lead = _lead("BOSTON", "res-bos-3", "3 BOSTON AVE")
    _contact(lead, "cap@vitorio.com", "BOSTON")
    _queue("BOSTON", "cap@vitorio.com")

    # Consome o único envio do dia nesta caixa.
    _svc().enqueue_outbound_message(
        batch_id=None, contact_id=None, city="BOSTON", to_email="done@vitorio.com",
        subject="s", body_hash="h",
    )
    sent = _svc().list_queued_outbound_messages(limit=10)[-1]
    _svc().update_outbound_message(
        sent["id"], status="sent", mailbox_id=box["id"], sent_at=NOW.strftime("%Y-%m-%d %H:%M:%S")
    )

    status = await clean_engine.status()
    assert status["mailbox_remaining_today"] == 0
    assert status["queue_blocker"]["reason"] == "mailbox_cap"
    assert "warm-up" in status["queue_blocker"]["detail"]
    assert status["queue_blocker"]["retry_at"].endswith("00:00:00")
    # A caixa expõe a folga nas linhas (a UI mostra "restam 0").
    assert status["mailboxes"][0]["remaining_today"] == 0


def test_control_tower_explains_cap_instead_of_failing(clean_engine):
    _config(send_enabled="1", warmup_enabled="0", per_mailbox_daily_cap="25")
    box = _mailbox("ct@example.com", daily_cap=1)

    lead = _lead("BOSTON", "res-bos-4", "4 BOSTON AVE")
    _contact(lead, "ct@vitorio.com", "BOSTON")
    msg = _queue("BOSTON", "ct@vitorio.com")
    # Fila com 60h.
    old = (NOW - timedelta(hours=60)).strftime("%Y-%m-%d %H:%M:%S")
    conn = get_connection()
    try:
        conn.execute("UPDATE outbound_messages SET queued_at=? WHERE id=?", (old, msg["id"]))
        conn.commit()
    finally:
        conn.close()

    # Com cap=1 e 0 enviados, há capacidade -> fila velha é falha real.
    checks = {c["name"]: c for c in control_tower._check_queue()}
    assert checks["queue_age"]["status"] == "fail"
    assert "capacidade" in checks["queue_age"]["detail"]

    # Consome a única unidade do dia -> passa a ser backpressure explicado.
    _svc().enqueue_outbound_message(
        batch_id=None, contact_id=None, city="BOSTON", to_email="done2@vitorio.com",
        subject="s", body_hash="h",
    )
    done = _svc().list_queued_outbound_messages(limit=10)[-1]
    _svc().update_outbound_message(
        done["id"], status="sent", mailbox_id=box["id"], sent_at=NOW.strftime("%Y-%m-%d %H:%M:%S")
    )

    checks = {c["name"]: c for c in control_tower._check_queue()}
    assert checks["queue_age"]["status"] == "warn"
    assert "limite de caixa" in checks["queue_age"]["detail"]

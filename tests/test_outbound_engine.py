"""Testes do motor de envio real (Outbound Frio - Fase 2).

Cobrem as travas anti-spam e anti-abuso (quiet hours, warm-up, tetos), a
regra de so' aceitar e-mails `valid`, e o pipeline enqueue -> worker sem
tocar na rede real (Snov/Gmail mockados).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from backend.main import _outbound_worker_loop  # noqa: F401  (importa o app)
from backend.services import outbound_engine as engine_module
from backend.services.db import get_connection
from backend.services.gmail import SendResult, build_raw_message, parse_auth_ref
from backend.services.outbound_engine import (
    OutboundEngine,
    effective_mailbox_cap,
    is_quiet_hours,
    warmup_days,
)
from backend.services.snov import (
    SnovService,
    _extract_email_records,
    _extract_verification,
    email_domain,
    normalize_email,
)

# ------------------------------------------------------------------ pure helpers


def test_is_quiet_hours_inside_wrapped_window():
    # Janela 22:00-07:00 (wrap). 23:30 esta' dentro; 12:00 nao.
    assert is_quiet_hours(
        datetime(2026, 10, 19, 23, 30, tzinfo=timezone.utc), "22:00", "07:00"
    )
    assert not is_quiet_hours(
        datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc), "22:00", "07:00"
    )


def test_is_quiet_hours_inside_plain_window_and_invalid_values():
    assert is_quiet_hours(
        datetime(2026, 10, 19, 9, 30, tzinfo=timezone.utc), "08:00", "18:00"
    )
    assert not is_quiet_hours(
        datetime(2026, 10, 19, 19, 0, tzinfo=timezone.utc), "08:00", "18:00"
    )
    # Valores invalidos nao bloqueiam envio.
    assert not is_quiet_hours(
        datetime(2026, 10, 19, 23, 0, tzinfo=timezone.utc), None, "07:00"
    )
    assert not is_quiet_hours(
        datetime(2026, 10, 19, 23, 0, tzinfo=timezone.utc), "25:00", "07:00"
    )
    assert not is_quiet_hours(
        datetime(2026, 10, 19, 23, 0, tzinfo=timezone.utc), "22:00", "22:00"
    )


def test_warmup_ramp_starts_at_one_and_reaches_cap():
    now = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)
    config = {"warmup_enabled": "1", "min_warmup_days": "14", "per_mailbox_daily_cap": "25"}
    # Dia 0 (sem registo) -> teto minimo de 1.
    assert effective_mailbox_cap({"daily_cap": 25}, config, now) == 1
    # Dia 13 (24h de registo) -> 25*14/14 = 25.
    assert effective_mailbox_cap(
        {"daily_cap": 25, "warmup_started_at": "2026-10-06 12:00:00"}, config, now
    ) == 25
    # Warm-up desligado -> teto cheio.
    config_off = dict(config, warmup_enabled="0")
    assert effective_mailbox_cap({"daily_cap": 25}, config_off, now) == 25


def test_warmup_disabled_keeps_cap_even_on_day_zero():
    now = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)
    config = {"warmup_enabled": "0", "min_warmup_days": "14", "per_mailbox_daily_cap": "25"}
    assert effective_mailbox_cap({"daily_cap": 25}, config, now) == 25


def test_warmup_days_handles_missing_and_formats():
    now = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)
    assert warmup_days(None, now) == 0
    assert warmup_days("", now) == 0
    assert warmup_days("2026-10-19 11:00:00", now) == 0
    assert warmup_days("2026-10-10 11:00:00", now) == 9


# ------------------------------------------------------------------ gmail helpers


def test_build_raw_message_is_base64url_with_headers():
    import base64

    raw = build_raw_message(
        "ops@example.com", "Quick question", "Hello there.", "sender@example.com", "Magic"
    )
    decoded = base64.urlsafe_b64decode(raw).decode("utf-8")
    assert "To: ops@example.com" in decoded
    assert "Subject: Quick question" in decoded
    assert "From: Magic <sender@example.com>" in decoded
    assert "Hello there." in decoded


def test_parse_auth_ref_handles_json_and_garbage():
    assert parse_auth_ref(None) == {}
    assert parse_auth_ref("not-json") == {}
    assert parse_auth_ref(json.dumps({"client_id": "a", "refresh_token": "b"})) == {
        "client_id": "a",
        "refresh_token": "b",
    }


@pytest.mark.asyncio
async def test_gmail_send_fails_closed_without_credentials():
    from backend.services.gmail import GmailSender

    sender = GmailSender()
    result = await sender.send(
        {"email": "sender@example.com", "auth_ref": None},
        "ops@example.com",
        "Subject",
        "Body",
    )
    assert result.success is False
    assert "configured" in (result.error or "")
    await sender.aclose()


# ------------------------------------------------------------------ snov client


def test_normalize_email_and_domain_helpers():
    assert normalize_email(" Ops@Example.COM ") == "ops@example.com"
    assert normalize_email("nope") is None
    assert normalize_email(None) is None
    assert email_domain("ops@example.com") == "example.com"
    # Webmail publico nao identifica empresa -> None.
    assert email_domain("ops@gmail.com") is None
    assert email_domain(None) is None


def test_snov_extraction_handles_shapes():
    assert _extract_verification({"data": {"ops@x.com": {"status": "valid"}}}, "ops@x.com") == "valid"
    assert _extract_verification({"result": [{"email": "ops@x.com", "status": "invalid"}]}, "ops@x.com") == "invalid"
    assert _extract_verification(None, "ops@x.com") is None
    records = _extract_email_records({"emails": [{"email": "a@x.com", "status": "valid"}]})
    assert records and records[0]["email"] == "a@x.com"
    assert _extract_email_records({}) == []


def _configured_snov() -> SnovService:
    svc = SnovService()
    svc.client_id = "cid"
    svc.client_secret = "sec"
    return svc


@pytest.mark.asyncio
async def test_snov_unconfigured_is_fail_soft(monkeypatch):
    svc = SnovService()
    assert svc.configured is False
    result = await svc.find_and_verify(owner_email="ops@example.com")
    assert result.success is False
    assert result.outcome == "not_configured"
    await svc.aclose()


@pytest.mark.asyncio
async def test_snov_only_accepts_valid_status(monkeypatch):
    svc = _configured_snov()
    calls: list[str] = []

    async def fake_post(path, payload):
        calls.append(path)
        if "verification-status" in path:
            return {"data": {payload["emails"][0]: {"status": "unknown"}}}, 200
        if "get-emails-from-names" in path:
            return {"emails": [{"email": "ops@x.com", "status": "unknown"}]}, 200
        return None, 200

    monkeypatch.setattr(svc, "_post", fake_post)
    result = await svc.find_and_verify(
        owner_email=None, contact_name="Maria Souza", domain="x.com"
    )
    assert result.success is False
    assert result.status == "unknown"
    assert result.outcome == "invalid_email"
    assert result.billed_calls == 1
    await svc.aclose()


@pytest.mark.asyncio
async def test_snov_accepts_valid_email_and_bills(monkeypatch):
    svc = _configured_snov()

    async def fake_post(path, payload):
        if "verification-status" in path:
            return {"data": {payload["emails"][0]: {"status": "valid"}}}, 200
        return None, 200

    monkeypatch.setattr(svc, "_post", fake_post)
    result = await svc.find_and_verify(owner_email="ops@x.com")
    assert result.success is True
    assert result.email == "ops@x.com"
    assert result.status == "valid"
    assert result.spend_usd == pytest.approx(svc.per_email_usd)
    await svc.aclose()


@pytest.mark.asyncio
async def test_snov_without_domain_is_no_domain():
    svc = _configured_snov()
    result = await svc.find_and_verify(
        owner_email=None, company_name="PRIME 80 LLC", contact_name="PRIME 80 LLC"
    )
    assert result.success is False
    assert result.outcome == "no_domain"
    assert result.billed_calls == 0
    await svc.aclose()


# ------------------------------------------------------------------ engine


@pytest.fixture()
def engine() -> OutboundEngine:
    """Isola o dominio outbound (BOSTON nao e' usado pelos outros testes)."""
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
        conn.execute("DELETE FROM leads WHERE UPPER(city)='BOSTON'")
        conn.commit()
    finally:
        conn.close()
    return OutboundEngine()


def _seed_mailbox(city: str = "") -> dict:
    svc = engine_module.db_service._service
    svc.upsert_sending_mailbox(
        email=f"sender-{city or 'global'}@example.com",
        provider="gmail",
        transport="gmail_api",
        display_name="MagicLeads Outreach",
        city=city,
        daily_cap=5,
        enabled=1,
        warmup_state="cold",
        auth_ref=json.dumps({"client_id": "c", "client_secret": "s", "refresh_token": "r"}),
    )
    rows = svc.list_sending_mailboxes(enabled_only=True)
    return rows[-1]


def _seed_contact(lead_id: int, email: str, city: str = "BOSTON") -> dict:
    svc = engine_module.db_service._service
    contact = svc.upsert_outbound_contact(
        lead_id=lead_id,
        email=email,
        city=city,
        state="NY",
        company_name="VITORIO CONTRACTING LLC",
        email_source="manual",
        email_status="valid",
    )
    # Gate de nicho: sem nicho confirmado o motor nao envia.
    if contact:
        svc.set_contact_niche(contact["id"], "general_contractors", "confirmed")
        if lead_id:
            svc.set_lead_niche(lead_id, "general_contractors", "confirmed")
    return contact


def _seed_lead(city: str, external_id: str, address: str) -> int:
    from backend.models.schemas import (
        EnrichedLead,
        IssueCategory,
        SourceType,
        UrgencyLevel,
    )

    payload = EnrichedLead(
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
        issue_description="outbound engine seed",
        urgency_level=UrgencyLevel.MEDIUM,
        case_status="open",
        owner_name="VITORIO CONTRACTING LLC",
        owner_phone="3475550111",
        owner_email="seed@example.com",
        date_reported=datetime(2026, 1, 15, 12, 0, 0),
        image_url=None,
        source_url=None,
    )
    row = engine_module.db_service._service.insert_lead_new(payload)
    assert row is not None
    return row["id"]


def _set_config(**values: str) -> None:
    svc = engine_module.db_service._service
    for key, value in values.items():
        svc.set_outbound_config(key, value, city="")


@pytest.mark.asyncio
async def test_engine_enqueue_requires_valid_contact_without_enrichment(engine, monkeypatch):
    """Sem `enrich_enabled` e sem contacto validado, nada e' enfileirado."""
    svc = engine_module.db_service._service
    _seed_lead("BOSTON", "engine-1", "1 ENGINE AVENUE")
    batch = svc.create_outbound_batch(
        city="BOSTON", name="engine-1", filters_json=json.dumps({"city": "BOSTON"}), kind="email"
    )
    svc.mark_outbound_batch_previewed(batch["id"], 1, 0.0)
    batch = svc.get_outbound_batch(batch["id"])

    _set_config(send_enabled="1", enrich_enabled="0")
    try:
        result = await engine.enqueue_batch(batch)
        assert result["queued"] == 0
        assert result["no_email"] == 1
        assert svc.count_outbound_messages(status="queued", batch_id=batch["id"]) == 0
    finally:
        _set_config(send_enabled="0")


@pytest.mark.asyncio
async def test_engine_enqueue_enqueues_only_valid_contact(engine):
    svc = engine_module.db_service._service
    lead_id = _seed_lead("BOSTON", "engine-2", "2 ENGINE AVENUE")
    _seed_contact(lead_id, "ops@vitorio.com")
    batch = svc.create_outbound_batch(
        city="BOSTON", name="engine-2", filters_json=json.dumps({"city": "BOSTON"}), kind="email"
    )
    svc.mark_outbound_batch_previewed(batch["id"], 1, 0.0)
    batch = svc.get_outbound_batch(batch["id"])

    _set_config(send_enabled="1", enrich_enabled="0")
    try:
        result = await engine.enqueue_batch(batch)
        assert result["queued"] == 1
        assert svc.count_outbound_messages(status="queued", batch_id=batch["id"]) == 1
    finally:
        _set_config(send_enabled="0")


@pytest.mark.asyncio
async def test_engine_worker_is_disabled_and_respects_quiet_hours(engine, monkeypatch):
    _set_config(send_enabled="0")
    assert (await engine.process_queue())["status"] == "disabled"

    _set_config(send_enabled="1")
    try:
        # Quiet hours forcados: o tick nao envia.
        monkeypatch.setattr(engine_module, "is_quiet_hours", lambda *a, **k: True)
        assert (await engine.process_queue())["status"] == "quiet_hours"
    finally:
        _set_config(send_enabled="0")


@pytest.mark.asyncio
async def test_engine_worker_sends_and_respects_caps(engine, monkeypatch):
    svc = engine_module.db_service._service
    _seed_mailbox()
    lead_id = _seed_lead("BOSTON", "engine-3", "3 ENGINE AVENUE")
    _seed_contact(lead_id, "ops3@vitorio.com")
    batch = svc.create_outbound_batch(
        city="BOSTON", name="engine-3", filters_json=json.dumps({"city": "BOSTON"}), kind="email"
    )
    svc.mark_outbound_batch_previewed(batch["id"], 1, 0.0)
    batch = svc.start_outbound_batch(batch["id"])

    _set_config(send_enabled="1", enrich_enabled="0")
    await engine.enqueue_batch(batch)
    assert svc.count_outbound_messages(status="queued") == 1

    # Quiet hours falsos: o tick envia de facto.
    monkeypatch.setattr(engine_module, "is_quiet_hours", lambda *a, **k: False)
    sent_ids: list[str] = []

    class FakeGmail:
        async def send(self, mailbox, to_email, subject, body, from_name=None):
            sent_ids.append(to_email)
            return SendResult(success=True, provider_id="fake-1", http_status=200)

    monkeypatch.setattr(engine_module, "gmail_sender", FakeGmail())
    result = await engine.process_queue()
    assert result["sent"] == 1
    assert sent_ids == ["ops3@vitorio.com"]

    assert svc.count_outbound_messages(status="queued") == 0
    assert svc.count_outbound_messages(status="sent") >= 1
    # Caixa registou o envio e o lote ficou concluido.
    mailboxes = svc.list_sending_mailboxes(enabled_only=True)
    assert mailboxes[0]["last_send_at"] is not None
    assert svc.get_outbound_batch(batch["id"])["status"] in ("sent", "sending")


@pytest.mark.asyncio
async def test_engine_worker_skips_unconfirmed_and_suppressed(engine, monkeypatch):
    svc = engine_module.db_service._service
    _seed_mailbox()
    lead_id = _seed_lead("BOSTON", "engine-4", "4 ENGINE AVENUE")
    contact = _seed_contact(lead_id, "ops4@vitorio.com")
    # Passa a pendente: o worker nao pode enviar.
    svc.update_outbound_contact_status(contact["id"], email_status="unknown")
    batch = svc.create_outbound_batch(
        city="BOSTON", name="engine-4", filters_json=json.dumps({"city": "BOSTON"}), kind="email"
    )
    svc.mark_outbound_batch_previewed(batch["id"], 1, 0.0)
    batch = svc.start_outbound_batch(batch["id"])
    _set_config(send_enabled="1", enrich_enabled="0")
    try:
        # Volta a valido para enfileirar, depois suprime antes do envio.
        svc.update_outbound_contact_status(contact["id"], email_status="valid")
        await engine.enqueue_batch(batch)
        svc.add_suppression("ops4@vitorio.com", channel="email", reason="test")
        monkeypatch.setattr(engine_module, "is_quiet_hours", lambda *a, **k: False)
        result = await engine.process_queue()
        assert result["sent"] == 0
        assert result["skipped"] == 1
    finally:
        _set_config(send_enabled="0")


@pytest.mark.asyncio
async def test_engine_status_reports_queue_and_mailboxes(engine):
    _seed_mailbox()
    status = await engine.status()
    assert status["send_enabled"] in (True, False)
    assert "queued" in status
    assert "sent_today" in status
    assert status["mailboxes"], "deve expor pelo menos uma caixa"
    assert "effective_cap" in status["mailboxes"][0]
    assert "warmup_state" in status["mailboxes"][0]


# ------------------------------------------------------------------ dedup + claim


def test_engine_dedup_index_blocks_second_active_message(engine):
    """O indice unico parcial impede 2 mensagens ativas para o mesmo e-mail."""
    svc = engine_module.db_service._service
    first = svc.enqueue_outbound_message(
        batch_id=None, contact_id=None, city="BOSTON", to_email="dup@vitorio.com",
        subject="s", body_hash="h1",
    )
    assert first is not None
    dup = svc.enqueue_outbound_message(
        batch_id=None, contact_id=None, city="BOSTON", to_email="dup@vitorio.com",
        subject="s", body_hash="h2",
    )
    # INSERT OR IGNORE: a segunda nao entra (dedup dura).
    assert dup is None
    assert (
        svc.count_outbound_messages(status="queued") <= 1
    )


def test_engine_enqueue_skips_leads_already_messaged(engine):
    """list_outbound_leads exclui leads cujo contacto ja' tem mensagem ativa."""
    svc = engine_module.db_service._service
    lead_id = _seed_lead("BOSTON", "engine-dedup-1", "9 DEDUP AVENUE")
    contact = _seed_contact(lead_id, "dedup-lead@vitorio.com")
    # Primeira mensagem ativa para este contacto.
    assert svc.enqueue_outbound_message(
        batch_id=None, contact_id=contact["id"], city="BOSTON",
        to_email="dedup-lead@vitorio.com", subject="s", body_hash="h",
    ) is not None
    # O lead ja' nao volta a ser oferecido a lotes futuros.
    remaining = svc.list_outbound_leads("BOSTON", None, 200)
    assert all(r["id"] != lead_id for r in remaining)


def test_engine_claim_outbound_message_is_atomic(engine):
    """Claim: queued->sending so' 'e verdadeiro uma vez (sem reenvio)."""
    svc = engine_module.db_service._service
    msg = svc.enqueue_outbound_message(
        batch_id=None, contact_id=None, city="BOSTON", to_email="claim@vitorio.com",
        subject="s", body_hash="h",
    )
    assert msg is not None
    assert svc.claim_outbound_message(msg["id"]) is True
    # Segundo tick: a mensagem ja' nao esta' 'queued'.
    assert svc.claim_outbound_message(msg["id"]) is False
    assert svc.get_outbound_message(msg["id"])["status"] == "sending"


# ------------------------------------------------------------------ sequence


def test_outbound_step2_template_is_english_and_has_offer():
    """O e-mail 2 traz a oferta ($120/semana) e mantem o opt-out."""
    from backend.services import outbound_templates as ot

    tpl = ot.SEQUENCE_TEMPLATES["step2_offer"]
    ot.assert_english_only(tpl["subject"])
    ot.assert_english_only(tpl["body"])
    assert "$120" in tpl["body"]
    assert 'reply "unsubscribe"' in tpl["body"]
    # O preco nao vai no assunto (gatilho de spam).
    assert "$" not in tpl["subject"]

    ctx = ot.build_context(
        {"owner_name": "", "address": "1 MAIN ST", "issue_category": "Roof"},
        "NYC",
        "roofing",
        120,
    )
    ctx["url"] = ot.sequence_url("NYC", "roofing", step=2)
    rendered = ot.render_sequence_email("step2_offer", ctx)
    assert "New York City" in rendered["body"]
    assert "roofing" in rendered["body"]
    assert "magicleads.app/en?city=NYC&niche=roofing&step=2" in rendered["body"]
    assert "{" not in rendered["body"] and "}" not in rendered["body"]


@pytest.mark.asyncio
async def test_engine_schedules_step2_after_step1_sent(engine, monkeypatch):
    """Enviado o passo 1, o passo 2 (oferta) e' enfileirado."""
    svc = engine_module.db_service._service
    lead_id = _seed_lead("BOSTON", "engine-seq-1", "10 SEQUENCE AVENUE")
    _seed_contact(lead_id, "seq1@vitorio.com")
    batch = svc.create_outbound_batch(
        city="BOSTON", name="engine-seq-1",
        filters_json=json.dumps({"city": "BOSTON", "niche": "roofing"}), kind="email",
    )
    svc.mark_outbound_batch_previewed(batch["id"], 1, 0.0)
    batch = svc.start_outbound_batch(batch["id"])

    _set_config(send_enabled="1", enrich_enabled="0")
    try:
        await engine.enqueue_batch(batch)
        queued = svc.list_queued_outbound_messages(limit=10)
        assert queued, "o passo 1 devia estar na fila"
        step1 = queued[0]
        assert step1["sequence_step"] == 1
        assert step1["next_step_at"], "o passo 1 tem de agendar o passo 2"

        # Simula o envio: a mensagem passa a 'sent' e o agendamento esta' vencido.
        svc.update_outbound_message(step1["id"], status="sent")
        svc.set_outbound_message_next_step(step1["id"], "2000-01-01 00:00:00")

        result = await engine.schedule_next_steps()
        assert result["scheduled"] == 1

        step2 = [
            m for m in svc.list_queued_outbound_messages(limit=10)
            if m["sequence_step"] == 2
        ]
        assert len(step2) == 1
        assert step2[0]["to_email"] == "seq1@vitorio.com"
        # O agendamento do passo 1 foi consumido.
        assert svc.get_outbound_message(step1["id"])["next_step_at"] is None
    finally:
        _set_config(send_enabled="0")


@pytest.mark.asyncio
async def test_engine_does_not_schedule_step2_if_replied(engine, monkeypatch):
    """Quem ja' respondeu nao recebe o e-mail da oferta."""
    svc = engine_module.db_service._service
    lead_id = _seed_lead("BOSTON", "engine-seq-2", "11 SEQUENCE AVENUE")
    contact = _seed_contact(lead_id, "seq2@vitorio.com")
    batch = svc.create_outbound_batch(
        city="BOSTON", name="engine-seq-2",
        filters_json=json.dumps({"city": "BOSTON", "niche": "roofing"}), kind="email",
    )
    svc.mark_outbound_batch_previewed(batch["id"], 1, 0.0)
    batch = svc.start_outbound_batch(batch["id"])

    _set_config(send_enabled="1", enrich_enabled="0")
    try:
        await engine.enqueue_batch(batch)
        step1 = svc.list_queued_outbound_messages(limit=10)[0]
        svc.update_outbound_message(step1["id"], status="sent")
        svc.set_outbound_message_next_step(step1["id"], "2000-01-01 00:00:00")

        # O contacto respondeu -> a sequencia para.
        assert svc.mark_outbound_contact_replied(contact["id"]) is True

        result = await engine.schedule_next_steps()
        assert result["scheduled"] == 0
        assert not [
            m for m in svc.list_queued_outbound_messages(limit=10)
            if m["sequence_step"] == 2
        ]
    finally:
        _set_config(send_enabled="0")


@pytest.mark.asyncio
async def test_engine_step2_is_not_duplicated(engine, monkeypatch):
    """O mesmo passo nunca e' criado duas vezes (indice unico por email+passo)."""
    svc = engine_module.db_service._service
    lead_id = _seed_lead("BOSTON", "engine-seq-3", "12 SEQUENCE AVENUE")
    _seed_contact(lead_id, "seq3@vitorio.com")
    batch = svc.create_outbound_batch(
        city="BOSTON", name="engine-seq-3",
        filters_json=json.dumps({"city": "BOSTON", "niche": "roofing"}), kind="email",
    )
    svc.mark_outbound_batch_previewed(batch["id"], 1, 0.0)
    batch = svc.start_outbound_batch(batch["id"])

    _set_config(send_enabled="1", enrich_enabled="0")
    try:
        await engine.enqueue_batch(batch)
        step1 = svc.list_queued_outbound_messages(limit=10)[0]
        svc.update_outbound_message(step1["id"], status="sent")
        svc.set_outbound_message_next_step(step1["id"], "2000-01-01 00:00:00")

        await engine.schedule_next_steps()
        # Reagenda o passo 1 (simula um tick que nao consumiu) -> nao duplica.
        svc.set_outbound_message_next_step(step1["id"], "2000-01-01 00:00:00")
        await engine.schedule_next_steps()

        step2 = [
            m for m in svc.list_queued_outbound_messages(limit=10)
            if m["sequence_step"] == 2
        ]
        assert len(step2) == 1
    finally:
        _set_config(send_enabled="0")




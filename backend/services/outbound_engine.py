"""Outbound Frio - motor real (Fase 2).

Fecha a esteira de envio: materializa lotes em `outbound_messages`, aplica as
travas anti-spam (so' e-mails `valid`), o warm-up por caixa, os tetos diarios e
as quiet hours, e envia pela Gmail API.

Fica integralmente no dominio outbound (`outbound_*`, Gmail, EmailListVerify). Nao toca
Dashboard, ingestao/UPSERT, Landing, Push ou Resend. O envio real continua
fail-closed: `send_enabled=0` (default) desliga todo o processamento.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from ..config import settings
from ..utils.logger import logger
from . import outbound_templates
from .db import SERVED_CITIES, db_service
from .enrichment_emaillistverify import emaillistverify_service
from .gmail import gmail_sender

# --------------------------------------------------------------- helpers

def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_json(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        data = json.loads(value)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _parse_hhmm(value: Optional[str]) -> Optional[tuple[int, int]]:
    if not value or ":" not in str(value):
        return None
    try:
        hh, mm = str(value).split(":", 1)
        h, m = int(hh), int(mm)
        if 0 <= h < 24 and 0 <= m < 60:
            return h, m
    except (TypeError, ValueError):
        return None
    return None


def day_key(now: Optional[datetime] = None) -> str:
    return (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d")


def _now_str(now: Optional[datetime] = None) -> str:
    return (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M:%S")


def is_quiet_hours(now: datetime, start: Optional[str], end: Optional[str]) -> bool:
    """True se `now` (UTC) cai dentro do intervalo de silencio (aceita wrap)."""
    s = _parse_hhmm(start)
    e = _parse_hhmm(end)
    if not s or not e or s == e:
        return False
    minutes = now.hour * 60 + now.minute
    start_m = s[0] * 60 + s[1]
    end_m = e[0] * 60 + e[1]
    if start_m < end_m:
        return start_m <= minutes < end_m
    return minutes >= start_m or minutes < end_m


def warmup_days(started_at: Optional[str], now: datetime) -> int:
    if not started_at:
        return 0
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            started = datetime.strptime(str(started_at).strip(), fmt).replace(
                tzinfo=timezone.utc
            )
            return max(0, (now - started).days)
        except ValueError:
            continue
    return 0


def effective_mailbox_cap(mailbox: dict, config: dict, now: datetime) -> int:
    """Teto efetivo da caixa: min(caixa, config) com rampa de warm-up.

    Sem warm-up (ou apos `min_warmup_days`), devolve o teto cheio. Durante o
    warm-up, cresce linearmente de 1 ate' ao teto ao longo dos dias minimos.
    """
    mailbox_cap = _int(mailbox.get("daily_cap"), _int(config.get("per_mailbox_daily_cap"), 25))
    config_cap = _int(config.get("per_mailbox_daily_cap"), 25)
    cap = max(0, min(mailbox_cap, config_cap)) if config_cap > 0 else max(0, mailbox_cap)
    if config.get("warmup_enabled") != "1":
        return cap
    min_days = _int(config.get("min_warmup_days"), 14)
    days = warmup_days(mailbox.get("warmup_started_at"), now)
    if min_days <= 0 or days >= min_days:
        return cap
    return max(1, int(cap * (days + 1) / min_days))


def _mailbox_warmup_state(mailbox: dict, config: dict, now: datetime) -> str:
    min_days = _int(config.get("min_warmup_days"), 14)
    if config.get("warmup_enabled") != "1":
        return "warm"
    return "warm" if warmup_days(mailbox.get("warmup_started_at"), now) >= min_days else "warming"


class OutboundEngine:
    """Materializa lotes e processa a fila de envio real."""

    # Alias para testes/monkeypatch.
    ENRICH_CONCURRENCY = 4

    async def aclose(self) -> None:
        """Fecha os clients HTTP partilhados (Gmail/EmailListVerify) no shutdown."""
        for client in (gmail_sender, emaillistverify_service):
            try:
                await client.aclose()
            except Exception:
                pass

    # ---------------------------------------------------------- enqueue

    async def enqueue_batch(self, batch: dict, config: Optional[dict] = None) -> dict:
        """Promove um lote a REAL e enfileira apenas e-mails `valid`.

        Retorna contadores (queued/skipped/no_email) para o painel. Nao envia:
        o worker e' quem processa `outbound_messages`.
        """
        city = (batch.get("city") or "").strip().upper()
        config = config or await db_service.get_outbound_config(city or None)
        filters = _parse_json(batch.get("filters_json"))
        niche = filters.get("niche") or outbound_templates.DEFAULT_NICHE
        categories = outbound_templates.niche_categories(niche)
        limit = _int(
            filters.get("batch_size") or batch.get("contact_count") or config.get("batch_size"),
            200,
        )
        enrich_enabled = config.get("enrich_enabled") == "1"
        daily_enrich_cap = _int(config.get("daily_enrich_cap"), 1000)
        max_spend = _float(config.get("max_spend_per_batch_usd"), 0.0)

        today = day_key()
        usage = await db_service.get_outbound_counter(city, today)
        billed_today = _int(usage.get("enriched"), 0)
        enrichment_left = max(0, daily_enrich_cap - billed_today) if daily_enrich_cap > 0 else 10**9

        leads = await db_service.list_outbound_leads(city, categories, limit)
        # `{count}` no copy reflecte o inventario REAL da cidade/nicho (mesma
        # fonte da previa do painel), nao o tamanho do lote. Fonte unica para
        # previa e envio; o piso/arredondamento e' aplicado por copy_count.
        count_for_copy = await db_service.count_qualified_contractors_in_city(
            city, categories
        )
        if count_for_copy <= 0:
            count_for_copy = len(leads)

        queued = 0
        skipped = 0
        no_email = 0
        spend_total = 0.0
        billed_batch = 0

        for lead in leads:
            contact = await db_service.get_outbound_contact_by_lead(lead["id"])
            if contact and contact.get("email_status") == "valid" and not contact.get("unsubscribed"):
                pass  # reaproveita contacto validado
            elif enrich_enabled and enrichment_left > 0 and spend_total < max_spend:
                result = await emaillistverify_service.find_and_verify(
                    owner_email=lead.get("owner_email"),
                    company_name=lead.get("owner_name"),
                    contact_name=(contact or {}).get("contact_name"),
                    city=city,
                )
                billed_batch += result.billed_calls
                spend_total += result.spend_usd
                enrichment_left -= result.billed_calls
                if result.success and result.status == "valid" and result.email:
                    contact = await db_service.upsert_outbound_contact(
                        lead_id=lead["id"],
                        email=result.email,
                        city=city,
                        state=lead.get("state"),
                        company_name=lead.get("owner_name"),
                        contact_name=(contact or {}).get("contact_name"),
                        email_source="emaillistverify",
                        email_status="valid",
                    )
                else:
                    no_email += 1
                    continue
            else:
                no_email += 1
                continue

            if not contact or not contact.get("email"):
                no_email += 1
                continue

            email = contact["email"]
            if await db_service.is_suppressed(email):
                skipped += 1
                continue

            try:
                context = outbound_templates.build_context(
                    lead, city, niche, count_for_copy, contact=contact
                )
                rendered = outbound_templates.render_email(niche, context)
            except Exception as e:
                # Copy tem de ser en-US: um lead com dados non-ASCII e' excluido,
                # nunca derruba o lote inteiro.
                logger.warning("[OUTBOUND] Lead %s sem copy valido: %s", lead.get("id"), e)
                skipped += 1
                continue
            body_hash = hashlib.sha256(rendered["body"].encode("utf-8")).hexdigest()
            # Sequencia (Prioridade D): o passo 1 (amostra) agenda o passo 2
            # (oferta) para daqui a N dias, se o destinatario nao responder.
            next_step_at = None
            if getattr(settings, "OUTBOUND_SEQUENCE_ENABLED", True):
                delay_days = _int(
                    getattr(settings, "OUTBOUND_SEQUENCE_STEP2_DELAY_DAYS", 3), 3
                )
                if delay_days > 0:
                    next_step_at = _now_str(
                        datetime.now(timezone.utc) + timedelta(days=delay_days)
                    )
            msg = await db_service.enqueue_outbound_message(
                batch_id=batch.get("id"),
                contact_id=contact["id"],
                city=city,
                to_email=email,
                subject=rendered["subject"],
                body_hash=body_hash,
                sequence_step=1,
                next_step_at=next_step_at,
            )
            if msg:
                queued += 1
            else:
                skipped += 1

        if billed_batch:
            await db_service.increment_outbound_counter(
                city, today, enriched=billed_batch, spend_usd=spend_total
            )
        await db_service.update_outbound_batch_stats(batch.get("id"), queued, spend_total)

        return {
            "queued": queued,
            "skipped": skipped,
            "no_email": no_email,
            "spend_usd": round(spend_total, 4),
            "total_leads": len(leads),
        }

    # ---------------------------------------------------------- reaper

    async def reap_stale_sending(self, now: Optional[datetime] = None) -> int:
        """Marca como 'failed' as mensagens presas em 'sending' ha demasiado tempo.

        Motivo: o claim atomico (`queued -> sending`) acontece ANTES do envio.
        Se o processo morrer a meio (deploy, OOM, restart), a mensagem fica em
        'sending' PARA SEMPRE: o `list_queued_outbound_messages` so' le
        'queued' e nao havia reaper.

        Semantica at-most-once: nao reenfileiramos, porque nao sabemos se o
        envio chegou a acontecer, e um e-mail frio duplicado e' pior do que um
        e-mail perdido (o lead nao e' consumido pelo outbound).
        """
        now = now or datetime.now(timezone.utc)
        minutes = _int(getattr(settings, "OUTBOUND_STALE_SENDING_MINUTES", 15), 15)
        if minutes <= 0:
            return 0
        cutoff = _now_str(now - timedelta(minutes=minutes))
        try:
            n = await db_service.fail_stale_sending_outbound_messages(cutoff)
        except Exception as e:
            logger.warning("[OUTBOUND] reaper falhou: %s", e)
            return 0
        if n:
            logger.warning(
                "[OUTBOUND] %s mensagem(ns) presa(s) em 'sending' ha mais de %s min "
                "-> marcadas como failed (o processo morreu a meio do envio)",
                n, minutes,
            )
        return n

    # ---------------------------------------------------------- sequence

    async def schedule_next_steps(self, now: Optional[datetime] = None) -> dict:
        """Cria o proximo passo da sequencia para quem ja' recebeu o anterior.

        Passo 1 = e-mail de amostra (sem preco). Passo 2 = e-mail da oferta
        ($120/semana). O passo 2 so' e' criado se o destinatario:
          * nao respondeu (`replied_at` vazio);
          * nao se desinscreveu;
          * nao esta' suprimido.

        Sem deteccao automatica de respostas (exige scope `gmail.readonly`),
        `replied_at` e' marcado manualmente pelo painel. Conservative: na duvida
        NAO se envia o passo 2.
        """
        now = now or datetime.now(timezone.utc)
        if not getattr(settings, "OUTBOUND_SEQUENCE_ENABLED", True):
            return {"scheduled": 0, "skipped": 0}
        max_step = _int(getattr(settings, "OUTBOUND_SEQUENCE_MAX_STEP", 2), 2)
        if max_step < 2:
            return {"scheduled": 0, "skipped": 0}

        due = await db_service.list_outbound_messages_due_for_sequence(_now_str(now))
        scheduled = 0
        skipped = 0

        for message in due:
            step = _int(message.get("sequence_step"), 1)
            if step >= max_step:
                # Ultimo passo: consome o agendamento e nao cria mais nada.
                await db_service.set_outbound_message_next_step(message["id"], None)
                continue

            to_email = (message.get("to_email") or "").strip()
            if not to_email:
                await db_service.set_outbound_message_next_step(message["id"], None)
                continue

            contact = await db_service.get_outbound_contact_by_email(to_email)
            if not contact:
                await db_service.set_outbound_message_next_step(message["id"], None)
                skipped += 1
                continue
            if contact.get("replied_at") or contact.get("unsubscribed"):
                await db_service.set_outbound_message_next_step(message["id"], None)
                skipped += 1
                continue
            if await db_service.is_suppressed(to_email):
                await db_service.set_outbound_message_next_step(message["id"], None)
                skipped += 1
                continue

            city = (message.get("city") or "").strip().upper()
            batch = (
                await db_service.get_outbound_batch(message["batch_id"])
                if message.get("batch_id")
                else None
            )
            niche = outbound_templates.DEFAULT_NICHE
            if batch:
                filters = _parse_json(batch.get("filters_json"))
                niche = filters.get("niche") or niche
            categories = outbound_templates.niche_categories(niche)

            lead = None
            if contact.get("lead_id"):
                lead = await db_service.get_lead_by_id(contact["lead_id"])
            if not lead:
                await db_service.set_outbound_message_next_step(message["id"], None)
                skipped += 1
                continue

            count = await db_service.count_qualified_contractors_in_city(city, categories)
            if count <= 0:
                count = _int(batch.get("contact_count"), 0) if batch else 0

            try:
                context = outbound_templates.build_context(
                    lead, city, niche, count, contact=contact
                )
                context["url"] = outbound_templates.sequence_url(city, niche, step=step + 1)
                rendered = outbound_templates.render_sequence_email("step2_offer", context)
            except Exception as e:
                logger.warning(
                    "[OUTBOUND] Falha ao renderizar o passo %s: %s", step + 1, e
                )
                await db_service.set_outbound_message_next_step(message["id"], None)
                skipped += 1
                continue

            body_hash = hashlib.sha256(rendered["body"].encode("utf-8")).hexdigest()
            next_step_at = None
            if step + 1 < max_step:
                delay_days = _int(
                    getattr(settings, "OUTBOUND_SEQUENCE_STEP2_DELAY_DAYS", 3), 3
                )
                if delay_days > 0:
                    next_step_at = _now_str(
                        datetime.now(timezone.utc) + timedelta(days=delay_days)
                    )

            created = await db_service.enqueue_outbound_message(
                batch_id=message.get("batch_id"),
                contact_id=contact["id"],
                city=city,
                to_email=to_email,
                subject=rendered["subject"],
                body_hash=body_hash,
                sequence_step=step + 1,
                next_step_at=next_step_at,
            )
            # Consome o agendamento desta mensagem, venha a criacao bem ou mal:
            # re-tentar o passo nao pode duplicar (o indice unico por passo
            # garante isso, mas nao vale a pena insistir).
            await db_service.set_outbound_message_next_step(message["id"], None)
            if created:
                scheduled += 1
            else:
                skipped += 1

        if scheduled:
            logger.info("[OUTBOUND] Sequencia: %s mensagem(s) do proximo passo criada(s)", scheduled)
        return {"scheduled": scheduled, "skipped": skipped}

    # ---------------------------------------------------------- worker tick

    async def _pick_mailbox(self, city: str, config: dict, now: datetime, day: str) -> Optional[dict]:
        mailboxes = await db_service.list_sending_mailboxes(enabled_only=True)
        best: Optional[dict] = None
        for mailbox in mailboxes:
            mb_city = (mailbox.get("city") or "").strip().upper()
            if mb_city and mb_city != (city or "").strip().upper():
                continue
            if mailbox.get("warmup_started_at") is None:
                await db_service.set_mailbox_warmup_started(mailbox["id"])
                mailbox = {**mailbox, "warmup_started_at": _now_str(now)}
            cap = effective_mailbox_cap(mailbox, config, now)
            if cap <= 0:
                continue
            sent = await db_service.count_mailbox_sent_today(mailbox["id"], day)
            if sent >= cap:
                continue
            if best is None or sent < best["_sent_today"]:
                best = {
                    **mailbox,
                    "_sent_today": sent,
                    "_cap": cap,
                    "_warmup_state": _mailbox_warmup_state(mailbox, config, now),
                }
        return best

    async def process_queue(
        self, limit: Optional[int] = None, now: Optional[datetime] = None
    ) -> dict:
        """Um tick do worker: envia ate' ao limite do chunk respeitando travas."""
        now = now or datetime.now(timezone.utc)
        global_config = await db_service.get_outbound_config()
        if global_config.get("send_enabled") != "1":
            return {"status": "disabled", "sent": 0}
        if is_quiet_hours(
            now, global_config.get("quiet_hours_start"), global_config.get("quiet_hours_end")
        ):
            return {"status": "quiet_hours", "sent": 0}

        limit = limit or _int(
            getattr(settings, "OUTBOUND_WORKER_CHUNK", 10), 10
        )
        # Sprint 1: limpa mensagens presas em 'sending' (o processo morreu entre
        # o claim e o envio — tipicamente num deploy). Sem isto ficavam para
        # sempre: credito gasto, lead contactado, e-mail nunca enviado.
        await self.reap_stale_sending(now)
        # Sequencia (Prioridade D): agenda o proximo passo antes de drenar a
        # fila, para que o passo 2 entre na MESMA janela de envio.
        await self.schedule_next_steps(now)
        messages = await db_service.list_queued_outbound_messages(limit=limit)
        day = day_key(now)
        sent = 0
        skipped = 0
        failed = 0
        touched_batches: set[int] = set()

        for message in messages:
            city = message.get("city") or ""
            config = await db_service.get_outbound_config(city or None)
            if config.get("send_enabled") != "1":
                break
            counter = await db_service.get_outbound_counter(city, day)
            daily_cap = _int(config.get("daily_send_cap"), 100)
            if daily_cap > 0 and _int(counter.get("sent"), 0) >= daily_cap:
                break

            batch = (
                await db_service.get_outbound_batch(message["batch_id"])
                if message.get("batch_id")
                else None
            )
            if batch:
                touched_batches.add(batch["id"])
                if _int(batch.get("dry_run"), 1) == 1:
                    await db_service.update_outbound_message(
                        message["id"], status="skipped", error="dry_run batch"
                    )
                    skipped += 1
                    continue

            contact = (
                await db_service.get_outbound_contact_by_email(message["to_email"])
                if message.get("to_email")
                else None
            )
            if (
                not contact
                or contact.get("email_status") != "valid"
                or contact.get("unsubscribed")
            ):
                await db_service.update_outbound_message(
                    message["id"], status="skipped", error="email not confirmed valid"
                )
                skipped += 1
                continue

            if await db_service.is_suppressed(message["to_email"]):
                await db_service.update_outbound_message(
                    message["id"], status="suppressed", error="suppressed"
                )
                skipped += 1
                continue

            mailbox = await self._pick_mailbox(city, config, now, day)
            if not mailbox:
                logger.info("[OUTBOUND] Sem caixa com capacidade agora — parando o tick")
                break

            subject, body = await self._render_message(
                batch, contact, city, _int(message.get("sequence_step"), 1)
            )
            if body is None:
                await db_service.update_outbound_message(
                    message["id"], status="failed", error="cannot render message"
                )
                failed += 1
                continue

            # Claim atomico: so' o tick que ganhar a corrida (queued->sending)
            # envia. Ticks sobrepostos veem rowcount=0 e saltam — sem reenvio.
            if not await db_service.claim_outbound_message(message["id"]):
                logger.info(
                    "[OUTBOUND] Mensagem %s ja' reclamada por outro tick", message["id"]
                )
                continue

            result = await gmail_sender.send(
                mailbox,
                message["to_email"],
                subject or (message.get("subject") or ""),
                body,
                from_name=mailbox.get("display_name"),
            )
            if result.success:
                await db_service.update_outbound_message(
                    message["id"],
                    status="sent",
                    provider_id=result.provider_id,
                    sent_at=_now_str(now),
                    mailbox_id=mailbox["id"],
                )
                await db_service.increment_outbound_counter(city, day, sent=1)
                await db_service.update_mailbox_after_send(
                    mailbox["id"], warmup_state=mailbox.get("_warmup_state")
                )
                sent += 1
            else:
                await db_service.update_outbound_message(
                    message["id"],
                    status="failed",
                    error=result.error,
                    mailbox_id=mailbox["id"],
                )
                failed += 1

        for batch_id in touched_batches:
            remaining = await db_service.count_outbound_messages(
                status="queued", batch_id=batch_id
            )
            if remaining == 0:
                await db_service.finish_outbound_batch(batch_id, status="sent")

        return {"status": "ok", "sent": sent, "skipped": skipped, "failed": failed}

    async def _render_message(
        self,
        batch: Optional[dict],
        contact: dict,
        city: str,
        sequence_step: int = 1,
    ) -> tuple[Optional[str], Optional[str]]:
        """Re-renderiza subject+body a partir do lead real (integridade = hash)."""
        niche = outbound_templates.DEFAULT_NICHE
        count = 0
        categories = None
        if batch:
            filters = _parse_json(batch.get("filters_json"))
            niche = filters.get("niche") or niche
            categories = outbound_templates.niche_categories(niche)
        # Mesmo `{count}` da previa e do enqueue: inventario real da cidade/nicho.
        try:
            count = await db_service.count_qualified_contractors_in_city(city, categories)
        except Exception:
            count = 0
        if count <= 0:
            count = _int(batch.get("contact_count"), 0) if batch else 0
        lead = None
        if contact.get("lead_id"):
            lead = await db_service.get_lead_by_id(contact["lead_id"])
        if not lead:
            return None, None
        try:
            context = outbound_templates.build_context(lead, city, niche, count, contact=contact)
            if sequence_step >= 2:
                # Passo da sequencia (oferta): template proprio + link da landing.
                context["url"] = outbound_templates.sequence_url(
                    city, niche, step=sequence_step
                )
                rendered = outbound_templates.render_sequence_email(
                    "step2_offer", context
                )
            else:
                rendered = outbound_templates.render_email(niche, context)
        except Exception as e:
            logger.warning("[OUTBOUND] Falha ao re-renderizar mensagem: %s", e)
            return None, None
        return rendered["subject"], rendered["body"]

    # ---------------------------------------------------------- status

    async def status(self) -> dict:
        now = datetime.now(timezone.utc)
        day = day_key(now)
        global_config = await db_service.get_outbound_config()
        mailboxes = await db_service.list_sending_mailboxes(enabled_only=False)
        mailbox_rows = []
        for mailbox in mailboxes:
            cap = effective_mailbox_cap(mailbox, global_config, now)
            sent_today = await db_service.count_mailbox_sent_today(mailbox["id"], day)
            mailbox_rows.append(
                {
                    "id": mailbox["id"],
                    "email": mailbox["email"],
                    "city": mailbox.get("city") or "",
                    "enabled": _int(mailbox.get("enabled"), 0),
                    "daily_cap": _int(mailbox.get("daily_cap"), 25),
                    "effective_cap": cap,
                    "sent_today": sent_today,
                    "warmup_state": _mailbox_warmup_state(mailbox, global_config, now),
                    "warmup_days": warmup_days(mailbox.get("warmup_started_at"), now),
                }
            )
        usage = await db_service.get_outbound_counter("", day)
        sent_today = 0
        enriched_today = 0
        spend_today = _float(usage.get("spend_usd"), 0.0)
        for served_city in SERVED_CITIES:
            counter = await db_service.get_outbound_counter(served_city, day)
            sent_today += _int(counter.get("sent"), 0)
            enriched_today += _int(counter.get("enriched"), 0)
            spend_today += _float(counter.get("spend_usd"), 0.0)
        return {
            "send_enabled": global_config.get("send_enabled") == "1",
            "enrich_enabled": global_config.get("enrich_enabled") == "1",
            "quiet_hours_now": is_quiet_hours(
                now,
                global_config.get("quiet_hours_start"),
                global_config.get("quiet_hours_end"),
            ),
            "day": day,
            "queued": await db_service.count_outbound_messages(status="queued"),
            "sent_today": sent_today,
            "enriched_today": enriched_today,
            "spend_today_usd": round(spend_today, 4),
            "config": global_config,
            "mailboxes": mailbox_rows,
            "enrichment_configured": emaillistverify_service.configured,
            "enrichment_provider": "emaillistverify",
            "sequence": {
                "enabled": bool(getattr(settings, "OUTBOUND_SEQUENCE_ENABLED", True)),
                "step2_delay_days": _int(
                    getattr(settings, "OUTBOUND_SEQUENCE_STEP2_DELAY_DAYS", 3), 3
                ),
                "max_step": _int(getattr(settings, "OUTBOUND_SEQUENCE_MAX_STEP", 2), 2),
            },
            "stale_sending": await db_service.count_stale_sending_outbound_messages(
                _now_str(
                    (now - timedelta(minutes=_int(
                        getattr(settings, "OUTBOUND_STALE_SENDING_MINUTES", 15), 15
                    ))).replace(tzinfo=timezone.utc)
                )
            ),
        }


outbound_engine = OutboundEngine()

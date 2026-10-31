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
from . import niche_classifier, outbound_templates
from .db import (
    SENDABLE_EMAIL_STATUSES,
    SERVED_CITIES,
    TRUSTED_EMAIL_SOURCES,
    db_service,
)
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


# Status de e-mail aceitos no envio. `valid` e' o gate historico; `verified` e
# `catch_all` vem dos provedores de verificacao. Contactos de origem
# `import`/`manual` entraram ja' com e-mail fornecido pelo operador/fornecedor,
# por isso nao dependem do status gravado (imports antigos podiam gravar NULL).
# Fonte unica: `db.py` (o diagnostico do admin usa as mesmas listas).
def is_sendable_contact(contact: Optional[dict]) -> bool:
    """Verdadeiro quando o contacto tem e-mail preenchido e pode receber copy."""
    if not contact:
        return False
    if not str(contact.get("email") or "").strip():
        return False
    if _int(contact.get("unsubscribed"), 0):
        return False
    source = str(contact.get("email_source") or "").strip().lower()
    if source in TRUSTED_EMAIL_SOURCES:
        return True
    status = str(contact.get("email_status") or "").strip().lower()
    return status in SENDABLE_EMAIL_STATUSES


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


def _now_dt(now: Optional[datetime] = None) -> datetime:
    """Normaliza para UTC antes de formatar.

    Se um chamador passar um datetime aware noutro fuso, formatar sem converter
    produzia um cutoff deslocado — o reaper podia marcar como 'failed' um envio
    que acabou de ser reclamado (ou nunca limpar um preso). Datetimes naive sao
    assumidos UTC (contrato do projeto/SQLite).
    """
    dt = now or datetime.now(timezone.utc)
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return dt


def day_key(now: Optional[datetime] = None) -> str:
    return _now_dt(now).strftime("%Y-%m-%d")


def _now_str(now: Optional[datetime] = None) -> str:
    return _now_dt(now).strftime("%Y-%m-%d %H:%M:%S")


def is_quiet_hours(now: datetime, start: Optional[str], end: Optional[str]) -> bool:
    """True se `now` (UTC) cai dentro do intervalo de silencio (aceita wrap)."""
    now = _now_dt(now)
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


# Rampa conservadora aprovada: dia 0-2 -> 1/dia, dia 3 -> 2, dia 4 -> 3,
# dia 5 -> 5, dia 6 -> 8, dia 7+ -> 12 (por caixa).
DEFAULT_WARMUP_RAMP: tuple[int, ...] = (1, 1, 1, 2, 3, 5, 8, 12)


def warmup_ramp(config: dict) -> tuple[int, ...]:
    """Le `warmup_ramp` ("1,1,1,2,3,5,8,12") com fallback seguro."""
    raw = str(config.get("warmup_ramp") or "").strip()
    if not raw:
        return DEFAULT_WARMUP_RAMP
    parsed: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            parsed.append(max(1, int(part)))
        except ValueError:
            continue
    return tuple(parsed) or DEFAULT_WARMUP_RAMP


def effective_mailbox_cap(mailbox: dict, config: dict, now: datetime) -> int:
    """Teto efetivo da caixa para hoje.

    Com warm-up ativo, a RAMPA manda: dia N -> ramp[min(N, len-1)], limitado
    apenas por `per_mailbox_daily_cap`. Isto substitui a formula linear antiga,
    que com `daily_cap=1` nunca subia acima de 1 (a caixa ficava presa para
    sempre no primeiro escalao).

    Sem warm-up (ou depois de a rampa terminar), vale o menor entre
    `daily_cap` da caixa e `per_mailbox_daily_cap`.
    """
    mailbox_cap = _int(mailbox.get("daily_cap"), _int(config.get("per_mailbox_daily_cap"), 25))
    config_cap = _int(config.get("per_mailbox_daily_cap"), 25)
    ceiling = max(0, min(mailbox_cap, config_cap)) if config_cap > 0 else max(0, mailbox_cap)

    if config.get("warmup_enabled") != "1":
        return ceiling

    days = warmup_days(mailbox.get("warmup_started_at"), now)
    ramp = warmup_ramp(config)
    if days >= len(ramp):
        return ceiling
    day_cap = ramp[days]
    if config_cap > 0:
        day_cap = min(day_cap, config_cap)
    return max(0, day_cap)


def _mailbox_warmup_state(mailbox: dict, config: dict, now: datetime) -> str:
    min_days = _int(config.get("min_warmup_days"), 14)
    if config.get("warmup_enabled") != "1":
        return "warm"
    return "warm" if warmup_days(mailbox.get("warmup_started_at"), now) >= min_days else "warming"


def next_utc_midnight(now: Optional[datetime] = None) -> str:
    """Primeiro instante do próximo dia UTC (quando os caps de caixa repõem)."""
    dt = (_now_dt(now) + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def quiet_hours_end_iso(now: datetime, config: dict) -> Optional[str]:
    """Instante em que a janela de silêncio atual termina (UTC), se aplicável."""
    if not is_quiet_hours(
        now, config.get("quiet_hours_start"), config.get("quiet_hours_end")
    ):
        return None
    end = _parse_hhmm(config.get("quiet_hours_end"))
    if not end:
        return None
    dt = _now_dt(now)
    target = dt.replace(hour=end[0], minute=end[1], second=0, microsecond=0)
    if target <= dt:
        target += timedelta(days=1)
    return target.strftime("%Y-%m-%d %H:%M:%S")


def mailbox_matches_city(mailbox_city: Optional[str], message_city: Optional[str]) -> bool:
    """Caixa global (city vazio) serve qualquer cidade; específica só a sua.

    Uma mensagem sem cidade também aceita qualquer caixa — é o caso dos lotes
    antigos criados antes de `city` ser propagada.
    """
    mb = (mailbox_city or "").strip().upper()
    msg = (message_city or "").strip().upper()
    if not mb or not msg:
        return True
    return mb == msg


def mailbox_capacity_row(
    mailbox: dict, config: dict, now: datetime, sent_today: int
) -> dict:
    """Fotografia de capacidade de uma caixa para o dia corrente."""
    cap = effective_mailbox_cap(mailbox, config, now)
    return {
        **mailbox,
        "effective_cap": cap,
        "sent_today": max(0, _int(sent_today, 0)),
        "remaining_today": max(0, cap - max(0, _int(sent_today, 0))),
        "warmup_state": _mailbox_warmup_state(mailbox, config, now),
        "warmup_days": warmup_days(mailbox.get("warmup_started_at"), now),
    }


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

        # BLOQUEIO DURO: sem inventario qualificado nao se cria nem promove lote.
        # Antes disto, um lote vazio saia da mesma forma e o copy dizia "0 ...".
        if count_for_copy <= 0:
            logger.warning(
                "[OUTBOUND] lote %s bloqueado: sem inventario para %s/%s",
                batch.get("id"), city, niche,
            )
            return {
                "status": "blocked",
                "reason": "no_inventory",
                "queued": 0,
                "skipped": 0,
                "no_email": 0,
                "pending_enrich": 0,
                "skipped_niche": 0,
                "spend_usd": 0.0,
                "total_leads": 0,
            }

        # Numero DIVULGADO = o que conseguimos mesmo entregar (CAN-SPAM safe).
        copy_count = max(1, min(count_for_copy, limit))
        mix_cache: dict[str, list[tuple[str, int]]] = {}

        queued = 0
        skipped = 0
        skipped_niche = 0
        no_email = 0
        pending_enrich = 0
        spend_total = 0.0
        billed_batch = 0

        for lead in leads:
            contact = await db_service.get_outbound_contact_by_lead(lead["id"])
            if not contact and lead.get("owner_email"):
                # Import B2B: o e-mail tambem esta no proprio lead, caso a
                # linha de `outbound_contacts` tenha ficado noutro lead.
                contact = await db_service.get_outbound_contact_by_email(
                    lead["owner_email"]
                )
            if is_sendable_contact(contact):
                pass  # reaproveita contacto validado
            elif enrich_enabled and enrichment_left > 0 and spend_total < max_spend:
                # NAO enriquecer dentro do request HTTP (200 leads x ~4 candidatos
                # x ~2s = ~27 min: o proxy do Railway cortava o pedido a meio).
                # Enfileira o lead e devolve de imediato; o loop de background
                # (`enrichment_queue.worker_loop`) faz descoberta + validacao RCPT
                # via worker VPS, com retry/backoff, e grava em outbound_contacts.
                from . import enrichment_queue

                await enrichment_queue.enqueue_leads([lead["id"]], city, niche)
                pending_enrich += 1
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

            # GATE: o copy segue o nicho do DESTINATARIO, nunca o do lote.
            lead_niche = (contact or {}).get("niche_key") or lead.get("niche_key")
            lead_niche_status = (contact or {}).get("niche_status") or lead.get(
                "niche_status"
            )
            if not niche_classifier.is_sendable(lead_niche, lead_niche_status):
                skipped_niche += 1
                logger.info(
                    "[OUTBOUND] lead=%s sem nicho confirmado (key=%s status=%s) - nao enviado",
                    lead.get("id"), lead_niche, lead_niche_status,
                )
                continue
            if lead_niche not in mix_cache:
                mix_cache[lead_niche] = await db_service.outbound_category_mix(
                    city, outbound_templates.niche_categories(lead_niche)
                )

            try:
                context = outbound_templates.build_context(
                    lead, city, lead_niche, copy_count, contact=contact,
                    top_categories=mix_cache.get(lead_niche),
                )
                rendered = outbound_templates.render_email(lead_niche, context)
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
            "skipped_niche": skipped_niche,
            "pending_enrich": pending_enrich,
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

    async def _capacity_snapshot(
        self, config: dict, now: datetime, day: str
    ) -> list[dict]:
        """Capacidade de TODAS as caixas ligadas, já com o cap de hoje.

        Uma caixa sem `warmup_started_at` é inicializada aqui (dia 0 da rampa).
        O snapshot é reutilizado por todos os pedidos do mesmo tick.
        """
        mailboxes = await db_service.list_sending_mailboxes(enabled_only=True)
        out: list[dict] = []
        for mailbox in mailboxes:
            if mailbox.get("warmup_started_at") is None:
                await db_service.set_mailbox_warmup_started(mailbox["id"])
                mailbox = {**mailbox, "warmup_started_at": _now_str(now)}
            sent = await db_service.count_mailbox_sent_today(mailbox["id"], day)
            out.append(mailbox_capacity_row(mailbox, config, now, sent))
        return out

    def _pick_mailbox(
        self, city: str, snapshot: list[dict], *, allow_spillover: bool = True
    ) -> Optional[dict]:
        """Escolhe a caixa com mais folga; a da cidade tem prioridade.

        Duas passagens:
          1. caixas globais ou da própria cidade com `remaining_today > 0`;
          2. se nenhuma da cidade tiver folga, qualquer caixa ligada com folga
             (spillover). Sem isto, uma cidade cujas caixas esgotaram o cap
             ficava bloqueada para sempre mesmo com outras caixas vazias.
        """
        eligible = [m for m in snapshot if _int(m.get("remaining_today"), 0) > 0]
        if not eligible:
            return None
        preferred = [
            m for m in eligible if mailbox_matches_city(m.get("city"), city)
        ]
        pool = preferred or (eligible if allow_spillover else [])
        if not pool:
            return None
        # Mais folga primeiro; desempate estável pelo id.
        pool.sort(key=lambda m: (_int(m.get("sent_today"), 0), _int(m.get("id"), 0)))
        best = dict(pool[0])
        best["_spillover"] = not mailbox_matches_city(best.get("city"), city)
        best["_sent_today"] = _int(best.get("sent_today"), 0)
        best["_cap"] = _int(best.get("effective_cap"), 0)
        best["_warmup_state"] = best.get("warmup_state") or "cold"
        return best

    async def process_queue(
        self, limit: Optional[int] = None, now: Optional[datetime] = None
    ) -> dict:
        """Um tick do worker: envia ate' ao limite do chunk respeitando travas.

        Regras de bloqueio (nenhuma delas pode parar o tick inteiro):
          * cidade com `send_enabled=0` -> essas mensagens ficam na fila e o
            tick continua para as outras cidades (antes um `break` parava tudo:
            head-of-line blocking e a fila de Chicago travava o resto);
          * caixa sem folga -> spillover para outra caixa com folga;
          * sem NENHUMA folga -> tick pára e reporta `blocked_reason=mailbox_cap`
            (é backpressure esperado do warm-up, não uma falha).
        """
        now = now or datetime.now(timezone.utc)
        global_config = await db_service.get_outbound_config()

        # Reaper corre SEMPRE (mesmo com envio desligado): uma mensagem presa
        # em 'sending' por um deploy não pode ficar invisível até alguém ligar
        # o motor outra vez.
        await self.reap_stale_sending(now)

        if global_config.get("send_enabled") != "1":
            return {
                "status": "disabled",
                "sent": 0,
                "blocked_reason": "send_enabled_off",
                "blocked_detail": "Motor de envio desligado (send_enabled=0).",
            }

        if is_quiet_hours(
            now, global_config.get("quiet_hours_start"), global_config.get("quiet_hours_end")
        ):
            return {
                "status": "quiet_hours",
                "sent": 0,
                "blocked_reason": "quiet_hours",
                "blocked_detail": "Dentro da janela de silêncio.",
                "retry_at": quiet_hours_end_iso(now, global_config),
            }

        limit = limit or _int(
            getattr(settings, "OUTBOUND_WORKER_CHUNK", 10), 10
        )
        # Sequencia (Prioridade D): agenda o proximo passo antes de drenar a
        # fila, para que o passo 2 entre na MESMA janela de envio.
        await self.schedule_next_steps(now)
        # Janela de scan maior do que o chunk: mensagens de cidades bloqueadas
        # (ou inválidas) não podem esconder as que estão atrás delas na fila.
        scan_limit = min(500, max(limit * 10, 200))
        messages = await db_service.list_queued_outbound_messages(limit=scan_limit)
        day = day_key(now)
        sent = 0
        skipped = 0
        failed = 0
        deferred = 0
        touched_batches: set[int] = set()

        # Cache por cidade: config + snapshot de caixas. Evita 3 queries por
        # mensagem e mantém o mesmo snapshot coerente dentro do tick.
        city_config: dict[str, dict] = {}
        city_snapshot: dict[str, list[dict]] = {}
        blocked_cities: dict[str, str] = {}

        stop_reason: Optional[str] = None
        stop_detail: Optional[str] = None
        retry_at: Optional[str] = None

        for message in messages:
            if sent >= limit:
                break
            city = (message.get("city") or "").strip()
            city_key = city.upper()

            if city_key in blocked_cities:
                deferred += 1
                continue

            if city_key not in city_config:
                city_config[city_key] = await db_service.get_outbound_config(city or None)
            config = city_config[city_key]

            if config.get("send_enabled") != "1":
                blocked_cities[city_key] = "city_send_disabled"
                deferred += 1
                continue

            counter = await db_service.get_outbound_counter(city, day)
            daily_cap = _int(config.get("daily_send_cap"), 100)
            if daily_cap > 0 and _int(counter.get("sent"), 0) >= daily_cap:
                blocked_cities[city_key] = "city_daily_cap"
                deferred += 1
                continue

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
            if not is_sendable_contact(contact):
                await db_service.update_outbound_message(
                    message["id"], status="skipped", error="email not sendable"
                )
                skipped += 1
                continue

            if await db_service.is_suppressed(message["to_email"]):
                await db_service.update_outbound_message(
                    message["id"], status="suppressed", error="suppressed"
                )
                skipped += 1
                continue

            if city_key not in city_snapshot:
                city_snapshot[city_key] = await self._capacity_snapshot(
                    config, now, day
                )
            mailbox = self._pick_mailbox(city, city_snapshot[city_key])
            if not mailbox:
                # Sem folga em NENHUMA caixa: nada mais pode sair neste tick.
                total_cap = sum(
                    _int(m.get("effective_cap"), 0)
                    for m in city_snapshot[city_key]
                )
                total_sent = sum(
                    _int(m.get("sent_today"), 0)
                    for m in city_snapshot[city_key]
                )
                stop_reason = (
                    "no_mailbox" if not city_snapshot[city_key] else "mailbox_cap"
                )
                stop_detail = (
                    "Sem caixas de envio ligadas."
                    if stop_reason == "no_mailbox"
                    else (
                        f"Limite de caixa atingido: {total_sent}/{total_cap} hoje "
                        f"(warm-up {warmup_days(city_snapshot[city_key][0].get('warmup_started_at'), now)} dia(s))."
                    )
                )
                retry_at = next_utc_midnight(now)
                logger.info(
                    "[OUTBOUND] Tick parado: %s (%s). %s mensagem(ns) ficam na fila.",
                    stop_reason, stop_detail, len(messages) - sent - skipped - failed,
                )
                break

            if mailbox.get("_spillover"):
                logger.info(
                    "[OUTBOUND] Spillover: mensagem %s (%s) vai pela caixa %s "
                    "por falta de folga na cidade.",
                    message["id"], city or "-", mailbox.get("email"),
                )

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

            try:
                result = await gmail_sender.send(
                    mailbox,
                    message["to_email"],
                    subject or (message.get("subject") or ""),
                    body,
                    from_name=mailbox.get("display_name"),
                )
            except Exception as e:  # noqa: BLE001
                # Uma exceção da Gmail (rede/token) não pode matar o tick e
                # deixar a mensagem em 'sending' até ao reaper: marca failed e
                # segue para a próxima.
                logger.error(
                    "[OUTBOUND] Envio falhou com exceção (msg %s): %s",
                    message["id"], e,
                )
                await db_service.update_outbound_message(
                    message["id"],
                    status="failed",
                    error=f"send exception: {e}"[:300],
                    mailbox_id=mailbox["id"],
                )
                failed += 1
                continue
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
                # Consome a folga no snapshot em memória (o próximo pedido do
                # mesmo tick não pode reutilizar uma unidade já gasta).
                mailbox["sent_today"] = _int(mailbox.get("sent_today"), 0) + 1
                mailbox["remaining_today"] = max(
                    0, _int(mailbox.get("remaining_today"), 0) - 1
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

        out = {
            "status": "ok",
            "sent": sent,
            "skipped": skipped,
            "failed": failed,
            "deferred": deferred,
        }
        if blocked_cities:
            out["blocked_cities"] = blocked_cities
        if stop_reason:
            out["blocked_reason"] = stop_reason
            out["blocked_detail"] = stop_detail
            out["retry_at"] = retry_at
        return out

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
            sent_today = await db_service.count_mailbox_sent_today(mailbox["id"], day)
            row = mailbox_capacity_row(mailbox, global_config, now, sent_today)
            mailbox_rows.append(
                {
                    "id": row["id"],
                    "email": row["email"],
                    "city": row.get("city") or "",
                    "enabled": _int(row.get("enabled"), 0),
                    "daily_cap": _int(row.get("daily_cap"), 25),
                    "effective_cap": _int(row.get("effective_cap"), 0),
                    "sent_today": _int(row.get("sent_today"), 0),
                    "remaining_today": _int(row.get("remaining_today"), 0),
                    "warmup_state": row["warmup_state"],
                    "warmup_days": row["warmup_days"],
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

        queue = await db_service.outbound_queue_summary()
        queued = _int(queue.get("queued"), 0)
        oldest_at = queue.get("oldest_at")
        oldest_age_h = None
        if oldest_at:
            try:
                oldest_dt = datetime.strptime(
                    str(oldest_at), "%Y-%m-%d %H:%M:%S"
                ).replace(tzinfo=timezone.utc)
                oldest_age_h = round((now - oldest_dt).total_seconds() / 3600, 1)
            except ValueError:
                oldest_age_h = None

        enabled_rows = [m for m in mailbox_rows if _int(m["enabled"], 0)]
        remaining_capacity = sum(_int(m["remaining_today"], 0) for m in enabled_rows)
        cap_total = sum(_int(m["effective_cap"], 0) for m in enabled_rows)
        cap_sent = sum(_int(m["sent_today"], 0) for m in enabled_rows)
        quiet_now = is_quiet_hours(
            now,
            global_config.get("quiet_hours_start"),
            global_config.get("quiet_hours_end"),
        )

        # Motivo explícito do bloqueio (mostrado na UI e na Control Tower).
        queue_blocker: Optional[dict] = None
        if queued > 0:
            oldest_city = (queue.get("oldest_city") or "").strip()
            city_cfg = (
                await db_service.get_outbound_config(oldest_city or None)
                if oldest_city
                else global_config
            )
            if global_config.get("send_enabled") != "1":
                queue_blocker = {
                    "reason": "send_enabled_off",
                    "detail": "Motor de envio desligado (send_enabled=0).",
                }
            elif quiet_now:
                queue_blocker = {
                    "reason": "quiet_hours",
                    "detail": "Quiet hours: o worker retoma no fim da janela.",
                    "retry_at": quiet_hours_end_iso(now, global_config),
                }
            elif city_cfg.get("send_enabled") != "1":
                queue_blocker = {
                    "reason": "city_send_disabled",
                    "detail": (
                        f"Envio desligado para {oldest_city or 'a cidade da fila'} "
                        "(configuração por cidade)."
                    ),
                }
            elif remaining_capacity <= 0:
                ramp_day = enabled_rows[0]["warmup_days"] if enabled_rows else 0
                queue_blocker = {
                    "reason": "mailbox_cap",
                    "detail": (
                        f"Limite de caixa atingido: {cap_sent}/{cap_total} hoje "
                        f"(warm-up dia {ramp_day}). Retoma à meia-noite UTC."
                    ),
                    "retry_at": next_utc_midnight(now),
                }

        return {
            "send_enabled": global_config.get("send_enabled") == "1",
            "enrich_enabled": global_config.get("enrich_enabled") == "1",
            "quiet_hours_now": quiet_now,
            "day": day,
            "queued": queued,
            "queue_oldest_at": oldest_at,
            "queue_oldest_age_hours": oldest_age_h,
            "queue_oldest_city": (queue.get("oldest_city") or ""),
            "mailbox_remaining_today": remaining_capacity,
            "mailbox_cap_total": cap_total,
            "mailbox_sent_today": cap_sent,
            "queue_blocker": queue_blocker,
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
                    now
                    - timedelta(
                        minutes=_int(
                            getattr(settings, "OUTBOUND_STALE_SENDING_MINUTES", 15), 15
                        )
                    )
                )
            ),
        }


outbound_engine = OutboundEngine()

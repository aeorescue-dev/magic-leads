"""Auto-scheduler de campanhas de voz B2B.

Consome a fila por cidade/nicho, aplica `can_call()` e dispara Telnyx +
vitrine sem clique individual. Sem chaves Telnyx corre em dry-run.
"""
from __future__ import annotations

import asyncio
import json
import random
from datetime import datetime, timedelta, timezone

import anyio

from ..config import settings
from ..utils.logger import logger
from . import b2b_voice, telnyx_voice, voice_audio_cache, voice_scripts
from .timeutil import NY_TZ, day_key, next_day_hour_utc, next_or_today_hour_utc

MAX_GUARD_MULTIPLIER = 10
# Erros que nao sao do contacto: pausam a campanha em vez de o saltar.
TRANSIENT_API_REASONS = {
    "http_401",
    "http_402",
    "http_403",
    "http_429",
    "network_error",
}
# Bloqueios que acontecem antes de a Telnyx receber a chamada: a reserva do
# DID pode ser devolvida sem risco de ultrapassar o cap.
PRE_CALL_BLOCK_REASONS = {
    "dnc_not_checked",
    "dnc_stale",
    "dnc_listed",
    "suppressed",
    "invalid_phone",
    "not_business",
    "state_not_enabled",
    "status_blocked",
    "attempt_cap",
    "showcase_unavailable",
    "script_not_approved",
    "assistant_missing",
}


def _campaign_start_hour(campaign: dict) -> int:
    try:
        return max(0, min(23, int(campaign.get("start_hour_et") or 9)))
    except (TypeError, ValueError):
        return 9


def _did_for_city(city: str) -> str:
    """Resolve o DID local da cidade a partir de VOICE_DID_BY_CITY.

    Aceita JSON ({"dallas":"+14699607326"}) ou pares simples
    (dallas=+14699607326,new york=+1929...). Cidade desconhecida -> "".
    """
    raw = str(getattr(settings, "VOICE_DID_BY_CITY", "") or "").strip()
    if not raw:
        return ""
    mapping: dict = {}
    try:
        if raw.startswith("{"):
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                mapping = parsed
        else:
            for part in raw.split(","):
                key, sep, value = part.partition("=")
                if sep and key.strip():
                    mapping[key.strip()] = value.strip()
    except (TypeError, ValueError, json.JSONDecodeError):
        logger.warning("[VOICE] VOICE_DID_BY_CITY invalido; ignorado")
        return ""
    wanted = str(city or "").strip().lower()
    for key, value in mapping.items():
        if str(key).strip().lower() != wanted:
            continue
        did = str(value or "").strip()
        if len(did) == 12 and did.startswith("+1"):
            return did
        logger.warning("[VOICE] DID invalido para %s: %r", city, value)
        return ""
    return ""


def _did_pool_for_city(city: str) -> list[str]:
    """Resolve o pool de DIDs locais de `VOICE_DID_POOL_BY_CITY`.

    Formato: {"new york":["+1929...","+1917..."]}. Sem pool configurado,
    cai no mapeamento singular de `_did_for_city` (compatibilidade Dallas).
    """
    raw = str(getattr(settings, "VOICE_DID_POOL_BY_CITY", "") or "").strip()
    if raw:
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            logger.warning("[VOICE] VOICE_DID_POOL_BY_CITY invalido; ignorado")
            parsed = {}
        if isinstance(parsed, dict):
            alias = b2b_voice.CITY_ALIASES.get(str(city or "").strip().upper())
            wanted = str(alias or city or "").strip().lower()
            for key, value in parsed.items():
                if str(key).strip().lower() != wanted:
                    continue
                values = value if isinstance(value, list) else [value]
                pool: list[str] = []
                for item in values:
                    did = str(item or "").strip()
                    if len(did) == 12 and did.startswith("+1"):
                        if did not in pool:
                            pool.append(did)
                    else:
                        logger.warning(
                            "[VOICE] DID invalido no pool de %s: %r", city, item
                        )
                return pool
    # Sem pool explicito, o chamador usa o mapeamento singular legado
    # (`_did_for_city`), preservando Dallas e o transbordo secundario.
    return []


def _campaign_batch_size(campaign: dict) -> int:
    """Escolhe o lote do dia a partir de `batch_plan` (ramp) ou `batch_size`."""
    raw = campaign.get("batch_plan")
    if raw:
        try:
            plan = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(plan, list) and plan:
                index = max(0, int(campaign.get("plan_index") or 0))
                return max(1, int(plan[min(index, len(plan) - 1)]))
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
    try:
        return max(
            1,
            int(
                campaign.get("batch_size")
                or campaign.get("max_calls")
                or 25
            ),
        )
    except (TypeError, ValueError):
        return 25


async def _run_sync(fn, *args):
    return await anyio.to_thread.run_sync(fn, *args)


async def run_campaign(campaign_id: int) -> None:
    if bool(getattr(settings, "VOICE_FREEZE", True)):
        logger.warning(
            "[VOICE] VOICE_FREEZE=1: campanha %s nao arranca", campaign_id
        )
        return
    campaign = await _run_sync(b2b_voice.get_campaign, campaign_id)
    if not campaign or campaign.get("status") != "running":
        return

    start_hour = _campaign_start_hour(campaign)
    now = b2b_voice._utc_now()
    if now.astimezone(NY_TZ).hour < start_hour:
        next_batch = next_or_today_hour_utc(start_hour, now=now)
        await _run_sync(
            lambda: b2b_voice.update_campaign(
                campaign_id,
                status="paused",
                next_batch_at=next_batch,
                error="before_start_hour",
            )
        )
        logger.info(
            "[AUTO-DIALER] campanha %s aguarda a hora de inicio (%02d:00 ET)",
            campaign_id,
            start_hour,
        )
        return

    max_calls = max(1, int(campaign.get("quota_total") or campaign.get("max_calls") or 25))
    batch_size = _campaign_batch_size(campaign)
    calls = int(campaign.get("calls_started") or 0)
    initial_calls = calls
    batch_end = min(max_calls, calls + batch_size)
    include_fallback = bool(int(campaign.get("include_fallback", 1)))
    delay = max(
        0,
        int(
            campaign.get("call_interval_seconds")
            or getattr(settings, "VOICE_AUTOSCHED_DELAY_SECONDS", 30)
        ),
    )
    jitter = max(
        0.0, float(getattr(settings, "VOICE_CALL_INTERVAL_JITTER", 0.2) or 0)
    )
    pause_every = max(
        0, int(getattr(settings, "VOICE_PAUSE_EVERY_CALLS", 25) or 0)
    )
    pause_seconds = max(
        0, int(getattr(settings, "VOICE_PAUSE_SECONDS", 600) or 0)
    )
    did_cap = max(1, int(getattr(settings, "VOICE_DID_DAILY_CAP", 50) or 50))
    secondary_from = str(
        getattr(settings, "TELNYX_FROM_NUMBER_SECONDARY", "") or ""
    ).strip()
    trade_plan: list[dict] = []
    raw_plan = campaign.get("trade_plan")
    if raw_plan:
        try:
            parsed = json.loads(raw_plan) if isinstance(raw_plan, str) else raw_plan
            if isinstance(parsed, list):
                trade_plan = [
                    {
                        "trade": str(item.get("trade") or "").strip(),
                        "quota": max(0, int(item.get("quota") or 0)),
                    }
                    for item in parsed
                    if isinstance(item, dict)
                ]
        except (TypeError, ValueError, json.JSONDecodeError):
            trade_plan = []
    if not trade_plan:
        trade_plan = [
            {
                "trade": str(campaign.get("trade") or "").strip(),
                "quota": max_calls,
            }
        ]
    used_by_trade = await _run_sync(
        b2b_voice.campaign_trade_counts, campaign_id
    )

    if voice_audio_cache.enabled() and voice_audio_cache.mode() == "shared":
        shared_name = str(
            getattr(settings, "VOICE_TTS_SHARED_NAME", "there") or "there"
        )
        prewarm_texts: list[str] = []
        for item in trade_plan:
            trade_code = str(item.get("trade") or "").strip()
            if not trade_code or int(item.get("quota") or 0) <= 0:
                continue
            try:
                rendered = voice_scripts.render(
                    trade_code,
                    shared_name,
                    campaign.get("city") or "",
                    0,
                    "",
                    "",
                )
                prewarm_texts.append(str(rendered.get("greeting") or ""))
            except Exception:  # noqa: BLE001
                continue
        if prewarm_texts:
            try:
                cleaned = await _run_sync(voice_audio_cache.cleanup)
                if cleaned.get("removed"):
                    logger.info(
                        "[TTS-CACHE] cleanup removeu %s áudios",
                        cleaned.get("removed"),
                    )
            except Exception:  # noqa: BLE001
                pass
            warmed = await _run_sync(voice_audio_cache.prewarm, prewarm_texts)
            logger.info(
                "[TTS-CACHE] prewarm shared: %s criados, %s hits",
                warmed.get("created"),
                warmed.get("hits"),
            )

    async def next_trade_batch(limit: int) -> tuple[str, list[dict]]:
        for item in trade_plan:
            trade_code = str(item.get("trade") or "").strip()
            target = int(item.get("quota") or 0)
            used = int(used_by_trade.get(trade_code, 0))
            if target <= 0 or used >= target:
                continue
            # Nunca buscar mais candidatos do que a quota restante deste trade.
            # Sem este limite, o primeiro trade consumia o lote inteiro.
            remaining = max(1, target - used)
            rows = await _run_sync(
                b2b_voice.campaign_candidates,
                campaign_id,
                campaign.get("city") or "",
                trade_code,
                min(limit, remaining),
                include_fallback,
            )
            if rows:
                return trade_code, rows
            # Sem contactos para este trade: não voltar a tentar neste run.
            used_by_trade[trade_code] = target
        return "", []

    guard = 0
    max_guard = max(1, batch_end - calls) * MAX_GUARD_MULTIPLIER + 100

    try:
        while calls < batch_end and guard < max_guard:
            current = await _run_sync(b2b_voice.get_campaign, campaign_id)
            if not current or current.get("status") != "running":
                return
            city = current.get("city") or ""
            trade, batch = await next_trade_batch(min(25, batch_end - calls))
            if not batch:
                break
            progressed = False
            for company in batch:
                current = await _run_sync(b2b_voice.get_campaign, campaign_id)
                if not current or current.get("status") != "running":
                    return
                if calls >= batch_end:
                    break
                city_name = current.get("city") or city
                pool = _did_pool_for_city(city_name)
                if pool:
                    # Nao reservar DID para um contacto que o gate ja rejeita
                    # (ex.: DNC em falta). Isso queimaria capacidade do pool.
                    gate = await _run_sync(b2b_voice.can_call, company)
                    if not gate.get("allowed"):
                        reasons = [
                            str(item) for item in (gate.get("reasons") or [])
                        ]
                        if "outside_hours" in reasons:
                            next_batch = (
                                b2b_voice._utc_now() + timedelta(hours=1)
                            ).isoformat()
                            await _run_sync(
                                lambda: b2b_voice.update_campaign(
                                    campaign_id,
                                    status="paused",
                                    next_batch_at=next_batch,
                                    error="outside_hours",
                                )
                            )
                            logger.info(
                                "[AUTO-DIALER] campanha %s pausada: fora da janela",
                                campaign_id,
                            )
                            return
                        await _run_sync(
                            b2b_voice.skip_campaign_company,
                            campaign_id,
                            company["id"],
                            ",".join(reasons) or "blocked",
                        )
                        await _run_sync(
                            b2b_voice.bump_campaign, campaign_id, 0, 0, 1
                        )
                        continue
                    from_number = await _run_sync(
                        b2b_voice.reserve_did, pool, day_key(), did_cap
                    )
                    if not from_number:
                        next_batch = next_day_hour_utc(
                            start_hour, now=b2b_voice._utc_now()
                        )
                        await _run_sync(
                            lambda: b2b_voice.update_campaign(
                                campaign_id,
                                status="paused",
                                next_batch_at=next_batch,
                                error="did_capacity_reached",
                            )
                        )
                        logger.warning(
                            "[AUTO-DIALER] campanha %s pausada: pool de DIDs "
                            "esgotado no dia",
                            campaign_id,
                        )
                        return
                else:
                    city_did = _did_for_city(city_name)
                    from_number = city_did or (
                        secondary_from
                        if secondary_from and calls >= did_cap
                        else ""
                    )
                result = await _run_sync(
                    telnyx_voice.create_call,
                    company,
                    str(campaign_id),
                    "",
                    city,
                    trade,
                    bool(campaign.get("dry_run")),
                    from_number,
                )
                if not result.get("ok"):
                    reason = str(result.get("reason") or "blocked")
                    if reason in (
                        "total_budget_reached",
                        "days_limit_reached",
                    ):
                        if from_number:
                            await _run_sync(
                                b2b_voice.release_did, from_number, day_key()
                            )
                        await _run_sync(
                            lambda: b2b_voice.update_campaign(
                                campaign_id,
                                status="completed",
                                finished_at=datetime.now(
                                    timezone.utc
                                ).isoformat(),
                                next_batch_at=None,
                                error=reason[:300],
                            )
                        )
                        logger.info(
                            "[AUTO-DIALER] campanha %s terminada: %s",
                            campaign_id,
                            reason,
                        )
                        return
                    if reason == "outside_hours":
                        # Fora da janela local do estado: nao queimar o
                        # contacto. Pausa e o loop de retoma tenta daqui a
                        # uma hora (o candidato continua na fila).
                        if from_number:
                            await _run_sync(
                                b2b_voice.release_did, from_number, day_key()
                            )
                        next_batch = (
                            b2b_voice._utc_now() + timedelta(hours=1)
                        ).isoformat()
                        await _run_sync(
                            lambda: b2b_voice.update_campaign(
                                campaign_id,
                                status="paused",
                                next_batch_at=next_batch,
                                error="outside_hours",
                            )
                        )
                        logger.info(
                            "[AUTO-DIALER] campanha %s pausada: fora da janela",
                            campaign_id,
                        )
                        return
                    if reason in (
                        "daily_budget_reached",
                        "daily_calls_reached",
                    ):
                        if from_number:
                            await _run_sync(
                                b2b_voice.release_did, from_number, day_key()
                            )
                        next_batch = next_day_hour_utc(
                            start_hour, now=b2b_voice._utc_now()
                        )
                        await _run_sync(
                            lambda: b2b_voice.update_campaign(
                                campaign_id,
                                status="paused",
                                next_batch_at=next_batch,
                                error=str(result.get("reason"))[:300],
                                plan_index=int(current.get("plan_index") or 0)
                                + 1,
                            )
                        )
                        logger.info(
                            "[AUTO-DIALER] campanha %s pausada: %s",
                            campaign_id,
                            result.get("reason"),
                        )
                        return
                    if reason in TRANSIENT_API_REASONS or reason.startswith(
                        "http_5"
                    ):
                        # Erro de conta/rede: a chamada nunca saiu. Remove a
                        # linha failed para o contacto voltar a ser candidato
                        # e pausa; nao marca a empresa como saltada.
                        if from_number:
                            await _run_sync(
                                b2b_voice.release_did, from_number, day_key()
                            )
                        voice_call_id = result.get("voice_call_id")
                        if voice_call_id:
                            await _run_sync(
                                b2b_voice.delete_voice_call,
                                int(voice_call_id),
                            )
                        next_batch = (
                            b2b_voice._utc_now() + timedelta(hours=1)
                        ).isoformat()
                        await _run_sync(
                            lambda: b2b_voice.update_campaign(
                                campaign_id,
                                status="paused",
                                next_batch_at=next_batch,
                                error=reason[:300],
                            )
                        )
                        logger.warning(
                            "[AUTO-DIALER] campanha %s pausada (transitorio): %s",
                            campaign_id,
                            reason,
                        )
                        return
                    if from_number and reason in PRE_CALL_BLOCK_REASONS:
                        await _run_sync(
                            b2b_voice.release_did, from_number, day_key()
                        )
                    await _run_sync(
                        b2b_voice.skip_campaign_company,
                        campaign_id,
                        company["id"],
                        str(result.get("reason") or "blocked"),
                    )
                    await _run_sync(
                        b2b_voice.bump_campaign, campaign_id, 0, 0, 1
                    )
                    continue

                calls += 1
                used_by_trade[trade] = int(used_by_trade.get(trade, 0)) + 1
                progressed = True
                await _run_sync(b2b_voice.bump_campaign, campaign_id, 1, 0, 0)
                # A vitrine so e enviada depois de o contacto atender e dar
                # consentimento (tool capture_email), nunca no dial.

                if not result.get("dry_run") and delay and calls < batch_end:
                    low = max(0.0, delay * (1.0 - jitter))
                    high = max(low, delay * (1.0 + jitter))
                    await asyncio.sleep(random.uniform(low, high))
                    if (
                        pause_every
                        and pause_seconds
                        and calls % pause_every == 0
                        and calls < batch_end
                    ):
                        await asyncio.sleep(pause_seconds)

            guard += 1
            if not progressed:
                break

        final = await _run_sync(b2b_voice.get_campaign, campaign_id)
        if final and final.get("status") == "running":
            if calls >= max_calls or calls <= initial_calls:
                await _run_sync(
                    lambda: b2b_voice.update_campaign(
                        campaign_id,
                        status="completed",
                        finished_at=b2b_voice._iso(),
                        next_batch_at=None,
                    )
                )
            else:
                next_batch = next_day_hour_utc(
                    _campaign_start_hour(final or campaign),
                    now=b2b_voice._utc_now(),
                )
                await _run_sync(
                    lambda: b2b_voice.update_campaign(
                        campaign_id,
                        status="paused",
                        next_batch_at=next_batch,
                        plan_index=int(final.get("plan_index") or 0) + 1,
                    )
                )
    except Exception as exc:  # noqa: BLE001
        logger.error("[AUTO-DIALER] campanha %s falhou: %s", campaign_id, exc)
        message = str(exc)[:300]
        await _run_sync(
            lambda: b2b_voice.update_campaign(
                campaign_id,
                status="error",
                error=message,
                finished_at=b2b_voice._iso(),
            )
        )

"""Auto-scheduler de campanhas de voz B2B.

Consome a fila por cidade/nicho, aplica `can_call()` e dispara Telnyx +
vitrine sem clique individual. Sem chaves Telnyx corre em dry-run.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import anyio

from ..config import settings
from ..utils.logger import logger
from . import b2b_voice, telnyx_voice
from .timeutil import NY_TZ, next_day_hour_utc, next_or_today_hour_utc

MAX_GUARD_MULTIPLIER = 10
# Erros que nao sao do contacto: pausam a campanha em vez de o saltar.
TRANSIENT_API_REASONS = {
    "http_401",
    "http_402",
    "http_403",
    "http_429",
    "network_error",
}


def _campaign_start_hour(campaign: dict) -> int:
    try:
        return max(0, min(23, int(campaign.get("start_hour_et") or 9)))
    except (TypeError, ValueError):
        return 9


async def _run_sync(fn, *args):
    return await anyio.to_thread.run_sync(fn, *args)


async def run_campaign(campaign_id: int) -> None:
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
    batch_size = max(1, int(campaign.get("batch_size") or max_calls))
    calls = int(campaign.get("calls_started") or 0)
    initial_calls = calls
    batch_end = min(max_calls, calls + batch_size)
    include_fallback = bool(int(campaign.get("include_fallback", 1)))
    delay = max(0, int(getattr(settings, "VOICE_AUTOSCHED_DELAY_SECONDS", 30)))
    guard = 0
    max_guard = max(1, batch_end - calls) * MAX_GUARD_MULTIPLIER + 100

    try:
        while calls < batch_end and guard < max_guard:
            current = await _run_sync(b2b_voice.get_campaign, campaign_id)
            if not current or current.get("status") != "running":
                return
            city = current.get("city") or ""
            trade = current.get("trade") or ""
            batch = await _run_sync(
                b2b_voice.campaign_candidates,
                campaign_id,
                city,
                trade,
                min(25, batch_end - calls),
                include_fallback,
            )
            if not batch:
                break
            progressed = False
            for company in batch:
                current = await _run_sync(b2b_voice.get_campaign, campaign_id)
                if not current or current.get("status") != "running":
                    return
                if calls >= batch_end:
                    break
                result = await _run_sync(
                    telnyx_voice.create_call,
                    company,
                    str(campaign_id),
                    "",
                    city,
                    trade,
                    bool(campaign.get("dry_run")),
                )
                if not result.get("ok"):
                    reason = str(result.get("reason") or "blocked")
                    if reason in (
                        "total_budget_reached",
                        "days_limit_reached",
                    ):
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
                        next_batch = next_day_hour_utc(
                            start_hour, now=b2b_voice._utc_now()
                        )
                        await _run_sync(
                            lambda: b2b_voice.update_campaign(
                                campaign_id,
                                status="paused",
                                next_batch_at=next_batch,
                                error=str(result.get("reason"))[:300],
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
                progressed = True
                await _run_sync(b2b_voice.bump_campaign, campaign_id, 1, 0, 0)
                # A vitrine so e enviada depois de o contacto atender e dar
                # consentimento (tool capture_email), nunca no dial.

                if not result.get("dry_run") and delay:
                    await asyncio.sleep(delay)

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

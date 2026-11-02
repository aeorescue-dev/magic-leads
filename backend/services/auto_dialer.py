"""Auto-scheduler de campanhas de voz B2B.

Consome a fila por cidade/nicho, aplica `can_call()` e dispara Telnyx +
vitrine sem clique individual. Sem chaves Telnyx corre em dry-run.
"""
from __future__ import annotations

import asyncio

import anyio

from ..config import settings
from ..utils.logger import logger
from . import b2b_voice, telnyx_voice

MAX_GUARD_MULTIPLIER = 10


async def _run_sync(fn, *args):
    return await anyio.to_thread.run_sync(fn, *args)


async def run_campaign(campaign_id: int) -> None:
    campaign = await _run_sync(b2b_voice.get_campaign, campaign_id)
    if not campaign or campaign.get("status") != "running":
        return

    max_calls = max(1, int(campaign.get("max_calls") or 25))
    calls = int(campaign.get("calls_started") or 0)
    delay = max(0, int(getattr(settings, "VOICE_AUTOSCHED_DELAY_SECONDS", 30)))
    guard = 0
    max_guard = max_calls * MAX_GUARD_MULTIPLIER + 100

    try:
        while calls < max_calls and guard < max_guard:
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
                min(25, max_calls - calls),
            )
            if not batch:
                break
            progressed = False
            for company in batch:
                current = await _run_sync(b2b_voice.get_campaign, campaign_id)
                if not current or current.get("status") != "running":
                    return
                if calls >= max_calls:
                    break
                result = await _run_sync(
                    telnyx_voice.create_call,
                    company,
                    str(campaign_id),
                    "",
                    city,
                    trade,
                )
                if not result.get("ok"):
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
                showcase_result = await _run_sync(
                    telnyx_voice.send_showcase_for_call,
                    result["voice_call_id"],
                    city,
                    trade,
                )
                if showcase_result.get("ok"):
                    await _run_sync(
                        b2b_voice.bump_campaign, campaign_id, 0, 1, 0
                    )
                else:
                    logger.warning(
                        "[AUTO-DIALER] vitrine falhou para empresa %s: %s",
                        company["id"],
                        showcase_result.get("reason"),
                    )
                    await _run_sync(
                        b2b_voice.bump_campaign, campaign_id, 0, 0, 1
                    )

                if not result.get("dry_run") and delay:
                    await asyncio.sleep(delay)

            guard += 1
            if not progressed:
                break

        final = await _run_sync(b2b_voice.get_campaign, campaign_id)
        if final and final.get("status") == "running":
            await _run_sync(
                lambda: b2b_voice.update_campaign(
                    campaign_id,
                    status="completed",
                    finished_at=b2b_voice._iso(),
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

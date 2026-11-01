"""Backfill em lote de proprietários (`owner_name IS NULL`).

Motivo (auditoria 01/11/2026): o enriquecimento de owner corria uma única vez,
inline, apenas em leads novos. Uma oscilação da API (Socrata/CKAN) deixava o
lead sem dono para sempre, porque não havia retry nem backfill.

Este módulo corre em processo (sem cron externo), com quota por cidade/dia,
cursor descendente por `id` e wrap-around quando chega ao início. Não envia
e-mail nem toca em nada além de `owner_name`/`mailing_address`.
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from typing import Iterable, Optional

from ..utils.logger import logger
from . import timeutil
from .db import db_service
from .enrichment import owner_enrichment

CITIES = ("NYC", "CHICAGO", "DALLAS", "BOSTON")
BATCH = 25
MIN_INTERVAL_SECONDS = 1.0
_lock = asyncio.Lock()


def cities() -> tuple[str, ...]:
    raw = (os.getenv("OWNER_BACKFILL_CITIES") or "").strip()
    if not raw:
        return CITIES
    return tuple(c.strip().upper() for c in raw.split(",") if c.strip())


def per_city_day() -> int:
    raw = (os.getenv("OWNER_BACKFILL_PER_CITY_DAY") or "").strip()
    if raw:
        try:
            return max(0, min(int(raw), 5000))
        except ValueError:
            pass
    from ..config import settings

    try:
        return max(0, int(getattr(settings, "OWNER_BACKFILL_PER_CITY_DAY", 200)))
    except (TypeError, ValueError):
        return 200


def _is_real_address(value: Optional[str]) -> bool:
    text = (value or "").strip()
    return bool(text) and not text.upper().startswith("B2B CONTACT")


async def run_once(
    now: Optional[datetime] = None,
    cities_override: Optional[Iterable[str]] = None,
) -> dict:
    """Um ciclo de backfill: até `per_city_day()` leads por cidade."""
    if _lock.locked():
        return {"status": "busy", "filled": 0, "cities": {}}
    async with _lock:
        now = now or datetime.now(timezone.utc)
        day = timeutil.day_key(now)
        quota = per_city_day()
        stats: dict[str, dict] = {}
        total_filled = 0
        if quota <= 0:
            return {"status": "disabled", "filled": 0, "cities": {}}

        for city in (cities_override or cities()):
            state = await db_service.get_owner_backfill_state(city, day)
            remaining = quota - int(state.get("jobs_today") or 0)
            if remaining <= 0:
                stats[city] = {"status": "quota", "processed": 0, "filled": 0}
                continue
            before_id = int(state.get("last_id") or 0)
            take = min(BATCH, remaining)
            rows = await db_service.list_leads_missing_owner(city, before_id, take)
            if not rows:
                # Fim da lista: reinicia o cursor para o próximo ciclo.
                await db_service.bump_owner_backfill_state(city, day, 0, 0)
                stats[city] = {
                    "status": "wrapped",
                    "processed": 0,
                    "filled": 0,
                    "cursor": 0,
                }
                continue

            filled = 0
            processed = 0
            for lead in rows:
                if not _is_real_address(lead.get("address")):
                    continue
                processed += 1
                try:
                    result = await owner_enrichment.enrich(
                        lead.get("address") or "",
                        lead.get("city") or city,
                        bbl=lead.get("bbl"),
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "[OWNER-BACKFILL] %s lead %s falhou: %s",
                        city, lead.get("id"), exc,
                    )
                    result = None
                owner = (result or {}).get("owner_name")
                if owner:
                    try:
                        await db_service.update_owner_details(
                            int(lead["id"]),
                            owner,
                            (result or {}).get("mailing_address"),
                        )
                        filled += 1
                    except Exception as exc:  # noqa: BLE001
                        logger.warning(
                            "[OWNER-BACKFILL] falha ao gravar owner do lead %s: %s",
                            lead.get("id"), exc,
                        )
                await asyncio.sleep(MIN_INTERVAL_SECONDS)

            cursor = int(rows[-1]["id"])
            await db_service.bump_owner_backfill_state(city, day, processed, cursor)
            total_filled += filled
            stats[city] = {
                "status": "ok",
                "processed": processed,
                "filled": filled,
                "cursor": cursor,
            }
            logger.info("[OWNER-BACKFILL] %s: %s", city, stats[city])
        return {"status": "ok", "filled": total_filled, "cities": stats}

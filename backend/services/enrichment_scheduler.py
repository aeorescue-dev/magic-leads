"""Scheduler autónomo de enriquecimento de empreiteiros (Fase 3).

Corre 24/7 em processo (sem cron externo), 4 jobs em paralelo, com quota por
cidade (default 300/dia). Só atua em cidades com `enrich_enabled=1`; nunca
envia e-mail. Estágios:
  new -> (OSM/Overpass) -> domain -> (SMTP RCPT + anti-catch-all) -> ready
  sem site / catch-all / sem e-mail após 2 tentativas -> quarantined
"""
from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timezone
from typing import Iterable, Optional

from ..utils.logger import logger
from . import entity_bridge
from .company_discovery import CompanyDiscovery
from .db import db_service
from .domain_resolver import resolve_domain

DEFAULT_CITIES = ("NYC", "CHICAGO", "BOSTON")
CONCURRENCY = 4
PER_CITY_DAY = 300
TICK_SECONDS = 60
OVERPASS_MIN_INTERVAL = 1.1
MAX_ATTEMPTS = 2

_global_sem = asyncio.Semaphore(CONCURRENCY)
_overpass_lock = asyncio.Lock()
_last_overpass_at = 0.0
_run_lock = asyncio.Lock()
_discovery = CompanyDiscovery()


def cities() -> tuple[str, ...]:
    raw = (os.getenv("ENRICH_ENTITY_CITIES") or "").strip()
    if not raw:
        return DEFAULT_CITIES
    return tuple(c.strip().upper() for c in raw.split(",") if c.strip())


def per_city_day() -> int:
    try:
        return max(1, min(int(os.getenv("ENRICH_ENTITIES_PER_CITY_DAY", PER_CITY_DAY)), 2000))
    except ValueError:
        return PER_CITY_DAY


async def _throttle_overpass() -> None:
    """Uma consulta Overpass a cada ~1,1 s (política de uso público)."""
    global _last_overpass_at
    async with _overpass_lock:
        wait = OVERPASS_MIN_INTERVAL - (time.monotonic() - _last_overpass_at)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_overpass_at = time.monotonic()


async def _domain_stage(entity: dict) -> str:
    async with _global_sem:
        await _throttle_overpass()
        resolved = await resolve_domain(entity.get("legal_name") or "", entity.get("city") or "")
    if resolved:
        await db_service.mark_contractor_domain_attempt(
            int(entity["id"]),
            resolved["domain"],
            float(resolved.get("confidence") or 0.0),
            MAX_ATTEMPTS,
        )
        return "domain"
    await db_service.mark_contractor_domain_attempt(
        int(entity["id"]), None, 0.0, MAX_ATTEMPTS
    )
    return "no_domain"


async def _email_stage(entity: dict) -> str:
    lead = {
        "owner_name": entity.get("legal_name") or "",
        "city": entity.get("city") or "",
        "state": entity.get("state") or "",
    }
    domain = entity.get("domain") or ""
    async with _global_sem:
        validation = await asyncio.to_thread(
            lambda: _discovery.validate_domain(domain, lead)
        )
    if getattr(validation, "catch_all", False):
        await db_service.mark_contractor_email_attempt(
            int(entity["id"]), None, "catch_all", MAX_ATTEMPTS
        )
        return "catch_all"
    accepted = list(getattr(validation, "accepted", []) or [])
    if accepted:
        await db_service.mark_contractor_email_attempt(
            int(entity["id"]), accepted[0], "valid", MAX_ATTEMPTS
        )
        updated = await db_service.get_contractor_entity(int(entity["id"]))
        return await entity_bridge.bridge_entity(updated or {**entity, "email": accepted[0]})
    await db_service.mark_contractor_email_attempt(
        int(entity["id"]), None, "unknown", MAX_ATTEMPTS
    )
    return "no_email"


async def run_once(
    now: Optional[datetime] = None, cities_override: Optional[Iterable[str]] = None
) -> dict:
    """Um ciclo: quota por cidade, estágios e contagens por resultado."""
    if _run_lock.locked():
        return {"status": "busy", "processed": 0, "cities": {}}
    async with _run_lock:
        now = now or datetime.now(timezone.utc)
        day = now.strftime("%Y-%m-%d")
        stats: dict[str, dict] = {}
        total = 0
        for city in (cities_override or cities()):
            config = await db_service.get_outbound_config(city)
            if config.get("enrich_enabled") != "1":
                stats[city] = {"status": "disabled", "processed": 0}
                continue
            state = await db_service.get_city_enrichment_state(city, day)
            remaining = per_city_day() - int(state.get("jobs_today") or 0)
            if remaining <= 0:
                stats[city] = {"status": "quota", "processed": 0}
                continue
            take = min(CONCURRENCY, remaining)
            # Entidades que ficaram 'ready' antes da ponte existir.
            bridged_now = await entity_bridge.bridge_ready_entities(city, take)
            domain_jobs = await db_service.list_entities_for_domain(city, take)
            email_jobs = await db_service.list_entities_for_email(city, take)
            tasks = [_domain_stage(e) for e in domain_jobs]
            tasks += [_email_stage(e) for e in email_jobs]
            if not tasks and not bridged_now.get("processed"):
                stats[city] = {"status": "idle", "processed": 0}
                continue
            results = await asyncio.gather(*tasks, return_exceptions=True)
            counts: dict[str, int] = dict(bridged_now.get("outcomes") or {})
            for result in results:
                if isinstance(result, Exception):
                    logger.warning("[ENRICH-SCHED] job falhou (%s): %s", city, result)
                    continue
                counts[result] = counts.get(result, 0) + 1
            processed = sum(counts.values())
            total += processed
            last_id = (domain_jobs + email_jobs)[-1]["id"] if (domain_jobs or email_jobs) else None
            await db_service.bump_city_enrichment_state(city, day, processed, last_id)
            stats[city] = {"status": "ok", "processed": processed, "outcomes": counts}
            logger.info("[ENRICH-SCHED] %s: %s", city, stats[city])
        return {"status": "ok", "processed": total, "cities": stats}


async def scheduler_loop() -> None:
    logger.info(
        "[ENRICH-SCHED] ativo: cidades=%s, concorrência=%s, quota=%s/cidade/dia",
        ",".join(cities()),
        CONCURRENCY,
        per_city_day(),
    )
    while True:
        try:
            await asyncio.sleep(TICK_SECONDS)
            await run_once()
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            logger.warning("[ENRICH-SCHED] tick falhou: %s", e)

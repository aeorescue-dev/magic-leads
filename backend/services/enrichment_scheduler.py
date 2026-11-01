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
from . import brave_search, entity_bridge, licensing_sources, osm_extract, owner_email
from .company_discovery import CompanyDiscovery
from .db import db_service
from .domain_resolver import resolve_domain

DEFAULT_CITIES = ("NYC", "CHICAGO", "BOSTON", "DALLAS")
CONCURRENCY = 4
PER_CITY_DAY = 750
TICK_SECONDS = 60
OVERPASS_MIN_INTERVAL = 1.1
MAX_ATTEMPTS = 2

_global_sem = asyncio.Semaphore(CONCURRENCY)
_overpass_lock = asyncio.Lock()
_last_overpass_at = 0.0
_run_lock = asyncio.Lock()
_source_lock = asyncio.Lock()
_ticks = [0]
_discovery = CompanyDiscovery()
SOURCE_INTERVAL_DAYS = 7
LICENSES_PER_RUN = 2000
OSM_PER_CITY = 800


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
        # 1) busca paga (Brave) com cache/orcamento: maior cobertura.
        try:
            resolved = await brave_search.find_domain(
                entity.get("legal_name") or "", entity.get("city") or ""
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[BRAVE] erro inesperado: %s", exc)
            resolved = None
        # 2) OSM/Overpass (bloqueado no Railway; circuit breaker).
        if not resolved:
            resolved = await resolve_domain(
                entity.get("legal_name") or "", entity.get("city") or ""
            )
        if not resolved:
            # Fallback autónomo: heurística de domínio (DNS + site + corroboração)
            # quando o Overpass está bloqueado/indisponível.
            lead = {
                "owner_name": entity.get("legal_name") or "",
                "city": entity.get("city") or "",
            }
            found = await asyncio.to_thread(
                _discovery.heuristic_domain,
                lead,
                _discovery._clock() + 12.0,
            )
            if found:
                resolved = {
                    "domain": found.domain,
                    "confidence": 0.55,
                    "source": "heuristic",
                    "snippet": getattr(found, "snippet", "") or "",
                }
    if resolved:
        await db_service.mark_contractor_domain_attempt(
            int(entity["id"]),
            resolved["domain"],
            float(resolved.get("confidence") or 0.0),
            MAX_ATTEMPTS,
            resolved.get("snippet") or "",
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
    if not accepted and domain:
        # OSINT do dono quando os padroes genericos falham (mesmo gate RCPT).
        async with _global_sem:
            owner_found = await asyncio.to_thread(
                owner_email.find_owner_email,
                domain,
                entity.get("legal_name") or "",
            )
        if owner_found:
            accepted = [owner_found]
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


async def _ingest_sources(now: datetime) -> dict:
    """Licencas (semanal) e OSM (semanal): fontes gratuitas, fora da Brave.

    Corre num task proprio para nunca atrasar o tick de enriquecimento.
    """
    if _source_lock.locked():
        return {"status": "busy"}
    async with _source_lock:
        day = now.strftime("%Y-%m-%d")
        out: dict[str, dict] = {}
        last = await db_service.get_system_kv("licenses_last_run")
        if not last or (now - _parse_day(last)).days >= SOURCE_INTERVAL_DAYS:
            try:
                out["licenses"] = await licensing_sources.ingest_nyc_licenses(
                    limit=LICENSES_PER_RUN
                )
                await db_service.set_system_kv("licenses_last_run", day)
                await db_service.checkpoint()
            except Exception as exc:  # noqa: BLE001
                logger.warning("[ENRICH-SCHED] licencas falharam: %s", exc)
                out["licenses"] = {"status": "error"}
        last = await db_service.get_system_kv("tdlr_last_run")
        if not last or (now - _parse_day(last)).days >= SOURCE_INTERVAL_DAYS:
            try:
                out["tdlr"] = await licensing_sources.ingest_tdlr(limit=12000)
                await db_service.set_system_kv("tdlr_last_run", day)
                await db_service.checkpoint()
            except Exception as exc:  # noqa: BLE001
                logger.warning("[ENRICH-SCHED] TDLR falhou: %s", exc)
                out["tdlr"] = {"status": "error"}
        last = await db_service.get_system_kv("il_roofing_last_run")
        if not last or (now - _parse_day(last)).days >= SOURCE_INTERVAL_DAYS:
            try:
                out["il_roofing"] = await licensing_sources.ingest_il_roofing(
                    limit=5000
                )
                await db_service.set_system_kv("il_roofing_last_run", day)
                await db_service.checkpoint()
            except Exception as exc:  # noqa: BLE001
                logger.warning("[ENRICH-SCHED] IL roofing falhou: %s", exc)
                out["il_roofing"] = {"status": "error"}
        last = await db_service.get_system_kv("chi_licenses_last_run")
        if not last or (now - _parse_day(last)).days >= SOURCE_INTERVAL_DAYS:
            try:
                out["chi_licenses"] = await licensing_sources.ingest_chicago_licenses(
                    limit=2000
                )
                await db_service.set_system_kv("chi_licenses_last_run", day)
                await db_service.checkpoint()
            except Exception as exc:  # noqa: BLE001
                logger.warning("[ENRICH-SCHED] Chicago licencas falharam: %s", exc)
                out["chi_licenses"] = {"status": "error"}
        last = await db_service.get_system_kv("osm_last_run")
        if not last or (now - _parse_day(last)).days >= SOURCE_INTERVAL_DAYS:
            try:
                out["osm"] = await osm_extract.ingest_all(limit_per_city=OSM_PER_CITY)
                await db_service.set_system_kv("osm_last_run", day)
                await db_service.checkpoint()
            except Exception as exc:  # noqa: BLE001
                logger.warning("[ENRICH-SCHED] OSM falhou: %s", exc)
                out["osm"] = {"status": "error"}
        return out or {"status": "skipped"}


def _parse_day(value: str) -> datetime:
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").replace(
            tzinfo=timezone.utc
        )
    except (TypeError, ValueError):
        return datetime.fromtimestamp(0, tz=timezone.utc)


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
            asyncio.create_task(_ingest_sources(datetime.now(timezone.utc)))
            _ticks[0] += 1
            if _ticks[0] % 30 == 0:
                await db_service.checkpoint()
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            logger.warning("[ENRICH-SCHED] tick falhou: %s", e)

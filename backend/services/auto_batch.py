"""Criação automática de lotes (auto-lote) para o motor não parar.

Travas: `send_enabled=0`, quiet hours, sem capacidade hoje, fila acima do
low-water, cooldown entre lotes e cidade com `send_enabled=0`. Nunca envia:
apenas cria o lote e chama `enqueue_batch` (o worker envia com os caps).
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Optional

from ..utils.logger import logger
from . import enrichment_scheduler, outbound_templates
from .db import db_service
from .outbound_engine import outbound_engine as engine

LOW_WATER = 3
DEFAULT_BATCH = 8
COOLDOWN_S = 600
KV_LAST_AT = "auto_batch_last_at"
KV_LAST = "auto_batch_last"


def choose_city(
    readiness: dict[str, dict], osint_by_city: Optional[dict[str, int]] = None
) -> Optional[tuple[str, int]]:
    """Cidade a processar: mais owner_osint prontos; empate -> mais prontos.

    Assim o braço escasso do KPI (owner_osint) chega aos 50 envios primeiro,
    sem deixar de enviar para o braço genérico (o 1:1 dentro do lote garante).
    """
    osint_by_city = osint_by_city or {}
    best: Optional[tuple[str, int]] = None
    best_score: Optional[tuple[int, int]] = None
    for city, data in readiness.items():
        ready = int(data.get("ready") or 0)
        if ready <= 0:
            continue
        score = (int(osint_by_city.get(city, 0)), ready)
        if best_score is None or score > best_score:
            best_score = score
            best = (city, ready)
    return best


def choose_niche(readiness: dict) -> str:
    by_niche = readiness.get("by_niche") or []
    if by_niche:
        return str(by_niche[0].get("niche_key") or outbound_templates.DEFAULT_NICHE)
    return outbound_templates.DEFAULT_NICHE


def _cooldown_ok() -> bool:
    svc = db_service._service
    last = svc.get_system_kv(KV_LAST_AT)
    if not last:
        return True
    try:
        return (time.time() - float(last)) >= COOLDOWN_S
    except (TypeError, ValueError):
        return True


def choose_balanced_niche(mix: list[dict]) -> Optional[str]:
    """Nicho com as DUAS origens (para o 1:1 arrancar logo no lote)."""
    balanced = [
        row for row in mix or []
        if int(row.get("osint") or 0) > 0 and int(row.get("generic") or 0) > 0
    ]
    if not balanced:
        return None
    best = max(balanced, key=lambda r: (int(r["osint"]), int(r["osint"]) + int(r["generic"])))
    return str(best.get("niche") or "")


def choose_city_niche(
    readiness: dict[str, dict], mixes: dict[str, list[dict]]
) -> Optional[tuple[str, str]]:
    """Par (cidade, nicho) com mais owner_osint e generic no mesmo lote."""
    best: Optional[tuple[tuple[int, int, int], str, str]] = None
    for city, rows in (mixes or {}).items():
        ready = int((readiness.get(city) or {}).get("ready") or 0)
        if ready <= 0:
            continue
        for row in rows or []:
            osint = int(row.get("osint") or 0)
            generic = int(row.get("generic") or 0)
            if osint <= 0 or generic <= 0:
                continue
            score = (osint, generic, ready)
            if best is None or score > best[0]:
                best = (score, city, str(row.get("niche") or ""))
    return (best[1], best[2]) if best else None


async def maybe_create_batch(now: Optional[datetime] = None) -> dict:
    now = now or datetime.now(timezone.utc)
    config = await db_service.get_outbound_config()
    if config.get("auto_batch_enabled") == "0":
        return {"status": "disabled"}
    if config.get("send_enabled") != "1":
        return {"status": "send_off"}
    if not _cooldown_ok():
        return {"status": "cooldown"}

    status = await engine.status()
    if status.get("quiet_hours_now"):
        return {"status": "quiet_hours"}
    if int(status.get("queued") or 0) >= LOW_WATER:
        return {"status": "queue_ok", "queued": status.get("queued")}
    remaining = int(status.get("mailbox_remaining_today") or 0)
    if remaining <= 0:
        return {"status": "no_capacity"}

    readiness: dict[str, dict] = {}
    mixes: dict[str, list[dict]] = {}
    for city in enrichment_scheduler.cities():
        cfg = await db_service.get_outbound_config(city)
        if cfg.get("send_enabled") != "1":
            continue
        readiness[city] = await db_service.outbound_readiness(city)
        try:
            mixes[city] = await db_service.ready_source_mix(city)
        except Exception:  # noqa: BLE001
            mixes[city] = []
    osint_by_city = {
        city: sum(int(row.get("osint") or 0) for row in mix)
        for city, mix in mixes.items()
    }
    pair = choose_city_niche(readiness, mixes)
    if pair:
        city, niche = pair
        ready = int(readiness[city].get("ready") or 0)
    else:
        pick = choose_city(readiness, osint_by_city)
        if not pick:
            return {"status": "no_inventory"}
        city, ready = pick
        niche = choose_niche(readiness[city])
    size = max(1, min(ready, remaining, DEFAULT_BATCH))

    svc = db_service._service
    name = f"auto-{now.strftime('%Y%m%d-%H%M')}-{city.lower()}-{niche}"
    try:
        batch = svc.create_outbound_batch(
            city=city,
            name=name,
            filters_json=json.dumps(
                {"city": city, "niche": niche, "batch_size": size}
            ),
            kind="email",
        )
        svc.mark_outbound_batch_previewed(int(batch["id"]), size, 0.0)
        batch = svc.start_outbound_batch(int(batch["id"]))
        result = await engine.enqueue_batch(batch)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[AUTO-BATCH] falhou (%s/%s): %s", city, niche, exc)
        return {"status": "error", "error": str(exc)[:120]}

    await db_service.set_system_kv(KV_LAST_AT, str(time.time()))
    await db_service.set_system_kv(
        KV_LAST, f"{now.isoformat()} {city}/{niche} queued={result.get('queued')}"
    )
    logger.info(
        "[AUTO-BATCH] %s/%s lote=%s size=%s queued=%s",
        city, niche, batch.get("id"), size, result.get("queued"),
    )
    return {
        "status": "created",
        "city": city,
        "niche": niche,
        "batch_id": batch.get("id"),
        "size": size,
        "queued": result.get("queued"),
        "blocked_reason": result.get("reason"),
    }

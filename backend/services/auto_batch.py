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


def choose_city(readiness: dict[str, dict]) -> Optional[tuple[str, int]]:
    """Cidade com mais prontos (ignora cidades sem inventário)."""
    best: Optional[tuple[str, int]] = None
    for city, data in readiness.items():
        ready = int(data.get("ready") or 0)
        if ready <= 0:
            continue
        if best is None or ready > best[1]:
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
    for city in enrichment_scheduler.cities():
        cfg = await db_service.get_outbound_config(city)
        if cfg.get("send_enabled") != "1":
            continue
        readiness[city] = await db_service.outbound_readiness(city)
    pick = choose_city(readiness)
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

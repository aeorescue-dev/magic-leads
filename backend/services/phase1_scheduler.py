"""Scheduler da Fase 1: prazos/multas a cada 6h e alvarás 1x/dia.

Não toca no scheduler reativo. A ingestão é síncrona (HTTP + SQLite), por isso
corre sempre num thread separado para não bloquear o event loop da API.

Regras aprovadas:
* fila visível: 7 dias (`PREVENTIVE_FEED_WINDOW_DAYS`);
* retenção: 30 dias para auditoria e purga aos 90 (`PREVENTIVE_RETENTION_DAYS`);
* operacional (chamados/prazos/multas): a cada 6h;
* alvarás/PLUTO: a cada 24h;
* nunca corre em produção por omissão (`PHASE1_SCHEDULER_ENABLED=False`).
"""
from __future__ import annotations

import asyncio
import logging
import time

from ..config import settings
from .opportunity_workflow import opportunity_workflow
from .phase1_enrichment import phase1_enrichment

logger = logging.getLogger("garimpador")


class Phase1Scheduler:
    """Loop idempotente com lock para impedir runs sobrepostos."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()

    async def run_operational(self) -> dict:
        return await self._run(include_permits=False)

    async def run_daily(self) -> dict:
        return await self._run(include_permits=True)

    async def _run(self, *, include_permits: bool) -> dict:
        if self._lock.locked():
            return {"status": "skipped", "reason": "already_running"}
        async with self._lock:
            limit = max(1, int(getattr(settings, "PHASE1_OPERATIONAL_LIMIT", 500) or 500))
            ecb = max(1, int(getattr(settings, "PHASE1_ECB_LIMIT", 1000) or 1000))
            permit_rows = (
                max(1, int(getattr(settings, "PHASE1_DAILY_PERMIT_ROWS", 1500) or 1500))
                if include_permits
                else 0
            )
            try:
                stats = await asyncio.to_thread(
                    phase1_enrichment.ingest,
                    hpd_complaints=limit,
                    hpd_deadlines=limit,
                    ecb=ecb,
                    chi_violations=limit,
                    permit_rows=permit_rows,
                )
                logger.info(
                    "[PHASE1] ingestão %s: %s",
                    "diária" if include_permits else "operacional",
                    stats,
                )
                return {"status": "ok", "stats": stats}
            except Exception as exc:  # nunca deixar o loop morrer
                logger.error("[PHASE1] falha na ingestão: %s", exc, exc_info=True)
                return {"status": "error", "error": str(exc)}

    async def run_retention(self) -> int:
        days = int(getattr(settings, "PREVENTIVE_RETENTION_DAYS", 90) or 90)
        try:
            deleted = await asyncio.to_thread(
                opportunity_workflow.prune_old, days
            )
            if deleted:
                logger.info("[PHASE1] retenção: %s linha(s) com mais de %s dias", deleted, days)
            return int(deleted or 0)
        except Exception as exc:
            logger.error("[PHASE1] falha na retenção: %s", exc, exc_info=True)
            return 0

    async def scheduler_loop(self) -> None:
        operational_hours = float(
            getattr(settings, "PHASE1_OPERATIONAL_INTERVAL_HOURS", 6) or 6
        )
        permits_hours = float(
            getattr(settings, "PHASE1_PERMITS_INTERVAL_HOURS", 24) or 24
        )
        logger.info(
            "[PHASE1] scheduler ativo (operacional %.1fh, alvarás %.1fh, fila %sd)",
            operational_hours,
            permits_hours,
            getattr(settings, "PREVENTIVE_FEED_WINDOW_DAYS", 7),
        )
        await self.run_retention()
        now = time.monotonic()
        last_operational = now
        last_permits = now
        if getattr(settings, "PHASE1_RUN_ON_START", True):
            # O run diário já inclui os sinais operacionais e os alvarás.
            await self.run_daily()
            last_operational = time.monotonic()
            last_permits = last_operational
        while True:
            await asyncio.sleep(60)
            current = time.monotonic()
            if current - last_permits >= permits_hours * 3600:
                await self.run_daily()
                last_permits = time.monotonic()
                last_operational = last_permits
                continue
            if current - last_operational >= operational_hours * 3600:
                await self.run_operational()
                last_operational = time.monotonic()

    async def run_once(
        self, *, include_permits: bool = True, retention: bool = False
    ) -> dict:
        """Gatilho manual (admin/testes), sem iniciar o loop."""
        if retention:
            await self.run_retention()
        return await self._run(include_permits=include_permits)


phase1_scheduler = Phase1Scheduler()

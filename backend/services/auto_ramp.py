"""Auto-Ramp e disjuntor das caixas de envio.

Regras aprovadas:
  * escada unica: 1,1,1,2,3,5,8,12,20,25,35,50,75;
  * abaixo de 25/dia sobe a cada 2-3 dias se a saude estiver limpa
    (warm-up da caixa/dominio, amostra pequena obrigatoria);
  * a partir de 25/dia exige **>=200 envios** na janela, bounce <1%,
    complaint <0.1% e zero erros de autenticacao nos ultimos 30 dias;
  * teto `auto_ramp_max` definido no Admin (default 75, maximo 100);
  * nunca desce sozinho; o disjuntor pausa a caixa, a retoma e' manual.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from ..utils.logger import logger
from .db import db_service, get_connection

AUTO_RAMP_STAGES: tuple[int, ...] = (1, 1, 1, 2, 3, 5, 8, 12, 20, 25, 35, 50, 75)
GATED_FROM = 25
MIN_SAMPLE_AFTER_GATE = 200
# Dias de permanencia em cada patamar antes do proximo degrau. Abaixo de 25 e'
# warm-up (2 dias por degrau); acima, a amostra/gates mandam e o intervalo
# apenas evita subir duas vezes no mesmo dia.
STEP_INTERVAL_DAYS: dict[int, int] = {
    1: 2, 2: 2, 3: 2, 5: 2, 8: 2, 12: 3, 20: 3, 25: 4, 35: 5, 50: 7,
}
DEFAULT_STEP_INTERVAL_DAYS = 7
MAX_RAMP = 100
BOUNCE_LIMIT = 0.01
COMPLAINT_LIMIT = 0.001
EVAL_KEY = "auto_ramp_last_eval"


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(value).strip(), fmt).replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            continue
    return None


def step_interval_days(current_cap: int) -> int:
    """Dias a permanecer no patamar antes de tentar o proximo degrau."""
    return int(STEP_INTERVAL_DAYS.get(int(current_cap), DEFAULT_STEP_INTERVAL_DAYS))


def next_stage_cap(current_cap: int, max_cap: int) -> Optional[int]:
    """Próximo degrau acima do cap atual, respeitando o teto."""
    for cap in AUTO_RAMP_STAGES:
        if cap > int(current_cap):
            return cap if cap <= int(max_cap) else None
    return None


def evaluate_mailbox(
    mailbox: dict, metrics: dict, now: Optional[datetime] = None
) -> dict:
    """Decisão pura (sem BD) para uma caixa. Devolve step ou hold + motivo."""
    now = now or datetime.now(timezone.utc)
    if not int(mailbox.get("auto_ramp_enabled") or 0):
        return {"action": "hold", "reason": "disabled"}
    if mailbox.get("paused_at") or not int(mailbox.get("enabled") or 0):
        return {"action": "hold", "reason": "paused"}

    current = max(1, int(mailbox.get("auto_ramp_cap") or 1))
    stage = int(mailbox.get("auto_ramp_stage") or 0)
    max_cap = min(MAX_RAMP, max(1, int(mailbox.get("auto_ramp_max") or 75)))

    last = _parse_dt(
        mailbox.get("auto_ramp_last_step_at")
        or mailbox.get("warmup_started_at")
        or mailbox.get("created_at")
    )
    if last and (now - last) < timedelta(days=step_interval_days(current)):
        return {"action": "hold", "reason": "interval"}

    sent = int(metrics.get("sent") or 0)
    if current >= GATED_FROM:
        if sent < MIN_SAMPLE_AFTER_GATE:
            return {"action": "hold", "reason": "sample"}
        if float(metrics.get("bounce_rate") or 0.0) >= BOUNCE_LIMIT:
            return {"action": "hold", "reason": "bounce"}
        if float(metrics.get("complaint_rate") or 0.0) >= COMPLAINT_LIMIT:
            return {"action": "hold", "reason": "complaint"}
        last_auth = _parse_dt(metrics.get("last_auth_error_at"))
        if last_auth and (now - last_auth) < timedelta(days=30):
            return {"action": "hold", "reason": "auth"}
    else:
        # Warm-up: amostra pequena, mas nunca subir sem envios reais.
        if sent < max(5, current * 3):
            return {"action": "hold", "reason": "sample"}

    nxt = next_stage_cap(current, max_cap)
    if nxt is None:
        return {"action": "hold", "reason": "max"}
    return {
        "action": "step",
        "from_cap": current,
        "to_cap": nxt,
        "stage": stage + 1,
        "reason": "healthy",
    }


def _eval_today(now: datetime) -> Optional[str]:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT value FROM system_kv WHERE key=?", (EVAL_KEY,)
        ).fetchone()
        return row["value"] if row else None
    finally:
        conn.close()


def _mark_eval(now: datetime) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO system_kv (key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (EVAL_KEY, now.strftime("%Y-%m-%d"), now.strftime("%Y-%m-%dT%H:%M:%SZ")),
        )
        conn.commit()
    finally:
        conn.close()


async def evaluate_auto_ramp(
    now: Optional[datetime] = None, force: bool = False
) -> dict:
    """Avalia todas as caixas com Auto-Ramp ligado (1x/dia, salvo force)."""
    now = now or datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    if not force and _eval_today(now) == today:
        return {"status": "skipped", "reason": "already_evaluated", "steps": 0}

    steps = 0
    holds = 0
    rows = await db_service.list_sending_mailboxes(enabled_only=False)
    for mailbox in rows:
        if not int(mailbox.get("auto_ramp_enabled") or 0):
            continue
        metrics = await db_service.mailbox_metrics(int(mailbox["id"]), 30)
        decision = evaluate_mailbox(mailbox, metrics, now)
        if decision["action"] == "step":
            await db_service.apply_auto_ramp_step(
                int(mailbox["id"]),
                int(decision["from_cap"]),
                int(decision["to_cap"]),
                int(decision["stage"]),
                decision["reason"],
                metrics,
            )
            steps += 1
            logger.info(
                "[AUTO-RAMP] caixa=%s %s -> %s/dia (stage=%s)",
                mailbox.get("email"),
                decision["from_cap"],
                decision["to_cap"],
                decision["stage"],
            )
        else:
            await db_service.set_auto_ramp_hold(int(mailbox["id"]), decision["reason"])
            holds += 1

    _mark_eval(now)
    return {
        "status": "ok",
        "steps": steps,
        "holds": holds,
        "metrics": {
            "mailboxes": sum(
                1 for m in rows if int(m.get("auto_ramp_enabled") or 0)
            )
        },
    }

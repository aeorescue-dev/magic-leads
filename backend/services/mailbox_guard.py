"""Disjuntor das caixas de envio (bounce, complaint e autenticação).

Regras aprovadas:
  * bounce > 2% (com >=20 envios na janela de 30 dias) -> pausa a caixa;
  * 2 bounces consecutivos -> pausa imediata (amostra pequena);
  * complaint > 0.1% -> pausa;
  * qualquer erro de autenticação -> pausa imediata;
  * retoma MANUAL no Admin; só a caixa pausa, as outras continuam.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from ..utils.logger import logger
from .db import db_service

BOUNCE_LIMIT = 0.02
COMPLAINT_LIMIT = 0.001
MIN_SAMPLE = 20
AUTH_MARKERS = (
    "invalid_grant",
    "invalid grant",
    "unauthorized",
    "insufficient",
    "401",
    "403",
)


def looks_like_auth_error(error: Optional[str], http_status: Optional[int] = None) -> bool:
    if http_status in (401, 403):
        return True
    text = (error or "").lower()
    return any(marker in text for marker in AUTH_MARKERS)


async def _pause(mailbox: dict, reason: str, detail: str) -> None:
    """Pausa + alerta crítico; idempotente se já estiver pausada pelo mesmo motivo."""
    if mailbox.get("paused_reason") == reason and mailbox.get("paused_at"):
        return
    ok = await db_service.pause_mailbox(int(mailbox["id"]), reason)
    if not ok:
        return
    await db_service.record_system_alert(
        level="critical",
        code="MAILBOX_PAUSED",
        message=f"Caixa {mailbox.get('email')} pausada ({reason}): {detail}",
        context={
            "mailbox_id": int(mailbox["id"]),
            "email": mailbox.get("email"),
            "reason": reason,
        },
    )
    logger.warning(
        "[MAILBOX-GUARD] caixa=%s pausada (%s): %s",
        mailbox.get("email"),
        reason,
        detail,
    )


async def check_mailboxes(now: Optional[datetime] = None) -> dict:
    """Avalia a saúde de todas as caixas ligadas e pausa as que violarem regras."""
    now = now or datetime.now(timezone.utc)
    paused = 0
    rows = await db_service.list_sending_mailboxes(enabled_only=True)
    for mailbox in rows:
        mid = int(mailbox["id"])
        metrics = await db_service.mailbox_metrics(mid, 30)
        sent = int(metrics.get("sent") or 0)
        if sent >= MIN_SAMPLE:
            if float(metrics.get("bounce_rate") or 0.0) > BOUNCE_LIMIT:
                await _pause(
                    mailbox,
                    "bounce_rate",
                    f"bounce {metrics['bounces']}/{sent} "
                    f"({metrics['bounce_rate'] * 100:.1f}%)",
                )
                paused += 1
                continue
            if float(metrics.get("complaint_rate") or 0.0) > COMPLAINT_LIMIT:
                await _pause(
                    mailbox,
                    "complaint_rate",
                    f"complaint {metrics['complaints']}/{sent} "
                    f"({metrics['complaint_rate'] * 100:.2f}%)",
                )
                paused += 1
                continue
        events = await db_service.last_bounce_events(mid, 2)
        if len(events) == 2 and all(e.get("kind") == "bounce" for e in events):
            await _pause(
                mailbox,
                "consecutive_bounces",
                f"2 bounces consecutivos ({events[0].get('email')})",
            )
            paused += 1
    return {"paused": paused, "checked": len(rows)}


async def handle_auth_error(mailbox: dict, error: Optional[str]) -> None:
    """Pausa imediata por falha de autenticação (sem retry)."""
    if not mailbox:
        return
    await db_service.mark_mailbox_auth_error(int(mailbox["id"]))
    await _pause(mailbox, "auth_failure", error or "erro de autenticação")

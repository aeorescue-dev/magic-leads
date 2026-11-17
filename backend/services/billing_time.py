"""Relógio diário do modelo de assinatura semanal.

A cota de telefones e o limite de cartas/visitas resetam à meia-noite em
`America/New_York` (decisão de produto). As datas gravadas em
`user_daily_usage.date` são a data local de Nova Iorque; `reset_at` é UTC.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from ..config import settings

DEFAULT_TZ = "America/New_York"


def billing_tz() -> ZoneInfo:
    name = str(getattr(settings, "BILLING_TIMEZONE", DEFAULT_TZ) or DEFAULT_TZ)
    return ZoneInfo(name)


def local_now(now: datetime | None = None) -> datetime:
    base = now or datetime.now(timezone.utc)
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    return base.astimezone(billing_tz())


def local_date(now: datetime | None = None) -> str:
    """Data operacional (YYYY-MM-DD) no fuso de billing."""
    return local_now(now).date().isoformat()


def next_reset_utc(now: datetime | None = None) -> str:
    """Próxima meia-noite local, convertida para UTC ISO-8601."""
    local = local_now(now)
    next_local_day = local.date() + timedelta(days=1)
    next_local = datetime.combine(next_local_day, time.min, tzinfo=local.tzinfo)
    return next_local.astimezone(timezone.utc).isoformat()


def local_day_bounds_utc(now: datetime | None = None) -> tuple[str, str]:
    """Início/fim do dia operacional em UTC (ISO-8601)."""
    local = local_now(now)
    start_local = datetime.combine(local.date(), time.min, tzinfo=local.tzinfo)
    end_local = start_local + timedelta(days=1)
    return (
        start_local.astimezone(timezone.utc).isoformat(),
        end_local.astimezone(timezone.utc).isoformat(),
    )

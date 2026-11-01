"""Dia operacional em America/New_York (o cap e o painel seguem o horario local).

O resto do sistema guarda timestamps em UTC; este modulo converte o *dia*
(NY) para o instante UTC correspondente, para as comparacoes de "enviados
hoje" baterem certo mesmo com DST.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

try:
    from zoneinfo import ZoneInfo

    NY_TZ = ZoneInfo("America/New_York")
except Exception:  # noqa: BLE001 — imagem sem tzdata: cai para UTC
    NY_TZ = timezone.utc


def _now(now: Optional[datetime] = None) -> datetime:
    return now or datetime.now(timezone.utc)


def day_key(now: Optional[datetime] = None) -> str:
    """Data local (NY) no formato YYYY-MM-DD."""
    return _now(now).astimezone(NY_TZ).strftime("%Y-%m-%d")


def day_start_utc(day: str) -> str:
    """00:00 NY de `day` no formato UTC usado em `sent_at`."""
    try:
        local = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=NY_TZ)
    except (TypeError, ValueError):
        return f"{day} 00:00:00"
    return local.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def next_day_start_utc(now: Optional[datetime] = None) -> str:
    """Proxima meia-noite NY, em UTC (para o retry do cap)."""
    local = _now(now).astimezone(NY_TZ)
    nxt = (local + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return nxt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

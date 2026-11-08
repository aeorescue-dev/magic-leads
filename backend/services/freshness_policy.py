"""Politica de frescura por cidade.

Boston publica 311 em dias uteis. Medir a idade em horas de calendario faz a
cidade oscilar para `fail` todos os fins de semana, mesmo com a pipeline e o
portal saudaveis. Para Boston, a idade efetiva desconta as horas de sabado e
domingo (America/New_York), mantendo a sensibilidade durante a semana.

Nao altera a idade bruta: `raw_age_hours` continua disponivel para diagnostico.
"""
from __future__ import annotations

import os
from datetime import datetime, time, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

EASTERN = ZoneInfo("America/New_York")
_DEFAULT_WEEKEND_CITIES = "BOSTON"


def _weekend_cities() -> set[str]:
    raw = os.getenv("FRESHNESS_WEEKEND_AWARE_CITIES", _DEFAULT_WEEKEND_CITIES)
    return {
        item.strip().upper()
        for item in str(raw or "").split(",")
        if item.strip()
    }


def parse_dt(value) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            try:
                parsed = datetime.strptime(text[:19], "%Y-%m-%d %H:%M:%S")
            except ValueError:
                return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def raw_age_hours(city: str, last_at, now) -> Optional[float]:
    last = parse_dt(last_at)
    current = parse_dt(now) or datetime.now(timezone.utc)
    if last is None:
        return None
    return round(max(0.0, (current - last).total_seconds() / 3600), 1)


def weekend_hours_between(start, end) -> float:
    """Horas de sabado/domingo (America/New_York) no intervalo [start, end]."""
    first = parse_dt(start)
    last = parse_dt(end)
    if first is None or last is None or last <= first:
        return 0.0
    start_local = first.astimezone(EASTERN)
    end_local = last.astimezone(EASTERN)
    total = 0.0
    day = start_local.date()
    while day <= end_local.date():
        if day.weekday() >= 5:  # sabado=5, domingo=6
            day_start = datetime.combine(day, time.min, tzinfo=EASTERN)
            day_end = day_start + timedelta(days=1)
            overlap_start = max(start_local, day_start)
            overlap_end = min(end_local, day_end)
            if overlap_end > overlap_start:
                total += (overlap_end - overlap_start).total_seconds() / 3600
        day += timedelta(days=1)
    return total


def is_weekend_aware(city: str) -> bool:
    return str(city or "").strip().upper() in _weekend_cities()


def effective_age_hours(city: str, last_at, now) -> Optional[float]:
    """Idade operacional: para Boston, desconta sabado/domingo."""
    raw = raw_age_hours(city, last_at, now)
    if raw is None or not is_weekend_aware(city):
        return raw
    weekend = weekend_hours_between(last_at, now)
    return round(max(0.0, raw - weekend), 1)

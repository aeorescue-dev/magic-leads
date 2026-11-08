"""Regras puras de cadência e frescura do scraper.

Sem I/O: recebem datas já lidas da BD e devolvem decisões testáveis.

Motivo (auditoria 01/11/2026): o scheduler interno dormia 6h *depois* do boot,
portanto cada deploy reiniciava o relógio e a ingestão podia ficar parada
indefinidamente. Além disso, um run com `inserted=0` ficava `success` e verde,
sem alerta, e as cidades nunca eram avaliadas pela data real do último facto
(`MAX(date_reported)`), só pelo número de linhas brutas devolvidas.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from .freshness_policy import effective_age_hours, raw_age_hours

# Códigos gravados em `system_alerts` (o painel/Control Tower filtra por eles).
CODE_CITY_STALE = "SCRAPER_CITY_STALE"
CODE_ZERO_INSERTS = "SCRAPER_ZERO_INSERTS"
CODE_OVERDUE = "SCRAPER_OVERDUE"


def parse_dt(value) -> Optional[datetime]:
    """Converte timestamps da BD (ISO ou 'YYYY-MM-DD HH:MM:SS') em UTC aware."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if not text:
            return None
        text = text.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            try:
                dt = datetime.strptime(text[:19], "%Y-%m-%d %H:%M:%S")
            except ValueError:
                return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def seconds_until_next_scrape(
    now: datetime,
    last_success_started_at,
    last_run_started_at,
    interval_hours: float,
    *,
    retry_minutes: int = 30,
    max_wake_seconds: float = 900.0,
    last_run_status: Optional[str] = None,
    last_run_error: Optional[str] = None,
) -> float:
    """Segundos até ao próximo run, com base no relógio (não no tempo de boot).

    - Cadência normal: `last_success + interval`.
    - Um run falhado não deve esperar 6h: permite retry após `retry_minutes`.
    - Um run **interrompido por deploy** (sem success posterior) dispara já,
      para o workflow não ficar à espera de um processo que já morreu.
    - Devolve 0 quando já está vencido (arranque após deploy recupera atraso).
    - Acorda no máximo a cada `max_wake_seconds` para reavaliar o relógio.
    """
    last_success = parse_dt(last_success_started_at)
    last_run = parse_dt(last_run_started_at)
    now = parse_dt(now) or datetime.now(timezone.utc)
    interval = max(0.25, float(interval_hours or 6))

    if (
        str(last_run_status or "").lower() in ("error", "interrupted")
        and last_run is not None
        and (last_success is None or last_run > last_success)
        and any(
            marker in str(last_run_error or "").lower()
            for marker in ("interrompido", "reiniciado")
        )
    ):
        return 0.0

    due: Optional[datetime] = None
    if last_success is not None:
        due = last_success + timedelta(hours=interval)
    if last_run is not None:
        retry_at = last_run + timedelta(minutes=max(1, int(retry_minutes)))
        due = retry_at if due is None else max(due, retry_at)
    if due is None:
        return 0.0

    remaining = (due - now).total_seconds()
    if remaining <= 0:
        return 0.0
    return min(remaining, max(60.0, float(max_wake_seconds)))


def zero_insert_streak(recent_runs: Iterable[dict]) -> int:
    """Runs concluídos consecutivos (mais recente primeiro) sem inserir nada."""
    streak = 0
    for run in recent_runs or []:
        status = str((run or {}).get("status") or "").lower()
        if status not in ("success", "partial"):
            break
        try:
            inserted = int((run or {}).get("inserted") or 0)
        except (TypeError, ValueError):
            inserted = 0
        if inserted > 0:
            break
        streak += 1
    return streak


def freshness_problems(
    now: datetime,
    city_last_dates: dict,
    recent_runs: Iterable[dict],
    *,
    interval_hours: float,
    stale_hours: float = 24.0,
    overdue_grace_hours: float = 2.0,
    stale_cities: Optional[Iterable[str]] = None,
) -> list[dict]:
    """Lista de problemas accionáveis, sem duplicar alertas nem tocar na BD."""
    now = parse_dt(now) or datetime.now(timezone.utc)
    problems: list[dict] = []
    last_dates = city_last_dates or {}
    for city in stale_cities if stale_cities is not None else last_dates.keys():
        key = str(city).strip().upper()
        last = parse_dt(last_dates.get(key))
        age_h = effective_age_hours(key, last, now)
        if age_h is not None and age_h <= stale_hours:
            continue
        raw_age = raw_age_hours(key, last, now)
        problems.append(
            {
                "code": CODE_CITY_STALE,
                "level": "warning",
                "city": key,
                "message": (
                    f"{key} sem dados novos há {age_h}h"
                    if age_h is not None
                    else f"{key} sem qualquer data de facto registada"
                ),
                "context": {
                    "city": key,
                    "last_date_reported": last.isoformat() if last else None,
                    "age_hours": age_h,
                    "raw_age_hours": raw_age,
                    "threshold_hours": stale_hours,
                },
            }
        )

    streak = zero_insert_streak(recent_runs)
    if streak >= 2:
        problems.append(
            {
                "code": CODE_ZERO_INSERTS,
                "level": "warning",
                "city": None,
                "message": f"{streak} runs consecutivos sem inserir leads",
                "context": {"streak": streak, "recent_runs": list(recent_runs or [])[:5]},
            }
        )

    runs = list(recent_runs or [])
    last_run = parse_dt(
        (runs[0] or {}).get("started_at") if runs else None
    )
    limit = timedelta(hours=max(0.5, float(interval_hours)) + overdue_grace_hours)
    if last_run is None:
        problems.append(
            {
                "code": CODE_OVERDUE,
                "level": "warning",
                "city": None,
                "message": "Nenhum run do scraper registado",
                "context": {"threshold_hours": limit.total_seconds() / 3600},
            }
        )
    elif now - last_run > limit:
        age_h = round((now - last_run).total_seconds() / 3600, 1)
        problems.append(
            {
                "code": CODE_OVERDUE,
                "level": "warning",
                "city": None,
                "message": f"Ingestão parada há {age_h}h (limite {limit.total_seconds() / 3600:.1f}h)",
                "context": {
                    "last_run_started_at": last_run.isoformat(),
                    "age_hours": age_h,
                    "threshold_hours": limit.total_seconds() / 3600,
                },
            }
        )
    return problems


def should_force_collection(
    now: datetime,
    last_run_started_at,
    problems: Iterable[dict],
    *,
    min_hours_between_forces: float = 2.0,
) -> bool:
    """True quando há problema real e não há um run recente (evita tempestade)."""
    if not list(problems or []):
        return False
    now = parse_dt(now) or datetime.now(timezone.utc)
    last_run = parse_dt(last_run_started_at)
    if last_run is None:
        return True
    return now - last_run >= timedelta(hours=max(0.25, float(min_hours_between_forces)))

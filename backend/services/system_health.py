"""System Health — visão operacional única do produto (Fase 27).

Read-only. Constrói um snapshot com 7 camadas + score 0–100 por camada e um
score global ponderado. Todas as leituras são à BD persistida (nunca a
contadores em memória, que reiniciam no deploy).

Regras de score (documentadas e testadas em `tests/test_system_health.py`):
  * começa em 100 e perde pontos por cada sinal degradado;
  * `status`: >=90 ok, >=60 warn, <60 fail;
  * o status global é o PIOR dos sete; o score global é a média ponderada.

Pesos: ingestão 20, enriquecimento 15, outreach 20, push 10, cotas 10,
infra 15, alertas 10.
"""
from __future__ import annotations

import json
import os
import shutil
import time
from datetime import datetime, timezone
from typing import Any, Optional

import anyio

from ..config import settings
from ..utils.logger import logger
from ..utils.time import utcnow_aware
from . import control_tower
from .alert_dedup import dedupe_alerts
from .db import SERVED_CITIES, db_service, get_connection
from .scrape_guard import parse_dt, zero_insert_streak

LAYER_ORDER = (
    "ingest",
    "enrichment",
    "outreach",
    "push",
    "quotas",
    "infra",
    "alerts",
)
LAYER_LABELS = {
    "ingest": "Ingestão",
    "enrichment": "Enriquecimento",
    "outreach": "Outreach",
    "push": "Web Push",
    "quotas": "Cotas & Custos",
    "infra": "Infra",
    "alerts": "Alertas",
}
LAYER_WEIGHTS = {
    "ingest": 20,
    "enrichment": 15,
    "outreach": 20,
    "push": 10,
    "quotas": 10,
    "infra": 15,
    "alerts": 10,
}
STATUS_LABELS = {
    "ok": "Saudável",
    "warn": "Atenção",
    "fail": "Crítico",
    "unknown": "Sem dados",
}
# Códigos de auditoria de segurança/administração: ficam visíveis no feed, mas
# não são falhas operacionais e não podem baixar o score da torre.
NON_OPERATIONAL_ALERT_PREFIXES = ("ADMIN_ACCESS_",)
# Mesma amostra minima do disjuntor (`mailbox_guard.MIN_SAMPLE`): uma taxa de
# bounce so e' acionavel com >=20 envios na caixa, nao com 1 bounce em 22.
MIN_BOUNCE_SAMPLE = 20
CACHE_TTL_SECONDS = 30.0
_CACHE: dict[str, Any] = {"at": 0.0, "window": 0, "data": None}


# ------------------------------------------------------------------ helpers
def score_to_status(score: int) -> str:
    if score >= 90:
        return "ok"
    if score >= 60:
        return "warn"
    return "fail"


def _clamp(value: float) -> int:
    return max(0, min(100, int(round(value))))


def _age_hours(value, now: datetime) -> Optional[float]:
    dt = parse_dt(value)
    if dt is None:
        return None
    return round((now - dt).total_seconds() / 3600, 1)


def _age_minutes(value, now: datetime) -> Optional[float]:
    dt = parse_dt(value)
    if dt is None:
        return None
    return round((now - dt).total_seconds() / 60, 1)


def _ny_hour(now: datetime) -> int:
    try:
        from zoneinfo import ZoneInfo

        return now.astimezone(ZoneInfo("America/New_York")).hour
    except Exception:  # noqa: BLE001
        return now.hour


def _layer(
    key: str,
    penalties: list[float],
    reasons: list[str],
    headline: str,
    metrics: list[dict],
    detail: Optional[dict] = None,
) -> dict:
    score = _clamp(100 - sum(penalties))
    status = score_to_status(score)
    return {
        "key": key,
        "label": LAYER_LABELS[key],
        "status": status,
        "status_label": STATUS_LABELS[status],
        "score": score,
        "headline": headline,
        "reasons": [r for r in reasons if r][:4],
        "metrics": metrics,
        "detail": detail or {},
    }


def _metric(
    key: str,
    label: str,
    value,
    unit: str = "",
    status: str = "ok",
    threshold: str = "",
) -> dict:
    return {
        "key": key,
        "label": label,
        "value": value,
        "unit": unit,
        "status": status,
        "threshold": threshold,
    }


# ------------------------------------------------------------- score layers
def score_ingest(
    cities: list[dict],
    recent_runs: list[dict],
    now: datetime,
    interval_hours: float = 6.0,
    stale_hours: float = 24.0,
    inserted_24h: Optional[int] = None,
) -> dict:
    penalties: list[float] = []
    reasons: list[str] = []
    fresh = 0
    oldest = 0.0
    for row in cities:
        city = str(row.get("city") or "").upper()
        age = _age_hours(row.get("last_fact"), now)
        row["age_h"] = age
        total = int(row.get("total") or 0)
        row["owner_pct"] = (
            round(100 * int(row.get("owners") or 0) / total, 1) if total else 0.0
        )
        if age is None:
            penalties.append(50)
            reasons.append(f"{city}: sem data de facto")
            continue
        oldest = max(oldest, age)
        if age > stale_hours * 1.5:
            penalties.append(50)
            reasons.append(f"{city}: {age:.1f}h sem factos")
        elif age > stale_hours:
            penalties.append(25)
            reasons.append(f"{city}: {age:.1f}h sem factos")
        else:
            fresh += 1

    streak = zero_insert_streak(recent_runs)
    if streak >= 2:
        penalties.append(30)
        reasons.append(f"{streak} runs seguidos sem inserir")

    last_run_age = _age_hours((recent_runs[0] or {}).get("started_at"), now) if recent_runs else None
    if not recent_runs:
        penalties.append(50)
        reasons.append("Sem runs de ingestão registados")
    else:
        if last_run_age is not None and last_run_age > interval_hours * 1.75:
            penalties.append(30)
            reasons.append(f"Último run há {last_run_age:.1f}h")
        if str((recent_runs[0] or {}).get("status") or "").lower() == "error":
            penalties.append(20)
            reasons.append("Último run terminou em erro")

    inserted_24h_runs = 0
    for run in recent_runs:
        age = _age_hours(run.get("started_at"), now)
        if age is not None and age <= 24:
            inserted_24h_runs += int(run.get("inserted") or 0)
    if inserted_24h is None:
        inserted_24h = inserted_24h_runs
    headline = (
        f"{fresh}/{len(cities)} cidades frescas · último run "
        + (f"há {last_run_age:.1f}h" if last_run_age is not None else "desconhecido")
    )
    metrics = [
        _metric(
            "cities_fresh",
            "Cidades frescas",
            fresh,
            f"/{len(cities)}",
            "ok" if fresh == len(cities) else ("warn" if fresh else "fail"),
            f"{stale_hours:.0f}h",
        ),
        _metric(
            "oldest_city_h",
            "Cidade mais antiga",
            oldest,
            "h",
            "ok" if oldest <= stale_hours else ("warn" if oldest <= stale_hours * 1.5 else "fail"),
            f"{stale_hours:.0f}h",
        ),
        _metric("inserted_24h", "Inseridos 24h", inserted_24h, "", "ok"),
        _metric(
            "zero_streak",
            "Runs sem inserir",
            streak,
            "",
            "ok" if streak < 2 else "fail",
            ">=2",
        ),
    ]
    return _layer(
        "ingest",
        penalties,
        reasons,
        headline,
        metrics,
        {"cities": cities, "runs": recent_runs[:5]},
    )


def score_enrichment(
    states: list[dict],
    entity_counts: dict,
    jobs: dict,
    owner_states: list[dict],
    brave: dict,
    now: datetime,
) -> dict:
    penalties: list[float] = []
    reasons: list[str] = []
    enabled = [s for s in states if int(s.get("enabled") or 0)]
    totals = {"new": 0, "ready": 0, "quarantined": 0, "other": 0}
    for city_rows in entity_counts.values():
        for status, count in (city_rows or {}).items():
            key = status if status in totals else "other"
            totals[key] += int(count or 0)

    if brave.get("configured") and brave.get("blocked"):
        penalties.append(25)
        reasons.append("Brave sem orçamento (descoberta parada)")

    if enabled and all(int(s.get("jobs_today") or 0) == 0 for s in enabled) and _ny_hour(now) >= 10:
        penalties.append(15)
        reasons.append("Scheduler sem jobs hoje depois das 10h NY")

    if totals["ready"] == 0 and (totals["new"] + totals["quarantined"]) > 0:
        penalties.append(25)
        reasons.append("Zero entidades prontas para outreach")

    oldest_job = jobs.get("oldest_age_h")
    if oldest_job is not None and oldest_job > 72:
        penalties.append(30)
        reasons.append(f"Fila de enriquecimento há {oldest_job:.0f}h")
    elif oldest_job is not None and oldest_job > 24:
        penalties.append(15)
        reasons.append(f"Fila de enriquecimento há {oldest_job:.0f}h")

    backfill_ages = [
        _age_hours(s.get("last_run_at"), now) for s in owner_states
    ]
    backfill_ages = [a for a in backfill_ages if a is not None]
    backfill_age = min(backfill_ages) if backfill_ages else None
    if owner_states and (backfill_age is None or backfill_age > 6):
        penalties.append(10)
        reasons.append("Backfill de owners sem run recente")

    domain_used = sum(int(s.get("domain_jobs_today") or 0) for s in enabled)
    domain_limit = int(brave.get("domain_limit") or 0) * max(1, len(enabled))
    headline = (
        f"{totals['ready']} prontos · {totals['new']} por enriquecer"
        + (f" · domínio {domain_used}/{domain_limit}" if domain_limit else "")
    )
    metrics = [
        _metric("ready", "Prontos", totals["ready"], "", "ok" if totals["ready"] else "warn"),
        _metric("new", "Por enriquecer", totals["new"], "", "ok"),
        _metric(
            "quarantined",
            "Quarentena",
            totals["quarantined"],
            "",
            "ok",
        ),
        _metric(
            "domain_quota",
            "Domínio hoje",
            domain_used,
            f"/{domain_limit}" if domain_limit else "",
            "ok" if not brave.get("blocked") else "warn",
            "orçamento Brave",
        ),
        _metric(
            "pending_jobs",
            "Fila e-mail",
            int(jobs.get("pending") or 0),
            "",
            "ok" if (oldest_job or 0) <= 24 else "warn",
            "24h",
        ),
    ]
    return _layer(
        "enrichment",
        penalties,
        reasons,
        headline,
        metrics,
        {
            "by_city": entity_counts,
            "states": states,
            "jobs": jobs,
            "owner_backfill": owner_states,
        },
    )


def score_outreach(out: dict, metrics: dict, now: datetime) -> dict:
    penalties: list[float] = []
    reasons: list[str] = []
    mailboxes = out.get("mailboxes") or []
    paused = [m for m in mailboxes if m.get("paused_at") or m.get("paused_reason")]
    if paused:
        penalties.append(min(60, 30 * len(paused)))
        reasons.append(f"{len(paused)} caixa(s) pausada(s)")

    if not out.get("send_enabled") and int(out.get("queued") or 0) > 0:
        penalties.append(30)
        reasons.append("Motor desligado com fila")

    totals = (metrics or {}).get("totals") or {}
    sent = int(totals.get("sent") or 0)
    bounce_rate = float(totals.get("bounce_rate") or 0.0)
    complaints = int(totals.get("complaints") or 0)
    complaint_rate = (complaints / sent) if sent else 0.0

    # O disjuntor só avalia taxa com >=20 envios POR CAIXA. O painel usa a
    # mesma amostra: com 11 envios numa caixa, 1 bounce (4,5% agregado) não é
    # um sinal estatístico e não deve pintar Outreach de vermelho.
    mailbox_rows = (metrics or {}).get("mailboxes") or []
    sampled = [
        m for m in mailbox_rows if int(m.get("sent") or 0) >= MIN_BOUNCE_SAMPLE
    ]
    max_sample_sent = max(
        (int(m.get("sent") or 0) for m in mailbox_rows), default=0
    )
    max_bounce = max(
        (float(m.get("bounce_rate") or 0.0) for m in sampled), default=None
    )
    max_complaint = None
    for m in sampled:
        row_sent = int(m.get("sent") or 0)
        if row_sent:
            rate = int(m.get("complaints") or 0) / row_sent
            max_complaint = rate if max_complaint is None else max(max_complaint, rate)

    if max_bounce is not None and max_bounce > 0.02:
        penalties.append(40)
        reasons.append(f"Bounce {max_bounce * 100:.1f}% (amostra ≥20/caixa)")
    elif max_bounce is not None and max_bounce > 0.01:
        penalties.append(20)
        reasons.append(f"Bounce {max_bounce * 100:.1f}% (amostra ≥20/caixa)")
    if max_complaint is not None and max_complaint > 0.001:
        penalties.append(50)
        reasons.append(f"Complaint {max_complaint * 100:.2f}% (amostra ≥20/caixa)")

    bounce_status = "ok"
    bounce_threshold = "2%"
    if max_bounce is not None and max_bounce > 0.02:
        bounce_status = "fail"
    elif bounce_rate > 0.02:
        bounce_status = "warn"
        bounce_threshold = f"amostra {max_sample_sent}/{MIN_BOUNCE_SAMPLE} por caixa"
    if max_complaint is not None and max_complaint > 0.001:
        complaint_status = "fail"
    elif complaint_rate > 0.001:
        complaint_status = "warn"
    else:
        complaint_status = "ok"
    sampled_note = (
        f"amostra {max_sample_sent}/{MIN_BOUNCE_SAMPLE} por caixa"
        if max_sample_sent < MIN_BOUNCE_SAMPLE
        else "amostra ≥20/caixa"
    )

    blocker = out.get("queue_blocker") or {}
    blocker_reason = str(blocker.get("reason") or "")
    queue_age = out.get("queue_oldest_age_hours")
    if (
        int(out.get("queued") or 0) > 0
        and queue_age is not None
        and queue_age > 3
        and blocker_reason not in ("mailbox_cap", "quiet_hours")
    ):
        penalties.append(20)
        reasons.append(f"Fila com {queue_age:.1f}h sem motivo esperado")

    headline = (
        f"{int(out.get('sent_today') or 0)}/{int(out.get('mailbox_cap_total') or 0)} envios hoje"
        + (f" · fila {int(out.get('queued') or 0)}" if int(out.get("queued") or 0) else "")
    )
    metrics_rows = [
        _metric("sent_today", "Enviados hoje", int(out.get("sent_today") or 0), "", "ok"),
        _metric(
            "queued",
            "Em fila",
            int(out.get("queued") or 0),
            "",
            "warn" if (queue_age or 0) > 3 and blocker_reason not in ("mailbox_cap", "quiet_hours") else "ok",
        ),
        _metric(
            "bounce_rate",
            "Bounce 30d",
            round(bounce_rate * 100, 2),
            "%",
            bounce_status,
            bounce_threshold,
        ),
        _metric(
            "complaint_rate",
            "Complaint 30d",
            round(complaint_rate * 100, 2),
            "%",
            complaint_status,
            "0,1%",
        ),
    ]
    return _layer(
        "outreach",
        penalties,
        reasons,
        headline,
        metrics_rows,
        {
            "queue_blocker": out.get("queue_blocker"),
            "quiet_hours_now": out.get("quiet_hours_now"),
            "mailboxes": mailboxes,
            "totals": totals,
            "bounce_gate": {
                "sample_max": max_sample_sent,
                "min_sample": MIN_BOUNCE_SAMPLE,
                "note": sampled_note,
            },
        },
    )


def score_push(push: dict) -> dict:
    penalties: list[float] = []
    reasons: list[str] = []
    deliveries = int(push.get("deliveries") or 0)
    not_configured = int(push.get("not_configured") or 0)
    expired = int(push.get("expired") or 0)
    dead = int(push.get("rejected_dead") or 0)
    active_subs = int(push.get("active_subs") or 0)
    notifications = int(push.get("notifications_24h") or 0)

    if not_configured:
        penalties.append(60)
        reasons.append(f"{not_configured} entregas sem VAPID")
    if deliveries == 0 and active_subs > 0 and notifications > 0:
        penalties.append(25)
        reasons.append("Sem entregas em 24h com subscrições ativas")
    if deliveries >= 10 and (expired + dead) / deliveries > 0.2:
        penalties.append(30)
        reasons.append(f"{(expired + dead) * 100 // deliveries}% de subscrições mortas")
    if active_subs == 0:
        penalties.append(15)
        reasons.append("Sem subscrições ativas")

    dead_pct = round((expired + dead) * 100 / deliveries, 1) if deliveries else 0.0
    headline = f"{deliveries} entregas 24h · {active_subs} dispositivos ativos"
    if deliveries == 0 and active_subs > 0 and notifications == 0:
        headline += " · sem alertas elegíveis"
    metrics = [
        _metric("deliveries", "Entregas 24h", deliveries, "", "ok"),
        _metric(
            "dead_pct",
            "Subscrições mortas",
            dead_pct,
            "%",
            "ok" if dead_pct <= 20 else "warn",
            "20%",
        ),
        _metric("active_subs", "Dispositivos ativos", active_subs, "", "ok" if active_subs else "warn"),
        _metric("clicks", "Cliques 24h", int(push.get("clicks") or 0), "", "ok"),
    ]
    return _layer(
        "push",
        penalties,
        reasons,
        headline,
        metrics,
        push,
    )


def score_quotas(brave: dict, searchbug: dict) -> dict:
    penalties: list[float] = []
    reasons: list[str] = []
    used = int(brave.get("used") or 0)
    limit = int(brave.get("limit") or 0)
    if brave.get("configured"):
        if brave.get("blocked"):
            penalties.append(40)
            reasons.append("Brave bloqueado até amanhã")
        elif limit and used / limit >= 0.9:
            penalties.append(20)
            reasons.append(f"Brave a {used * 100 // limit}% do orçamento")

    calls_15m = int(searchbug.get("calls_15m") or 0)
    transport_15m = int(searchbug.get("transport_15m") or 0)
    if calls_15m >= 5 and transport_15m / calls_15m > 0.5:
        penalties.append(40)
        reasons.append(f"{transport_15m}/{calls_15m} erros Searchbug em 15min")

    cost_1h = float(searchbug.get("cost_1h") or 0)
    cost_24h = float(searchbug.get("cost_24h") or 0)
    avg_hourly = cost_24h / 24.0 if cost_24h else 0.0
    if cost_1h > max(1.0, avg_hourly * 3):
        penalties.append(15)
        reasons.append(f"Searchbug ${cost_1h:.2f}/h acima da média")

    billed = int(searchbug.get("billed") or 0)
    ghost = int(searchbug.get("ghost") or 0)
    if billed >= 10 and ghost / billed > 0.3:
        penalties.append(15)
        reasons.append(f"{ghost}/{billed} chamadas pagas sem telefone")

    headline = (
        f"Brave {used}/{limit or '—'} · Searchbug ${cost_24h:.2f}/24h"
    )
    metrics = [
        _metric(
            "brave",
            "Brave",
            used,
            f"/{limit}" if limit else "",
            "fail" if brave.get("blocked") else ("warn" if limit and used / limit >= 0.9 else "ok"),
            "orçamento diário",
        ),
        _metric("searchbug_cost", "Searchbug 24h", round(cost_24h, 2), "$", "ok"),
        _metric(
            "searchbug_calls",
            "Chamadas 24h",
            int(searchbug.get("calls_24h") or 0),
            "",
            "ok",
        ),
        _metric(
            "ghost_pct",
            "Pagas sem telefone",
            round(ghost * 100 / billed, 1) if billed else 0.0,
            "%",
            "ok" if billed < 10 or ghost / billed <= 0.3 else "warn",
            "30%",
        ),
    ]
    return _layer(
        "quotas",
        penalties,
        reasons,
        headline,
        metrics,
        {"brave": brave, "searchbug": searchbug},
    )


def score_infra(
    checks: list[dict],
    disk_pct: Optional[float],
    worker_age_min: Optional[float],
    backup_age_h: Optional[float],
    now: datetime,
) -> dict:
    penalties: list[float] = []
    reasons: list[str] = []
    by_name = {str(c.get("check_name") or c.get("name")): c for c in checks or []}

    def status_of(name: str) -> Optional[str]:
        row = by_name.get(name)
        return str(row.get("status")) if row else None

    if status_of("db") == "fail":
        penalties.append(50)
        reasons.append("BD indisponível")
    if status_of("worker") == "fail" or (worker_age_min is not None and worker_age_min > 15):
        penalties.append(40)
        reasons.append("Worker sem heartbeat")
    elif status_of("worker") == "warn" or (worker_age_min is not None and worker_age_min > 5):
        penalties.append(10)
        reasons.append("Worker com heartbeat atrasado")
    if status_of("gmail_tokens") == "fail":
        penalties.append(40)
        reasons.append("Tokens Gmail inválidos")
    if status_of("backup") == "fail" or (backup_age_h is not None and backup_age_h > 72):
        penalties.append(30)
        reasons.append("Backup em falta/antigo")
    elif status_of("backup") == "warn" or (backup_age_h is not None and backup_age_h > 36):
        penalties.append(15)
        reasons.append("Backup com atraso")
    if status_of("vps_worker") == "fail":
        penalties.append(20)
        reasons.append("VPS worker indisponível")
    if disk_pct is not None:
        if disk_pct > 90:
            penalties.append(30)
            reasons.append(f"Disco a {disk_pct:.0f}%")
        elif disk_pct > 80:
            penalties.append(15)
            reasons.append(f"Disco a {disk_pct:.0f}%")

    headline = " · ".join(
        [
            f"worker {'OK' if (worker_age_min or 0) <= 5 else 'atrasado'}",
            f"backup {('%.0fh' % backup_age_h) if backup_age_h is not None else 'nunca'}",
            f"disco {('%.0f%%' % disk_pct) if disk_pct is not None else '—'}",
        ]
    )
    metrics = [
        _metric(
            "worker",
            "Worker",
            round(worker_age_min, 1) if worker_age_min is not None else None,
            "min",
            "ok" if (worker_age_min or 0) <= 5 else "warn",
            "5 min",
        ),
        _metric(
            "backup",
            "Backup",
            round(backup_age_h, 1) if backup_age_h is not None else None,
            "h",
            "ok" if (backup_age_h or 0) <= 36 else "fail",
            "36h",
        ),
        _metric(
            "disk",
            "Disco",
            round(disk_pct, 0) if disk_pct is not None else None,
            "%",
            "ok" if (disk_pct or 0) <= 80 else "warn",
            "80%",
        ),
        _metric(
            "gmail",
            "Tokens Gmail",
            1 if status_of("gmail_tokens") == "ok" else 0,
            "",
            "ok" if status_of("gmail_tokens") == "ok" else "fail",
        ),
    ]
    return _layer(
        "infra",
        penalties,
        reasons,
        headline,
        metrics,
        {"checks": checks},
    )


def _is_operational_alert(alert: dict) -> bool:
    code = str((alert or {}).get("code") or "").upper()
    return not any(code.startswith(p) for p in NON_OPERATIONAL_ALERT_PREFIXES)


def score_alerts(alerts: list[dict], now: datetime) -> dict:
    penalties: list[float] = []
    reasons: list[str] = []
    operational = [a for a in alerts if _is_operational_alert(a)]
    informational = [a for a in alerts if not _is_operational_alert(a)]
    critical = [
        a for a in operational
        if str(a.get("level")).lower() in ("critical", "error", "fail")
    ]
    warnings = [
        a for a in operational
        if str(a.get("level")).lower() in ("warning", "warn")
    ]
    # Alertas críticos antigos (>7 dias) são dívida de governação, não uma
    # falha operacional de agora: pesam menos e não pintam o painel de vermelho
    # para sempre até alguém reconhecer o alerta.
    critical_recent = [
        a for a in critical
        if (_age_hours(a.get("created_at"), now) or 0) <= 24 * 7
    ]
    critical_old = len(critical) - len(critical_recent)
    penalties.append(
        min(
            60,
            30 * len(critical_recent)
            + 5 * critical_old
            + 2 * len(warnings),
        )
    )
    if critical_recent:
        reasons.append(f"{len(critical_recent)} alerta(s) crítico(s) recente(s)")
    elif critical_old:
        reasons.append(f"{critical_old} alerta(s) crítico(s) histórico(s)")
    elif warnings:
        reasons.append(f"{len(warnings)} alerta(s) de atenção")

    oldest_age = None
    for alert in operational:
        age = _age_hours(alert.get("created_at"), now)
        if age is not None and (oldest_age is None or age > oldest_age):
            oldest_age = age
    # O alerta mais antigo só pesa se for de um alerta ainda "vivo" (crítico
    # recente ou warning); históricos já são contados em `critical_old`.
    live_ages = [
        _age_hours(a.get("created_at"), now) for a in (critical_recent + warnings)
    ]
    live_ages = [a for a in live_ages if a is not None]
    if live_ages and max(live_ages) > 24:
        penalties.append(10)
        reasons.append(f"Alerta aberto há {max(live_ages):.0f}h")

    occurrences = sum(max(1, int(a.get("occurrences") or 1)) for a in alerts)
    headline = f"{len(alerts)} aberto(s)"
    if informational:
        headline += f" ({len(informational)} informativo(s))"
    if occurrences > len(alerts):
        headline += f" · {occurrences} ocorrência(s)"
    metrics = [
        _metric(
            "open",
            "Abertos",
            len(alerts),
            "",
            "ok" if not operational else "warn",
        ),
        _metric(
            "critical",
            "Críticos recentes",
            len(critical_recent),
            "",
            "ok" if not critical_recent else "fail",
        ),
        _metric("warning", "Atenção", len(warnings), "", "ok" if not warnings else "warn"),
        _metric(
            "historical",
            "Críticos >7d",
            critical_old,
            "",
            "ok" if not critical_old else "warn",
        ),
        _metric(
            "occurrences",
            "Ocorrências",
            occurrences,
            "",
            "ok" if occurrences <= len(alerts) else "warn",
            "histórico do mesmo código",
        ),
        _metric(
            "informational",
            "Auditoria (info)",
            len(informational),
            "",
            "ok",
            "não pesa no score",
        ),
        _metric(
            "oldest_h",
            "Mais antigo",
            round(oldest_age, 1) if oldest_age is not None else None,
            "h",
            "ok" if (oldest_age or 0) <= 24 else "warn",
            "24h",
        ),
    ]
    return _layer(
        "alerts",
        penalties,
        reasons,
        headline,
        metrics,
        {
            "items": [
                {**alert, "informational": not _is_operational_alert(alert)}
                for alert in alerts
            ]
        },
    )


def build_overall(layers: dict) -> dict:
    score = _clamp(
        sum(
            int(layers[key]["score"]) * LAYER_WEIGHTS[key]
            for key in LAYER_ORDER
            if key in layers
        )
        / max(1, sum(LAYER_WEIGHTS[key] for key in layers if key in layers))
    )
    worst = "ok"
    for key in LAYER_ORDER:
        status = str((layers.get(key) or {}).get("status") or "ok")
        if status == "fail":
            worst = "fail"
            break
        if status == "warn":
            worst = "warn"
    reasons: list[str] = []
    for key in LAYER_ORDER:
        for reason in (layers.get(key) or {}).get("reasons") or []:
            if reason not in reasons:
                reasons.append(reason)
    return {
        "status": worst,
        "status_label": STATUS_LABELS[worst],
        "score": score,
        "reasons": reasons[:5],
    }


# ------------------------------------------------------------------ gather
def _disk_pct() -> Optional[float]:
    path = os.getenv("DATA_DIR") or "/data"
    if not os.path.isdir(path):
        path = os.getcwd()
    try:
        usage = shutil.disk_usage(path)
        return round(usage.used * 100 / usage.total, 1) if usage.total else None
    except OSError:
        return None


def _gather_sync() -> dict:
    conn = get_connection()
    try:
        cities = [dict(r) for r in conn.execute(
            """
            SELECT UPPER(TRIM(city)) AS city, COUNT(*) AS total,
                   SUM(CASE WHEN date_reported >= datetime('now','-24 hours')
                            THEN 1 ELSE 0 END) AS facts_24h,
                   SUM(CASE WHEN created_at >= datetime('now','-24 hours')
                            THEN 1 ELSE 0 END) AS created_24h,
                   MAX(date_reported) AS last_fact,
                   SUM(CASE WHEN COALESCE(TRIM(owner_name),'') <> ''
                            THEN 1 ELSE 0 END) AS owners,
                   SUM(CASE WHEN COALESCE(TRIM(owner_email),'') <> ''
                            THEN 1 ELSE 0 END) AS emails
            FROM leads GROUP BY 1 ORDER BY total DESC
            """
        ).fetchall()]
        # Uma cidade servida sem leads nenhuns tem de aparecer (score falha),
        # não desaparecer do painel.
        by_city = {str(c["city"]).upper(): c for c in cities}
        for city in SERVED_CITIES:
            by_city.setdefault(
                city,
                {
                    "city": city, "total": 0, "facts_24h": 0,
                    "created_24h": 0, "last_fact": None, "owners": 0,
                    "emails": 0,
                },
            )
        cities = list(by_city.values())
        city_health = {
            str(r["city"]).upper(): dict(r)
            for r in conn.execute("SELECT * FROM city_health").fetchall()
        }
        for row in cities:
            row["health"] = city_health.get(str(row["city"]).upper(), {})
        runs = [dict(r) for r in conn.execute(
            "SELECT run_id, trigger, status, inserted, total_raw, started_at, "
            "finished_at, error FROM scraper_runs ORDER BY id DESC LIMIT 8"
        ).fetchall()]
        runs_24h = dict(conn.execute(
            "SELECT COUNT(*) AS runs, COALESCE(SUM(inserted), 0) AS inserted, "
            "COALESCE(SUM(total_raw), 0) AS raw FROM scraper_runs "
            "WHERE started_at >= datetime('now','-24 hours')"
        ).fetchone())
        states = [dict(r) for r in conn.execute(
            "SELECT s.city, s.jobs_today, s.domain_jobs_today, s.last_run_at, "
            "       CASE WHEN c.value='1' THEN 1 ELSE 0 END AS enabled "
            "FROM city_enrichment_state s "
            "LEFT JOIN outbound_config c ON c.scope='outbound' "
            "  AND c.city=s.city AND c.key='enrich_enabled'"
        ).fetchall()]
        # Cidades activas sem estado ainda (primeiro dia) contam como ligadas
        # se a config global/cidade estiver a 1.
        for row in conn.execute(
            "SELECT city FROM outbound_config WHERE scope='outbound' "
            "AND key='enrich_enabled' AND value='1' AND city<>''"
        ).fetchall():
            key = str(row["city"]).upper()
            if not any(str(s["city"]).upper() == key for s in states):
                states.append(
                    {"city": key, "jobs_today": 0, "domain_jobs_today": 0,
                     "last_run_at": None, "enabled": 1}
                )
        entity_counts: dict[str, dict[str, int]] = {}
        for r in conn.execute(
            "SELECT UPPER(TRIM(city)) AS city, status, COUNT(*) AS c "
            "FROM contractor_entities GROUP BY 1,2"
        ).fetchall():
            entity_counts.setdefault(str(r["city"]), {})[str(r["status"])] = int(r["c"])
        jobs = {"pending": 0, "running": 0, "oldest_age_h": None, "by_status": {}}
        oldest_job = None
        for r in conn.execute(
            "SELECT status, COUNT(*) AS c, MIN(created_at) AS oldest "
            "FROM outbound_enrichment_jobs GROUP BY status"
        ).fetchall():
            status = str(r["status"])
            count = int(r["c"])
            jobs["by_status"][status] = count
            if status in ("pending", "running"):
                jobs["pending"] += count
                if r["oldest"] and (oldest_job is None or str(r["oldest"]) < str(oldest_job)):
                    oldest_job = r["oldest"]
        jobs["oldest"] = oldest_job
        owner_states = [dict(r) for r in conn.execute(
            "SELECT city, jobs_today, last_run_at FROM owner_backfill_state"
        ).fetchall()]
        brave_kv = {
            str(r["key"]): str(r["value"])
            for r in conn.execute(
                "SELECT key, value FROM system_kv WHERE key LIKE 'brave%'"
            ).fetchall()
        }
        searchbug = dict(conn.execute(
            """
            SELECT
              COALESCE(SUM(CASE WHEN called_at >= datetime('now','-24 hours')
                                THEN cost_usd ELSE 0 END), 0) AS cost_24h,
              COALESCE(SUM(CASE WHEN called_at >= datetime('now','-24 hours')
                                THEN 1 ELSE 0 END), 0) AS calls_24h,
              COALESCE(SUM(CASE WHEN called_at >= datetime('now','-1 hour')
                                THEN cost_usd ELSE 0 END), 0) AS cost_1h,
              COALESCE(SUM(CASE WHEN called_at >= datetime('now','-15 minutes')
                                THEN 1 ELSE 0 END), 0) AS calls_15m,
              COALESCE(SUM(CASE WHEN called_at >= datetime('now','-15 minutes')
                                AND transport_error=1 THEN 1 ELSE 0 END), 0) AS transport_15m,
              COALESCE(SUM(CASE WHEN called_at >= datetime('now','-24 hours')
                                AND billed=1 THEN 1 ELSE 0 END), 0) AS billed,
              COALESCE(SUM(CASE WHEN called_at >= datetime('now','-24 hours')
                                AND billed=1 AND outcome<>'success' THEN 1 ELSE 0 END), 0) AS ghost
            FROM searchbug_calls
            """
        ).fetchone())
        push = dict(conn.execute(
            """
            SELECT
              COUNT(*) AS deliveries,
              COALESCE(SUM(CASE WHEN outcome='accepted' THEN 1 ELSE 0 END), 0) AS accepted,
              COALESCE(SUM(CASE WHEN outcome='expired' THEN 1 ELSE 0 END), 0) AS expired,
              COALESCE(SUM(CASE WHEN outcome='rejected_dead' THEN 1 ELSE 0 END), 0) AS rejected_dead,
              COALESCE(SUM(CASE WHEN outcome='not_configured' THEN 1 ELSE 0 END), 0) AS not_configured,
              COALESCE(SUM(CASE WHEN clicked_at IS NOT NULL THEN 1 ELSE 0 END), 0) AS clicks
            FROM push_deliveries WHERE sent_at >= datetime('now','-24 hours')
            """
        ).fetchone())
        subs = dict(conn.execute(
            "SELECT COUNT(*) AS total, "
            "COALESCE(SUM(CASE WHEN disabled_at IS NULL THEN 1 ELSE 0 END), 0) AS active "
            "FROM push_subscriptions"
        ).fetchone())
        push["active_subs"] = int(subs["active"])
        push["total_subs"] = int(subs["total"])
        last_accepted = conn.execute(
            "SELECT MAX(sent_at) FROM push_deliveries WHERE outcome='accepted'"
        ).fetchone()[0]
        push["last_accepted"] = last_accepted
        push["notifications_24h"] = int(
            conn.execute(
                "SELECT COUNT(*) FROM notifications "
                "WHERE created_at >= datetime('now','-24 hours')"
            ).fetchone()[0]
            or 0
        )
        alert_rows = [dict(r) for r in conn.execute(
            "SELECT id, level, code, message, created_at FROM system_alerts "
            "WHERE acknowledged=0 ORDER BY id DESC LIMIT 200"
        ).fetchall()]
        # Um código repetido (ex.: BOSTON stale de 6 em 6 horas) é um só
        # problema operacional. O painel mostra ocorrências, não 9 cartões.
        alerts = dedupe_alerts(alert_rows, limit=50)
        return {
            "cities": cities,
            "city_health": city_health,
            "runs": runs,
            "runs_24h": runs_24h,
            "states": states,
            "entity_counts": entity_counts,
            "jobs": jobs,
            "owner_states": owner_states,
            "brave_kv": brave_kv,
            "searchbug": searchbug,
            "push": push,
            "alerts": alerts,
        }
    finally:
        conn.close()


def _brave_snapshot(kv: dict, states: list[dict], configured: bool) -> dict:
    from . import brave_search

    limit = int(brave_search.daily_limit()) if configured else 0
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    used = 0
    try:
        used = int(kv.get(f"brave_queries:{today}") or 0)
    except (TypeError, ValueError):
        used = 0
    blocked = bool(kv.get(f"brave_blocked:{today}")) or (limit > 0 and used >= limit)
    enabled = max(1, len([s for s in states if int(s.get("enabled") or 0)]))
    return {
        "configured": configured,
        "used": used,
        "limit": limit,
        "blocked": blocked,
        "domain_limit": (limit // enabled) if limit else 0,
    }


async def build_snapshot(
    window_hours: int = 24, include_history: bool = True
) -> dict:
    now = utcnow_aware()
    raw = await anyio.to_thread.run_sync(_gather_sync)
    try:
        from .outbound_engine import outbound_engine as engine

        out_status = await engine.status()
        out_metrics = await db_service.outbound_metrics(30)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[SYSTEM-HEALTH] outbound indisponível: %s", exc)
        out_status = {
            "send_enabled": False, "queued": 0, "mailboxes": [],
            "queue_blocker": {"reason": "unavailable", "detail": str(exc)},
        }
        out_metrics = {"totals": {}}

    checks = control_tower.latest_health()
    worker_age = _age_minutes(control_tower.kv_get(control_tower.KV_LAST_TICK), now)
    backup_age = _age_hours(control_tower.kv_get(control_tower.KV_LAST_BACKUP), now)

    from . import brave_search

    brave = _brave_snapshot(
        raw["brave_kv"], raw["states"], bool(brave_search.api_key())
    )
    jobs = raw["jobs"]
    if jobs.get("oldest"):
        jobs["oldest_age_h"] = _age_hours(jobs["oldest"], now)

    layers = {
        "ingest": score_ingest(
            raw["cities"],
            raw["runs"],
            now,
            interval_hours=float(
                getattr(settings, "SCRAPER_INTERVAL_HOURS", 6) or 6
            ),
            stale_hours=float(
                getattr(settings, "SCRAPER_STALE_HOURS", 36.0) or 36.0
            ),
            inserted_24h=int(raw["runs_24h"].get("inserted") or 0),
        ),
        "enrichment": score_enrichment(
            raw["states"], raw["entity_counts"], jobs, raw["owner_states"], brave, now
        ),
        "outreach": score_outreach(out_status, out_metrics, now),
        "push": score_push(raw["push"]),
        "quotas": score_quotas(brave, raw["searchbug"]),
        "infra": score_infra(checks, _disk_pct(), worker_age, backup_age, now),
        "alerts": score_alerts(raw["alerts"], now),
    }
    overall = build_overall(layers)
    snapshot = {
        "generated_at": now.isoformat(),
        "window_hours": max(1, min(int(window_hours), 168)),
        "overall": overall,
        "layers": layers,
        "history": [],
    }
    if include_history:
        snapshot["history"] = await _history(max(1, min(int(window_hours), 168)))
    return snapshot


async def _history(hours: int) -> list[dict]:
    rows = await db_service.list_system_health_snapshots(hours, 500)
    out: list[dict] = []
    for row in rows:
        try:
            payload = json.loads(row.get("payload") or "{}")
        except (TypeError, ValueError):
            payload = {}
        layer_scores = {
            key: int((payload.get("layers") or {}).get(key, {}).get("score") or 0)
            for key in LAYER_ORDER
        }
        out.append(
            {
                "captured_at": row.get("captured_at"),
                "status": row.get("overall_status"),
                "score": int(row.get("overall_score") or 0),
                "layers": layer_scores,
            }
        )
    return out


async def get_snapshot(window_hours: int = 24) -> dict:
    """Snapshot com cache de 30 s (protege a BD de refresh storms)."""
    now = time.monotonic()
    window = max(1, min(int(window_hours), 168))
    if (
        _CACHE["data"] is not None
        and _CACHE["window"] == window
        and (now - _CACHE["at"]) < CACHE_TTL_SECONDS
    ):
        return _CACHE["data"]
    data = await build_snapshot(window, include_history=True)
    _CACHE.update({"at": now, "window": window, "data": data})
    return data


def clear_cache() -> None:
    _CACHE.update({"at": 0.0, "window": 0, "data": None})


async def capture_snapshot() -> dict:
    """Grava 1 snapshot compacto (chamado pela Control Tower a cada 15 min)."""
    snap = await build_snapshot(24, include_history=False)
    compact = {
        "generated_at": snap["generated_at"],
        "overall": {
            "status": snap["overall"]["status"],
            "score": snap["overall"]["score"],
        },
        "layers": {
            key: {
                "status": layer.get("status"),
                "score": layer.get("score"),
                "headline": layer.get("headline"),
            }
            for key, layer in snap["layers"].items()
        },
    }
    await db_service.insert_system_health_snapshot(
        snap["generated_at"],
        snap["overall"]["status"],
        snap["overall"]["score"],
        json.dumps(compact, ensure_ascii=False),
    )
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if control_tower.kv_get("system_health_prune_day") != today:
        removed = await db_service.prune_system_health_snapshots(30)
        control_tower.kv_set("system_health_prune_day", today)
        if removed:
            logger.info("[SYSTEM-HEALTH] %s snapshots antigos removidos", removed)
    return compact

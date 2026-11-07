"""Leituras read-only para o painel admin do plano de dados.

Nada aqui escreve dados de negócio: apenas SELECTs nas tabelas de auditoria
(`ingestion_runs`, `entity_quarantine`, `freshness_runs`, `geocode_jobs`) e
nas métricas de scoring. O plano de voz (DIDs, pacing, campanhas) não é
chamado nem alterado por este módulo.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from . import b2b_voice, self_healing
from .db import get_connection


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = datetime.strptime(text[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _age_hours(value: Any) -> float | None:
    parsed = _parse(value)
    if not parsed:
        return None
    return round((_now() - parsed).total_seconds() / 3600, 1)


def _json(value: Any) -> Any:
    if value in (None, ""):
        return None
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return value


def _rows(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict]:
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def _leads_conn() -> sqlite3.Connection:
    self_healing.ensure_schema()
    return get_connection()


def _voice_conn() -> sqlite3.Connection:
    self_healing.ensure_schema()
    b2b_voice.init()
    return b2b_voice.get_conn()


# ----------------------------------------------------------------- ingestão


def ingestion(limit: int = 50) -> dict:
    limit = max(1, min(int(limit), 200))
    conn = _leads_conn()
    try:
        runs = _rows(
            conn,
            "SELECT id, run_id, source, status, attempt, http_status, "
            "rows_fetched, rows_parsed, rows_upserted, watermark_before, "
            "watermark_after, error_code, error_detail, started_at, finished_at "
            "FROM ingestion_runs ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        failures = _rows(
            conn,
            "SELECT id, run_id, source, url, http_status, error_class, "
            "retryable, next_retry_at, created_at "
            "FROM ingestion_failures ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        by_status = _rows(
            conn,
            "SELECT status, COUNT(1) n FROM ingestion_runs GROUP BY status",
        )
        by_source = _rows(
            conn,
            "SELECT source, status, COUNT(1) n, MAX(finished_at) last_at "
            "FROM ingestion_runs GROUP BY source, status ORDER BY source, status",
        )
        scraper_runs = _rows(
            conn,
            "SELECT id, run_id, trigger, started_at, finished_at, status, "
            "inserted, total_raw, cities_covered, error "
            "FROM scraper_runs ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        scraper_status = _rows(
            conn,
            "SELECT status, COUNT(1) n, COALESCE(SUM(inserted),0) inserted "
            "FROM scraper_runs GROUP BY status",
        )
        last_success = conn.execute(
            "SELECT started_at, finished_at, source FROM ingestion_runs "
            "WHERE status='success' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        last_failure = conn.execute(
            "SELECT started_at, source, error_code FROM ingestion_runs "
            "WHERE status<>'success' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    return {
        "runs": runs,
        "failures": failures,
        "by_status": by_status,
        "by_source": by_source,
        "scraper_runs": scraper_runs,
        "scraper_status": scraper_status,
        "last_success": dict(last_success) if last_success else None,
        "last_failure": dict(last_failure) if last_failure else None,
        "coverage_note": (
            "ingestion_runs cobre os conectores de licenças (DCWP, DOB "
            "licenses, DSNY, TDLR, IL, Chicago). Socrata/HPD/DOB violations "
            "são agregados em scraper_runs."
        ),
    }


# --------------------------------------------------------------- quarentena


def quarantine(limit: int = 200) -> dict:
    limit = max(1, min(int(limit), 500))
    conn = _leads_conn()
    try:
        active = _rows(
            conn,
            "SELECT q.id, q.entity_id, q.reason, q.rule_id, q.status, "
            "q.evidence_json, q.created_at, e.legal_name, e.license, "
            "e.state, e.city, e.phone, e.status AS entity_status "
            "FROM entity_quarantine q "
            "LEFT JOIN contractor_entities e ON e.id=q.entity_id "
            "WHERE q.status='active' ORDER BY q.id DESC LIMIT ?",
            (limit,),
        )
        for row in active:
            row["evidence"] = _json(row.get("evidence_json"))
        findings = _rows(
            conn,
            "SELECT id, run_id, entity_id, company_id, rule_id, severity, "
            "status, evidence_json, created_at, resolved_at "
            "FROM data_quality_findings ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        for row in findings:
            row["evidence"] = _json(row.get("evidence_json"))
        findings_by_rule = _rows(
            conn,
            "SELECT rule_id, severity, status, COUNT(1) n "
            "FROM data_quality_findings GROUP BY rule_id, severity, status "
            "ORDER BY n DESC",
        )
        entity_status = _rows(
            conn,
            "SELECT status, COUNT(1) n FROM contractor_entities "
            "GROUP BY status ORDER BY n DESC",
        )
        quarantined_total = sum(
            int(row["n"]) for row in entity_status if row["status"] == "quarantined"
        )
    finally:
        conn.close()
    placeholders = len(active)
    return {
        "active": active,
        "active_count": placeholders,
        "reason_counts": _counts(active, "reason"),
        "findings": findings,
        "findings_by_rule": findings_by_rule,
        "findings_total": len(findings),
        "entity_status": entity_status,
        "entity_quarantined_total": quarantined_total,
        "other_quarantined": max(0, quarantined_total - placeholders),
        "note": (
            "Os 9 placeholders são a quarentena ativa de `entity_quarantine`. "
            "`contractor_entities.status='quarantined'` inclui também entidades "
            "de enriquecimento já isoladas (não são os placeholders)."
        ),
    }


def _counts(rows: list[dict], key: str) -> list[dict]:
    bucket: dict[str, int] = {}
    for row in rows:
        value = str(row.get(key) or "-")
        bucket[value] = bucket.get(value, 0) + 1
    return [
        {"value": value, "n": n}
        for value, n in sorted(bucket.items(), key=lambda item: (-item[1], item[0]))
    ]


# ---------------------------------------------------------------- freshness


def freshness(limit: int = 50) -> dict:
    limit = max(1, min(int(limit), 200))
    conn = _leads_conn()
    try:
        runs = _rows(
            conn,
            "SELECT id, started_at, finished_at, hpd_checked, hpd_closed, "
            "dob_checked, dob_closed, history_refreshed, status, errors "
            "FROM freshness_runs ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        by_status = _rows(
            conn,
            "SELECT status, COUNT(1) n FROM freshness_runs GROUP BY status",
        )
        geocode = _rows(
            conn,
            "SELECT status, COUNT(1) n FROM geocode_jobs GROUP BY status "
            "ORDER BY n DESC",
        )
        remediation_count = int(
            conn.execute("SELECT COUNT(1) FROM health_remediations").fetchone()[0]
            or 0
        )
        remediations = _rows(
            conn,
            "SELECT id, check_name, attempt, action, status, next_attempt_at, "
            "last_error, created_at, resolved_at FROM health_remediations "
            "ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        sanitizer = _rows(
            conn,
            "SELECT id, run_id, mode, findings_count, quarantined_count, "
            "started_at, finished_at FROM sanitizer_runs "
            "ORDER BY id DESC LIMIT ?",
            (limit,),
        )
    finally:
        conn.close()
    last = runs[0] if runs else None
    return {
        "runs": runs,
        "last_run": last,
        "last_age_hours": _age_hours((last or {}).get("finished_at")),
        "by_status": by_status,
        "geocode": geocode,
        "geocode_total": sum(int(row["n"]) for row in geocode),
        "health_remediations": remediations,
        "health_remediations_count": remediation_count,
        "health_remediations_implemented": remediation_count > 0,
        "sanitizer_runs": sanitizer,
    }


# -------------------------------------------------------------------- score


def score_summary() -> dict:
    conn = _voice_conn()
    try:
        stats = conn.execute(
            "SELECT MIN(score) mn, MAX(score) mx, AVG(score) avg, "
            "COUNT(DISTINCT score) distinct_scores, COUNT(1) total, "
            "MAX(updated_at) updated_at FROM prospect_companies"
        ).fetchone()
        buckets = _rows(
            conn,
            "SELECT CAST(score / 10 AS INTEGER) * 10 AS bucket, COUNT(1) n "
            "FROM prospect_companies GROUP BY bucket ORDER BY bucket",
        )
        snapshots = int(
            conn.execute("SELECT COUNT(1) FROM score_snapshots").fetchone()[0] or 0
        )
        null_components = int(
            conn.execute(
                "SELECT COUNT(1) FROM score_snapshots "
                "WHERE components_json IS NULL OR components_json=''"
            ).fetchone()[0]
            or 0
        )
        run = conn.execute(
            "SELECT id, version, status, processed, errors, source_watermark, "
            "started_at, finished_at, summary_json FROM score_runs "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    bucket_map = {int(row["bucket"]): int(row["n"]) for row in buckets}
    return {
        "total": int(stats["total"] or 0),
        "min": float(stats["mn"] or 0),
        "max": float(stats["mx"] or 0),
        "avg": round(float(stats["avg"] or 0), 2),
        "distinct_scores": int(stats["distinct_scores"] or 0),
        "updated_at": stats["updated_at"],
        "buckets": [
            {"bucket": key, "label": f"{key}-{key + 9}", "n": bucket_map.get(key, 0)}
            for key in range(0, 70, 10)
        ],
        "snapshots": snapshots,
        "snapshots_without_components": null_components,
        "last_run": dict(run) if run else None,
    }


def score_detail(company_id: int) -> dict | None:
    conn = _voice_conn()
    try:
        company = conn.execute(
            "SELECT id, company_name, score, trade, city, state, phone, email, "
            "website, license_number, permit_count, permit_value_usd, "
            "years_active, employee_estimate, status, updated_at "
            "FROM prospect_companies WHERE id=?",
            (int(company_id),),
        ).fetchone()
        if not company:
            return None
        snapshot = conn.execute(
            "SELECT company_id, score, version, components_json, "
            "quality_penalty, computed_at, source_event_id "
            "FROM score_snapshots WHERE company_id=?",
            (int(company_id),),
        ).fetchone()
    finally:
        conn.close()
    out = dict(company)
    if snapshot:
        snap = dict(snapshot)
        snap["components"] = _json(snap.get("components_json"))
        snap.pop("components_json", None)
        out["snapshot"] = snap
    else:
        out["snapshot"] = None
    return out


# ------------------------------------------------------------------ summary


def summary() -> dict:
    """Payload único para os cartões do overview e para a página Data Plane."""
    return {
        "generated_at": _now().isoformat(),
        "ingestion": ingestion(limit=20),
        "quarantine": quarantine(limit=50),
        "freshness": freshness(limit=20),
        "score": score_summary(),
    }

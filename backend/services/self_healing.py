"""Fase 0 — estruturas de auditoria e sanitizer em dry-run.

Este modulo pertence ao plano de dados. Nao importa nem altera o auto-dialer,
DIDs, pacing ou campanhas. As escritas de quarentena sao explicitas e
auditadas; o resto do sanitizer corre em modo `dry_run`.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from . import b2b_voice
from .db import get_connection

LEADS_SCHEMA = """
CREATE TABLE IF NOT EXISTS domain_retry (
  entity_id INTEGER PRIMARY KEY REFERENCES contractor_entities(id) ON DELETE CASCADE,
  failures INTEGER NOT NULL DEFAULT 0,
  next_attempt_at TEXT,
  last_error TEXT,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ingestion_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL,
  source TEXT NOT NULL,
  status TEXT NOT NULL,
  attempt INTEGER NOT NULL DEFAULT 1,
  http_status INTEGER,
  rows_fetched INTEGER NOT NULL DEFAULT 0,
  rows_parsed INTEGER NOT NULL DEFAULT 0,
  rows_upserted INTEGER NOT NULL DEFAULT 0,
  watermark_before TEXT,
  watermark_after TEXT,
  error_code TEXT,
  error_detail TEXT,
  started_at TEXT NOT NULL,
  finished_at TEXT
);

CREATE TABLE IF NOT EXISTS ingestion_failures (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL,
  source TEXT NOT NULL,
  url TEXT,
  http_status INTEGER,
  error_class TEXT,
  retryable INTEGER NOT NULL DEFAULT 1,
  next_retry_at TEXT,
  payload_hash TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS data_quality_findings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL,
  entity_id INTEGER,
  company_id INTEGER,
  rule_id TEXT NOT NULL,
  severity TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'dry_run',
  evidence_json TEXT,
  created_at TEXT NOT NULL,
  resolved_at TEXT
);

CREATE TABLE IF NOT EXISTS entity_quarantine (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  entity_id INTEGER NOT NULL UNIQUE,
  reason TEXT NOT NULL,
  rule_id TEXT NOT NULL,
  evidence_json TEXT,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL,
  resolved_at TEXT
);

CREATE TABLE IF NOT EXISTS health_remediations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  check_name TEXT NOT NULL,
  attempt INTEGER NOT NULL DEFAULT 1,
  action TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  next_attempt_at TEXT,
  last_error TEXT,
  created_at TEXT NOT NULL,
  resolved_at TEXT
);

CREATE TABLE IF NOT EXISTS sanitizer_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL,
  mode TEXT NOT NULL,
  findings_count INTEGER NOT NULL DEFAULT 0,
  quarantined_count INTEGER NOT NULL DEFAULT 0,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  summary_json TEXT
);
"""

VOICE_SCHEMA = """
CREATE TABLE IF NOT EXISTS score_snapshots (
  company_id INTEGER PRIMARY KEY REFERENCES prospect_companies(id) ON DELETE CASCADE,
  score REAL NOT NULL,
  version TEXT NOT NULL,
  components_json TEXT,
  quality_penalty REAL NOT NULL DEFAULT 0,
  computed_at TEXT NOT NULL,
  source_event_id TEXT
);
"""

TEST_NAMES = {
    "SIGN GLORIOUS",
    "SIGNS OF THE TIMES",
    "LAA ADMIN SUPPORT PL",
    "DOB TESTER",
    "PLUMBER TESTER",
    "BOILER SOFTWARE ENGINEER",
    "OPEC INDUSTRIES",
    "PLUMBER SOFTWARE ENGINEER",
    "TEST",
}


_SCHEMA_READY = False


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_schema() -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    conn = get_connection()
    try:
        conn.executescript(LEADS_SCHEMA)
        conn.commit()
    finally:
        conn.close()
    b2b_voice.init()
    v = b2b_voice.get_conn()
    try:
        v.executescript(VOICE_SCHEMA)
        v.commit()
    finally:
        v.close()
    _SCHEMA_READY = True


def _insert_finding(
    conn: sqlite3.Connection,
    run_id: str,
    rule_id: str,
    severity: str,
    evidence: dict[str, Any],
    entity_id: int | None = None,
    company_id: int | None = None,
    status: str = "dry_run",
) -> None:
    conn.execute(
        "INSERT INTO data_quality_findings "
        "(run_id, entity_id, company_id, rule_id, severity, status, "
        "evidence_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            run_id,
            entity_id,
            company_id,
            rule_id,
            severity,
            status,
            json.dumps(evidence, ensure_ascii=False),
            _now(),
        ),
    )


def _placeholder_rows(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT id, legal_name, license, state, phone, status, bridged_at "
        "FROM contractor_entities WHERE license LIKE '%:99999%' "
        "OR license = 'SIGN HANGER:999232' "
        "OR upper(legal_name) IN ("
        + ",".join("?" for _ in TEST_NAMES)
        + ") ORDER BY id",
        tuple(sorted(TEST_NAMES)),
    ).fetchall()
    return [dict(row) for row in rows]


def dry_run() -> dict:
    ensure_schema()
    run_id = f"sanitize-{uuid.uuid4().hex[:12]}"
    started = _now()
    conn = get_connection()
    try:
        placeholders = _placeholder_rows(conn)
        shared = conn.execute(
            "SELECT COUNT(1) groups, COALESCE(SUM(n - 1), 0) extra FROM ("
            "SELECT phone, COUNT(1) n FROM contractor_entities "
            "WHERE COALESCE(TRIM(phone),'')<>'' GROUP BY phone HAVING COUNT(1)>1)"
        ).fetchone()
        phone_formats = conn.execute(
            "SELECT "
            "SUM(CASE WHEN phone LIKE '+1%' AND LENGTH(phone)=12 THEN 1 ELSE 0 END) e164, "
            "SUM(CASE WHEN LENGTH(REPLACE(REPLACE(REPLACE(phone,'-',''),' ',''),'(',''))=10 THEN 1 ELSE 0 END) ten_digit, "
            "COUNT(1) total FROM contractor_entities WHERE COALESCE(TRIM(phone),'')<>''"
        ).fetchone()
        no_source = conn.execute(
            "SELECT COUNT(1) FROM contractor_entities e WHERE NOT EXISTS "
            "(SELECT 1 FROM contractor_entity_sources s WHERE s.entity_id=e.id)"
        ).fetchone()[0]
        no_geo = conn.execute(
            "SELECT COUNT(1) FROM leads WHERE lat IS NULL OR lng IS NULL"
        ).fetchone()[0]
        dup_keys = conn.execute(
            "SELECT COUNT(1) FROM (SELECT state, COALESCE(license_type,''), license "
            "FROM contractor_entities WHERE COALESCE(TRIM(license),'')<>'' "
            "GROUP BY state, COALESCE(license_type,''), license HAVING COUNT(1)>1)"
        ).fetchone()[0]
        domain_attempts = {
            str(row["domain_attempts"]): int(row["n"])
            for row in conn.execute(
                "SELECT domain_attempts, COUNT(1) n FROM contractor_entities "
                "WHERE state='NY' AND COALESCE(TRIM(domain),'')='' "
                "GROUP BY domain_attempts ORDER BY domain_attempts"
            )
        }

        _insert_finding(
            conn, run_id, "test_placeholder", "critical",
            {"count": len(placeholders), "ids": [r["id"] for r in placeholders]},
        )
        _insert_finding(
            conn, run_id, "shared_phone", "high",
            {"groups": int(shared["groups"]), "extra_entities": int(shared["extra"])},
        )
        _insert_finding(
            conn, run_id, "phone_format", "high",
            {
                "total": int(phone_formats["total"]),
                "e164": int(phone_formats["e164"] or 0),
                "ten_digit": int(phone_formats["ten_digit"] or 0),
            },
        )
        _insert_finding(
            conn, run_id, "missing_source", "medium", {"count": int(no_source)}
        )
        _insert_finding(
            conn, run_id, "missing_geo", "medium", {"count": int(no_geo)}
        )
        _insert_finding(
            conn, run_id, "duplicate_identity_key", "medium",
            {"count": int(dup_keys)},
        )

        b2b_voice.init()
        v = b2b_voice.get_conn()
        try:
            score = v.execute(
                "SELECT MIN(score) mn, MAX(score) mx, COUNT(DISTINCT score) distinct_scores, "
                "COUNT(1) total FROM prospect_companies"
            ).fetchone()
        finally:
            v.close()
        _insert_finding(
            conn, run_id, "flat_score", "critical",
            {
                "min": score["mn"],
                "max": score["mx"],
                "distinct_scores": score["distinct_scores"],
                "total": score["total"],
            },
        )
        conn.commit()
    finally:
        conn.close()

    summary = {
        "run_id": run_id,
        "placeholders": placeholders,
        "placeholder_count": len(placeholders),
        "placeholder_ids": [r["id"] for r in placeholders],
        "shared_phone_groups": int(shared["groups"]),
        "shared_phone_extra_entities": int(shared["extra"]),
        "phone_total": int(phone_formats["total"]),
        "phone_e164": int(phone_formats["e164"] or 0),
        "phone_ten_digit": int(phone_formats["ten_digit"] or 0),
        "entities_without_source": int(no_source),
        "leads_without_geo": int(no_geo),
        "duplicate_identity_keys": int(dup_keys),
        "ny_domain_attempts": domain_attempts,
        "score_min": score["mn"],
        "score_max": score["mx"],
        "score_distinct": score["distinct_scores"],
        "score_total": score["total"],
        "mode": "dry_run",
    }
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO sanitizer_runs "
            "(run_id, mode, findings_count, quarantined_count, started_at, "
            "finished_at, summary_json) VALUES (?, 'dry_run', ?, 0, ?, ?, ?)",
            (run_id, 7, started, _now(), json.dumps(summary, ensure_ascii=False)),
        )
        conn.commit()
    finally:
        conn.close()
    return summary


def quarantine_test_entities(apply: bool = False) -> dict:
    """Quarentena controlada dos placeholders; nunca apaga linhas.

    `apply=False` devolve o manifesto. `apply=True` grava entidade
    quarantined + prospect do_not_call + auditoria.
    """
    ensure_schema()
    run_id = f"quarantine-{uuid.uuid4().hex[:12]}"
    started = _now()
    conn = get_connection()
    rows: list[dict] = []
    changed_entities = 0
    changed_prospects = 0
    try:
        rows = _placeholder_rows(conn)
        if apply:
            for row in rows:
                eid = int(row["id"])
                evidence = {
                    "legal_name": row["legal_name"],
                    "license": row["license"],
                    "phone": row["phone"],
                }
                conn.execute(
                    "UPDATE contractor_entities SET status='quarantined', "
                    "quarantine_reason='test_placeholder', "
                    "updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (eid,),
                )
                conn.execute(
                    "INSERT INTO entity_quarantine "
                    "(entity_id, reason, rule_id, evidence_json, status, created_at) "
                    "VALUES (?, 'test_placeholder', 'test_placeholder', ?, 'active', ?) "
                    "ON CONFLICT(entity_id) DO UPDATE SET reason=excluded.reason, "
                    "rule_id=excluded.rule_id, evidence_json=excluded.evidence_json, "
                    "status='active', resolved_at=NULL",
                    (eid, json.dumps(evidence, ensure_ascii=False), _now()),
                )
                _insert_finding(
                    conn, run_id, "test_placeholder", "critical", evidence,
                    entity_id=eid, status="quarantined",
                )
                changed_entities += 1

            b2b_voice.init()
            v = b2b_voice.get_conn()
            try:
                for row in rows:
                    phone = b2b_voice.normalize_phone(row.get("phone"))
                    prospects = v.execute(
                        "SELECT id, company_name, phone, status FROM prospect_companies "
                        "WHERE (phone=? AND ? IS NOT NULL) OR company_name=?",
                        (phone, phone, row["legal_name"]),
                    ).fetchall()
                    for p in prospects:
                        v.execute(
                            "UPDATE prospect_companies SET status='do_not_call', "
                            "notes=TRIM(COALESCE(notes,'') || ' test_placeholder_quarantine'), "
                            "updated_at=? WHERE id=?",
                            (_now(), int(p["id"])),
                        )
                        _insert_finding(
                            conn, run_id, "test_placeholder", "critical",
                            {"legal_name": row["legal_name"], "phone": p["phone"]},
                            entity_id=int(row["id"]),
                            company_id=int(p["id"]),
                            status="quarantined",
                        )
                        changed_prospects += 1
                v.commit()
            finally:
                v.close()
            conn.commit()
    finally:
        conn.close()

    result = {
        "run_id": run_id,
        "apply": apply,
        "entities": rows,
        "entity_count": len(rows),
        "quarantined_entities": changed_entities,
        "quarantined_prospects": changed_prospects,
    }
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO sanitizer_runs "
            "(run_id, mode, findings_count, quarantined_count, started_at, "
            "finished_at, summary_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                "enforce" if apply else "dry_run",
                len(rows),
                changed_entities if apply else 0,
                started,
                _now(),
                json.dumps(
                    {
                        "entity_count": len(rows),
                        "quarantined_entities": changed_entities,
                        "quarantined_prospects": changed_prospects,
                    },
                    ensure_ascii=False,
                ),
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return result


def record_domain_failure(entity_id: int, exc: BaseException) -> None:
    """Regista falha de domínio com backoff; não consome quota."""
    ensure_schema()
    now = datetime.now(timezone.utc)
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT failures FROM domain_retry WHERE entity_id=?", (int(entity_id),)
        ).fetchone()
        failures = int((row["failures"] if row else 0) or 0) + 1
        delay = min(21600, 120 * (2 ** min(failures - 1, 6)))
        nxt = (now + timedelta(seconds=delay)).isoformat()
        conn.execute(
            "INSERT INTO domain_retry "
            "(entity_id, failures, next_attempt_at, last_error, updated_at) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT(entity_id) DO UPDATE SET "
            "failures=excluded.failures, next_attempt_at=excluded.next_attempt_at, "
            "last_error=excluded.last_error, updated_at=excluded.updated_at",
            (int(entity_id), failures, nxt, str(exc)[:500], _now()),
        )
        conn.execute(
            "INSERT INTO ingestion_failures "
            "(run_id, source, url, http_status, error_class, retryable, "
            "next_retry_at, payload_hash, created_at) "
            "VALUES (?, 'domain', NULL, NULL, ?, 1, ?, NULL, ?)",
            (
                f"domain-{uuid.uuid4().hex[:12]}",
                type(exc).__name__,
                nxt,
                _now(),
            ),
        )
        conn.commit()
    finally:
        conn.close()

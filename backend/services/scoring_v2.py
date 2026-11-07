"""Scoring V2 — dinâmico, explicável e baseado em recência/gravidade.

O plano de voz lê `prospect_companies.score`; este módulo apenas escreve score,
snapshot e auditoria. Não toca em DIDs, pacing ou campanhas.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone

from . import b2b_voice, self_healing, voice_taxonomy
from .db import get_connection

VERSION = "v2.0"
_CITY = {
    "NEW YORK": "NYC",
    "NYC": "NYC",
    "CHICAGO": "CHICAGO",
    "DALLAS": "DALLAS",
    "BOSTON": "BOSTON",
}


def _city(value: object) -> str:
    text = " ".join(str(value or "").strip().upper().split())
    return _CITY.get(text, text)


def _parse(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _demand() -> dict[tuple[str, str], float]:
    """Demanda normalizada por cidade+categoria, com recência e gravidade."""
    now = datetime.now(timezone.utc)
    raw: dict[tuple[str, str], float] = defaultdict(float)
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT city, issue_category, date_reported, signal_type, "
            "signal_status FROM leads WHERE is_junk=0 "
            "AND COALESCE(signal_status,'open') IN ('open','')"
        ).fetchall()
    finally:
        conn.close()
    for row in rows:
        when = _parse(row["date_reported"])
        if not when:
            continue
        age_days = (now - when).days
        if age_days <= 7:
            recency = 1.0
        elif age_days <= 30:
            recency = 0.7
        elif age_days <= 90:
            recency = 0.4
        else:
            continue
        signal = str(row["signal_type"] or "")
        severity = {
            "legal_obligation": 1.0,
            "authorized_work": 0.85,
            "open_request": 0.6,
        }.get(signal, 0.5)
        raw[(_city(row["city"]), str(row["issue_category"] or ""))] += (
            recency * severity
        )
    top = max(raw.values(), default=0.0)
    if top <= 0:
        return {}
    return {key: value / top for key, value in raw.items()}


def _source_watermark() -> str:
    conn = get_connection()
    try:
        lead = conn.execute(
            "SELECT MAX(COALESCE(updated_at, created_at)) FROM leads"
        ).fetchone()[0]
        ent = conn.execute(
            "SELECT MAX(COALESCE(updated_at, created_at)) FROM contractor_entities"
        ).fetchone()[0]
    finally:
        conn.close()
    return str(max(str(lead or ""), str(ent or "")))


def _shared_phones() -> set[str]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT phone, COUNT(1) n FROM contractor_entities "
            "WHERE COALESCE(TRIM(phone),'')<>'' GROUP BY phone HAVING COUNT(1)>1"
        ).fetchall()
    finally:
        conn.close()
    return {
        b2b_voice.normalize_phone(row["phone"])
        for row in rows
        if b2b_voice.normalize_phone(row["phone"])
    }


def _confidence_map() -> dict[int, float]:
    b2b_voice.init()
    conn = b2b_voice.get_conn()
    try:
        rows = conn.execute(
            "SELECT company_id, MAX(confidence) c FROM company_trades "
            "WHERE confidence>=0.80 AND source<>'primary_unconfirmed' "
            "GROUP BY company_id"
        ).fetchall()
    finally:
        conn.close()
    return {int(row["company_id"]): float(row["c"]) for row in rows}


def recompute_all() -> dict:
    self_healing.ensure_schema()
    started = datetime.now(timezone.utc).isoformat()
    demand = _demand()
    shared = _shared_phones()
    confidence = _confidence_map()
    now = datetime.now(timezone.utc)
    b2b_voice.init()
    conn = b2b_voice.get_conn()
    try:
        prospects = conn.execute(
            "SELECT id, company_name, phone, email, website, city, trade, "
            "license_number, permit_count, permit_value_usd, years_active, "
            "employee_estimate, created_at, notes, status "
            "FROM prospect_companies"
        ).fetchall()
        snapshots = []
        updates = []
        buckets = defaultdict(int)
        for row in prospects:
            trade = str(row["trade"] or "")
            city = _city(row["city"])
            demand_value = max(
                (
                    demand.get((city, category), 0.0)
                    for category in voice_taxonomy.TRADE_TO_CATEGORIES.get(
                        trade, ()
                    )
                ),
                default=0.0,
            )
            conf = confidence.get(int(row["id"]), 0.0)
            contact = 4.0
            contact += 3.0 if row["email"] else 0.0
            contact += 3.0 if row["website"] else 0.0
            license_score = 8.0 if row["license_number"] else 0.0
            strength = (
                min(1.0, float(row["permit_count"] or 0) / 10.0) * 0.4
                + min(1.0, float(row["permit_value_usd"] or 0) / 50000.0) * 0.3
                + min(1.0, float(row["years_active"] or 0) / 10.0) * 0.2
                + min(1.0, float(row["employee_estimate"] or 0) / 50.0) * 0.1
            )
            created = _parse(row["created_at"])
            age = (now - created).days if created else 9999
            freshness = 5.0 if age <= 7 else 3.0 if age <= 30 else 1.0 if age <= 90 else 0.0
            penalty = 0.0
            if "test_placeholder" in str(row["notes"] or ""):
                penalty += 50.0
            phone = b2b_voice.normalize_phone(row["phone"])
            if phone and phone in shared:
                penalty += 8.0
            score = (
                10.0
                + 30.0 * demand_value
                + 12.0 * conf
                + license_score
                + contact
                + 8.0 * strength
                + freshness
                - penalty
            )
            score = round(max(0.0, min(100.0, score)), 2)
            buckets[int(score // 10) * 10] += 1
            components = {
                "demand": round(demand_value, 4),
                "trade_confidence": round(conf, 4),
                "license": license_score,
                "contact": contact,
                "company_strength": round(strength, 4),
                "freshness": freshness,
                "quality_penalty": penalty,
            }
            updates.append((int(round(score)), int(row["id"])))
            snapshots.append(
                (
                    int(row["id"]),
                    score,
                    VERSION,
                    json.dumps(components, ensure_ascii=False),
                    penalty,
                    now.isoformat(),
                    None,
                )
            )
        conn.executemany(
            "UPDATE prospect_companies SET score=?, updated_at=? WHERE id=?",
            [(score, now.isoformat(), cid) for score, cid in updates],
        )
        conn.executemany(
            "INSERT INTO score_snapshots "
            "(company_id, score, version, components_json, quality_penalty, "
            "computed_at, source_event_id) VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(company_id) DO UPDATE SET score=excluded.score, "
            "version=excluded.version, components_json=excluded.components_json, "
            "quality_penalty=excluded.quality_penalty, "
            "computed_at=excluded.computed_at, "
            "source_event_id=excluded.source_event_id",
            snapshots,
        )
        conn.commit()
    finally:
        conn.close()
    summary = {
        "version": VERSION,
        "processed": len(prospects),
        "buckets": dict(sorted(buckets.items())),
        "min": min((s[1] for s in snapshots), default=0),
        "max": max((s[1] for s in snapshots), default=0),
        "distinct": len({s[1] for s in snapshots}),
    }
    b2b_voice.init()
    conn = b2b_voice.get_conn()
    try:
        conn.execute(
            "INSERT INTO score_runs "
            "(version, status, processed, errors, source_watermark, "
            "started_at, finished_at, summary_json) "
            "VALUES (?, 'success', ?, 0, ?, ?, ?, ?)",
            (
                VERSION,
                len(prospects),
                _source_watermark(),
                started,
                datetime.now(timezone.utc).isoformat(),
                json.dumps(summary, ensure_ascii=False),
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return summary


def recompute_if_changed() -> dict:
    self_healing.ensure_schema()
    watermark = _source_watermark()
    b2b_voice.init()
    conn = b2b_voice.get_conn()
    try:
        last = conn.execute(
            "SELECT source_watermark FROM score_runs "
            "WHERE status='success' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    if last and str(last["source_watermark"] or "") >= watermark:
        return {"status": "skipped", "watermark": watermark}
    return {"status": "recomputed", **recompute_all()}

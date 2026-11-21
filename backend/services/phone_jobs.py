"""Fila persistente de consultas pagas de telefone.

O clique enfileira e devolve `in_progress`; o worker chama a Searchbug fora do
pedido HTTP. Isso cumpre o invariante "nunca chamar a Searchbug no clique" sem
perder o trabalho quando o processo reinicia (o estado vive no SQLite).

Single-flight: `phone_jobs.cache_key` e' UNIQUE. Dois cliques simultaneos no
mesmo lead/nome/morada produzem um unico job e uma unica factura.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from ..config import settings
from ..utils.logger import logger
from . import billing_time, daily_quota, free_unlocks, phone_cache, phone_policy
from .db import db_service, get_connection
from .lead_rules import get_owner_class
from .searchbug import classify_searchbug_outcome, searchbug_service

BACKOFF_MINUTES = (1, 5, 15)
MAX_ATTEMPTS = 3
POLL_SECONDS = float(getattr(settings, "PHONE_JOB_POLL_SECONDS", 15.0) or 15.0)

_STATUS_PENDING = "pending"
_STATUS_RUNNING = "running"
_STATUS_DONE = "done"
_STATUS_FAILED = "failed"


def _now() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def enqueue(
    *,
    cache_key: str,
    lead_id: int,
    user_id: Optional[int],
    idempotency_key: Optional[str],
    trigger: str,
    decision: "phone_policy.PhoneDecision",
    quota_ref: Optional[dict[str, Any]],
) -> dict[str, Any]:
    """Cria (ou reutiliza) o job. Nunca duplica trabalho pago."""
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO phone_jobs
              (cache_key, lead_id, user_id, idempotency_key, trigger, status,
               attempts, next_attempt_at, quota_bucket, quota_addon_id,
               lookup_address_kind)
            VALUES (?, ?, ?, ?, ?, 'pending', 0, ?, ?, ?, ?)
            ON CONFLICT(cache_key) DO NOTHING
            """,
            (
                cache_key,
                int(lead_id),
                user_id,
                idempotency_key,
                trigger,
                _now(),
                (quota_ref or {}).get("bucket"),
                (quota_ref or {}).get("addon_id"),
                decision.lookup_address_kind,
            ),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM phone_jobs WHERE cache_key = ?", (cache_key,)
        ).fetchone()
        return dict(row) if row else {}
    finally:
        conn.close()


def get_by_cache_key(cache_key: str) -> Optional[dict[str, Any]]:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM phone_jobs WHERE cache_key = ?", (cache_key,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def claim_due(
    limit: int = 5, lead_id: Optional[int] = None
) -> list[dict[str, Any]]:
    """Reivindica jobs devidos de forma atomica. Nao bloqueia leitores."""
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        where = "status = 'pending' AND datetime(next_attempt_at) <= datetime('now')"
        params: list[Any] = []
        if lead_id is not None:
            where += " AND lead_id = ?"
            params.append(int(lead_id))
        params.append(int(limit))
        rows = conn.execute(
            f"""
            SELECT * FROM phone_jobs
            WHERE {where}
            ORDER BY id ASC
            LIMIT ?
            """,
            tuple(params),
        ).fetchall()
        claimed = []
        for row in rows:
            cur = conn.execute(
                """
                UPDATE phone_jobs
                SET status = 'running', claimed_at = ?, updated_at = ?,
                    attempts = attempts + 1
                WHERE id = ? AND status = 'pending'
                """,
                (_now(), _now(), row["id"]),
            )
            if cur.rowcount:
                claimed.append(
                    {**dict(row), "attempts": int(row["attempts"] or 0) + 1}
                )
        conn.commit()
        return claimed
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _finish(job_id: int, status: str, error: Optional[str] = None) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE phone_jobs SET status = ?, last_error = ?, updated_at = ? WHERE id = ?",
            (status, (error or "")[:300] or None, _now(), int(job_id)),
        )
        conn.commit()
    finally:
        conn.close()


def _retry_later(job: dict[str, Any], error: str) -> bool:
    """Reagenda ou falha em definitivo. True se reagendou."""
    attempts = int(job.get("attempts") or 0)
    if attempts >= MAX_ATTEMPTS:
        _finish(int(job["id"]), _STATUS_FAILED, error)
        return False
    delay = BACKOFF_MINUTES[min(attempts, len(BACKOFF_MINUTES) - 1)]
    next_at = (datetime.utcnow() + timedelta(minutes=delay)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    conn = get_connection()
    try:
        conn.execute(
            """
            UPDATE phone_jobs
            SET status = 'pending', next_attempt_at = ?, last_error = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (next_at, error[:300], _now(), int(job["id"])),
        )
        conn.commit()
    finally:
        conn.close()
    return True


def _persist_reveal(
    job: dict[str, Any],
    lead: dict[str, Any],
    *,
    phone: str,
    verified: bool,
    label: Optional[str],
) -> None:
    """Regista o reveal concluido para o proximo clique nao voltar a cobrar.

    O clique que enfileirou e' o dono desta revelacao. `idempotency_key` e'
    UNIQUE, por isso um retry do worker nao duplica a linha.
    """
    user_id = job.get("user_id")
    if not user_id:
        return
    idem = str(job.get("idempotency_key") or f"phone-job:{job.get('id')}")
    payload = {
        "lead_id": int(lead.get("id") or job.get("lead_id")),
        "type": "phone",
        "trade_code": str(lead.get("issue_category") or ""),
        "phone": phone,
        "verified": bool(verified),
        "label": label,
        "owner_name": lead.get("owner_name"),
        "address": lead.get("address"),
        "city": lead.get("city"),
        "state": lead.get("state"),
        "zip_code": lead.get("zip_code"),
        "price_cents": 0,
    }
    conn = get_connection()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO lead_reveals "
            "(lead_id, user_id, revealed_date, idempotency_key, reveal_type, "
            "trade_code, credits_cents, payload_json, searchbug_call_id) "
            "VALUES (?, ?, ?, ?, 'phone', ?, 0, ?, NULL)",
            (
                int(lead.get("id") or job.get("lead_id")),
                int(user_id),
                billing_time.local_date(datetime.now(timezone.utc)),
                idem,
                str(lead.get("issue_category") or "") or None,
                json.dumps(payload, ensure_ascii=False),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _refund_quota(job: dict[str, Any]) -> None:
    user_id = job.get("user_id")
    bucket = job.get("quota_bucket")
    if not user_id or not bucket:
        return
    try:
        if str(bucket) == "free_bonus":
            free_unlocks.refund_phone(
                int(user_id), job.get("lead_id")
            )
            return
        daily_quota.refund_phone(int(user_id), bucket, job.get("quota_addon_id"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("[PHONE_JOB] refund falhou job=%s: %s", job.get("id"), exc)


async def process_one(job: dict[str, Any]) -> dict[str, Any]:
    """Executa um job. Devolve um resumo para logs/testes."""
    lead_id = int(job["lead_id"])
    lead = await db_service.get_lead_by_id(lead_id)
    if not lead:
        _finish(int(job["id"]), _STATUS_FAILED, "lead_not_found")
        _refund_quota(job)
        return {"ok": False, "reason": "lead_not_found"}

    decision = await phone_policy.decide(
        lead,
        owner=None,
        trigger=job.get("trigger") or "user_click",
        allow_resolve=False,
    )
    if decision.state == phone_policy.STATE_READY and decision.phone:
        _finish(int(job["id"]), _STATUS_DONE, "already_ready")
        return {"ok": True, "reason": "already_ready", "phone": decision.phone}

    if not decision.allow_paid_call:
        _finish(int(job["id"]), _STATUS_FAILED, decision.reason)
        _refund_quota(job)
        return {"ok": False, "reason": decision.reason}

    user_id = job.get("user_id")
    if user_id:
        attempt = await db_service.reserve_phone_attempt(int(user_id))
        if not attempt.get("ok"):
            _finish(int(job["id"]), _STATUS_FAILED, f"attempt_limit:{attempt.get('reason')}")
            _refund_quota(job)
            return {"ok": False, "reason": "attempt_limit"}

    last_error = "no_results"
    for candidate in decision.candidates:
        if bool(getattr(settings, "SEARCHBUG_MOCK", False)):
            # Staging/testes explicitos: numero deterministico e SEM selo.
            # Nunca corre em producao (SEARCHBUG_MOCK=0).
            from .searchbug import PhoneLookupResult

            result = PhoneLookupResult(
                success=True,
                phone=f"+1555{lead_id:07d}"[:12],
                provider="mock",
                verified=False,
                layer=candidate.layer,
            )
        else:
            result = await searchbug_service.lookup_phone(
                candidate.address,
                lead.get("city", ""),
                lead.get("state", ""),
                owner_name=candidate.owner_name,
                zip_code=lead.get("zip_code"),
                owner_class=get_owner_class(candidate.owner_name),
                lead_id=lead_id,
                trigger=job.get("trigger") or "user_click",
            )

        if result.success and result.phone:
            verified = phone_policy.verified_result(
                candidate, getattr(result, "verified", False), decision.owner
            )
            label = phone_policy.label_for(candidate, verified)
            phone_cache.put(
                cache_key=str(job["cache_key"]),
                lead_id=lead_id,
                owner_name=decision.owner_name,
                address=lead.get("address"),
                zip_code=lead.get("zip_code"),
                state=lead.get("state"),
                phone=result.phone,
                verified=verified,
                label=label,
                layer=getattr(result, "layer", candidate.layer) or candidate.layer,
                provider=getattr(result, "provider", "searchbug"),
                result_code="success",
            )
            await db_service.update_owner_phone(lead_id, result.phone, verified=verified)
            _persist_reveal(
                job, lead, phone=result.phone, verified=verified, label=label
            )
            _finish(int(job["id"]), _STATUS_DONE, None)
            return {
                "ok": True,
                "phone": result.phone,
                "verified": verified,
                "label": label,
                "candidate": candidate.kind,
            }

        last_error = getattr(result, "error", None) or "no_results"
        # `guard_skipped`/`name_mismatch`/`no_results` são ausências válidas;
        # não vale a pena gastar o fallback L3 no mesmo job.
        if last_error.startswith("guard_skipped"):
            break

    phone_cache.put(
        cache_key=str(job["cache_key"]),
        lead_id=lead_id,
        owner_name=decision.owner_name,
        address=lead.get("address"),
        zip_code=lead.get("zip_code"),
        state=lead.get("state"),
        phone=None,
        verified=False,
        label=None,
        layer=decision.candidates[0].layer if decision.candidates else None,
        provider="searchbug",
        result_code="no_results" if "no_results" in last_error.lower() else last_error,
    )

    # Ausencia definitiva nao se repete: pagar outra vez a mesma ausencia nao
    # a transforma num telefone. So' erros transitorios merecem retry.
    outcome = classify_searchbug_outcome(False, last_error)
    definitive = outcome in (
        "no_results", "name_mismatch", "guard_skipped", "invalid_request",
        "auth_error", "not_configured",
    )
    if not definitive and _retry_later(job, last_error):
        return {"ok": False, "reason": last_error, "retry": True}

    _finish(int(job["id"]), _STATUS_FAILED, last_error)
    _refund_quota(job)
    return {"ok": False, "reason": last_error, "retry": False}


async def worker_loop() -> None:
    """Loop de fundo. Nunca morre por uma excecao de um job."""
    logger.info("[PHONE_JOB] worker iniciado (poll=%ss)", POLL_SECONDS)
    while True:
        try:
            jobs = await asyncio.to_thread(claim_due, 5)
            for job in jobs:
                try:
                    summary = await process_one(job)
                    logger.info("[PHONE_JOB] job=%s %s", job.get("id"), summary)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("[PHONE_JOB] job=%s falhou: %s", job.get("id"), exc)
                    await asyncio.to_thread(_finish, int(job["id"]), _STATUS_FAILED, str(exc))
                    _refund_quota(job)
            await asyncio.sleep(POLL_SECONDS)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("[PHONE_JOB] loop: %s", exc)
            await asyncio.sleep(POLL_SECONDS)

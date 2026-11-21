"""Fase 3: reveals do modelo de subscrição semanal.

- Carta/visita: 10/dia, sem custo, owner + morada + mailing (quando existe).
- Telefone: quota diária do plano -> add-ons 24h -> Searchbug on-demand.
- Falha/no resultado: devolve a unidade ao bucket de origem.
Nunca usa créditos em cêntimos.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from . import billing_time, daily_quota, phone_jobs, phone_policy
from .db import db_service, get_connection

LETTER_PRICE_CENTS = 0
PHONE_PRICE_CENTS = 0


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _lead(conn, lead_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM leads WHERE id=?", (int(lead_id),)).fetchone()
    return dict(row) if row else None


def _prior_reveal(conn, user_id: int, lead_id: int, reveal_type: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM lead_reveals WHERE lead_id=? AND user_id=? AND reveal_type=? "
        "AND returned_to_pool=0 ORDER BY id DESC LIMIT 1",
        (int(lead_id), int(user_id), reveal_type),
    ).fetchone()
    if not row:
        return None
    data = dict(row)
    if data.get("payload_json"):
        try:
            data["payload"] = json.loads(data["payload_json"])
        except Exception:
            data["payload"] = None
    return data


def _insert_reveal(
    conn,
    user_id: int,
    lead_id: int,
    reveal_type: str,
    payload: dict[str, Any],
    idempotency_key: str,
    trade_code: str | None = None,
    searchbug_call_id: int | None = None,
) -> int:
    cur = conn.execute(
        "INSERT INTO lead_reveals "
        "(lead_id, user_id, revealed_date, idempotency_key, reveal_type, trade_code, "
        "credits_cents, payload_json, searchbug_call_id) "
        "VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)",
        (
            int(lead_id),
            int(user_id),
            billing_time.local_date(_now()),
            idempotency_key,
            reveal_type,
            trade_code,
            json.dumps(payload, ensure_ascii=False),
            searchbug_call_id,
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


async def reveal_letter(user_id: int, lead_id: int) -> dict[str, Any]:
    """Carta/visita livre, limitada a 10/dia. Idempotente por user/lead."""
    conn = get_connection()
    try:
        prior = _prior_reveal(conn, user_id, lead_id, "letter")
        lead = _lead(conn, lead_id)
        if not lead:
            raise daily_quota.QuotaError("lead_not_found", 404)
        if not int(lead.get("is_feed_ok") or 0):
            raise daily_quota.QuotaError("letter_not_eligible", 422)
        if not str(lead.get("owner_name") or "").strip():
            raise daily_quota.QuotaError("owner_missing", 422)
        if prior and prior.get("payload"):
            return {
                "duplicate": True,
                "payload": prior["payload"],
                "usage": daily_quota.usage_payload(user_id),
            }
        quota = daily_quota.consume_letter(user_id)
    finally:
        conn.close()

    payload = {
        "lead_id": int(lead_id),
        "type": "letter",
        "trade_code": str(lead.get("issue_category") or ""),
        "owner_name": lead.get("owner_name"),
        "address": lead.get("address"),
        "city": lead.get("city"),
        "state": lead.get("state"),
        "zip_code": lead.get("zip_code"),
        "mailing_address": lead.get("mailing_address"),
        "price_cents": LETTER_PRICE_CENTS,
    }
    conn = get_connection()
    try:
        try:
            reveal_id = _insert_reveal(
                conn,
                user_id,
                lead_id,
                "letter",
                payload,
                f"letter:{user_id}:{lead_id}:{uuid.uuid4().hex}",
                trade_code=str(lead.get("issue_category") or ""),
            )
        except Exception:
            daily_quota.refund_letter(user_id)
            raise
    finally:
        conn.close()
    return {
        "duplicate": False,
        "reveal_id": reveal_id,
        "payload": payload,
        "quota": quota,
        "usage": daily_quota.usage_payload(user_id),
    }


def _mock_phone(lead_id: int) -> str:
    tail = (int(lead_id) * 37) % 10000
    return f"+1 212 555 {tail:04d}"


async def reveal_phone(
    user_id: int,
    lead_id: int,
    idempotency_key: str,
    trade_code: str | None = None,
    owner=None,
) -> dict[str, Any]:
    """Le o telefone da cache; em cache fria enfileira e devolve `in_progress`.

    NUNCA chama a Searchbug dentro do pedido HTTP (AGENTS #5). A chamada paga
    acontece no worker (`phone_jobs`), fora do clique. A cota e' consumida
    apenas quando ha entrega ou quando o job e' aceite; se o job falhar em
    definitivo, o worker devolve a unidade.
    """
    if not str(idempotency_key or "").strip():
        raise daily_quota.QuotaError("idempotency_key_required", 422)
    conn = get_connection()
    try:
        prior = _prior_reveal(conn, user_id, lead_id, "phone")
        lead = _lead(conn, lead_id)
        if not lead:
            raise daily_quota.QuotaError("lead_not_found", 404)
        if not (
            int(lead.get("phone_eligible") or 0)
            or int(lead.get("phone_ready") or 0)
            or str(lead.get("owner_phone") or "").strip()
        ):
            raise daily_quota.QuotaError("phone_not_eligible", 422)
        if not str(lead.get("owner_name") or "").strip():
            raise daily_quota.QuotaError("owner_missing", 422)
        if not str(lead.get("address") or "").strip():
            raise daily_quota.QuotaError("address_missing", 422)
        if prior and prior.get("payload"):
            return {
                "success": True,
                "state": "ready",
                "duplicate": True,
                "payload": prior["payload"],
                "usage": daily_quota.usage_payload(user_id),
            }
    finally:
        conn.close()

    # O chamador ja' resolveu o dono (ou a proveniencia esta' no lead). Nao se
    # repete a consulta publica dentro do clique.
    decision = await phone_policy.decide(
        lead, owner=owner, trigger="user_click", allow_resolve=False
    )
    usage = daily_quota.usage_payload(user_id)

    # 1) Telefone disponivel (lead ou cache): entrega imediata.
    if decision.state == phone_policy.STATE_READY and decision.phone:
        quota = daily_quota.consume_phone(user_id)
        phone = decision.phone
        verified = bool(decision.verified)
        label = decision.label
        if not str(lead.get("owner_phone") or "").strip():
            await db_service.update_owner_phone(lead_id, phone, verified=verified)
        payload = {
            "lead_id": int(lead_id),
            "type": "phone",
            "trade_code": trade_code or str(lead.get("issue_category") or ""),
            "phone": phone,
            "verified": verified,
            "label": label,
            "owner_name": decision.owner_name or lead.get("owner_name"),
            "address": lead.get("address"),
            "city": lead.get("city"),
            "state": lead.get("state"),
            "zip_code": lead.get("zip_code"),
            "price_cents": PHONE_PRICE_CENTS,
        }
        conn = get_connection()
        try:
            try:
                reveal_id = _insert_reveal(
                    conn,
                    user_id,
                    lead_id,
                    "phone",
                    payload,
                    idempotency_key,
                    trade_code=trade_code or str(lead.get("issue_category") or ""),
                )
            except Exception:
                daily_quota.refund_phone(
                    user_id, quota["bucket"], quota.get("addon_id")
                )
                raise
        finally:
            conn.close()
        return {
            "success": True,
            "state": "ready",
            "duplicate": False,
            "reveal_id": reveal_id,
            "payload": payload,
            "provider": "cache",
            "verified": verified,
            "label": label,
            "quota": quota,
            "usage": daily_quota.usage_payload(user_id),
        }

    # 2) Cache fria mas politica autoriza: enfileira (single-flight).
    if decision.state == phone_policy.STATE_IN_PROGRESS:
        existing = phone_jobs.get_by_cache_key(decision.cache_key)
        if existing and existing.get("status") in ("pending", "running"):
            # Segundo clique enquanto o primeiro job corre: nao cobra outra vez.
            return {
                "success": True,
                "state": "in_progress",
                "error": "phone_in_progress",
                "message": "Estamos a confirmar o proprietário. Avisamos quando estiver pronto.",
                "payload": None,
                "quota": None,
                "usage": usage,
            }

        if not await db_service.phone_attempt_budget_ok(user_id):
            return {
                "success": False,
                "state": "no_phone",
                "error": "attempt_limit",
                "message": "Limite de consultas atingido. Tenta novamente mais tarde.",
                "quota_preserved": True,
                "payload": None,
                "quota": None,
                "usage": usage,
            }

        quota = daily_quota.consume_phone(user_id)
        try:
            phone_jobs.enqueue(
                cache_key=decision.cache_key,
                lead_id=int(lead_id),
                user_id=user_id,
                idempotency_key=idempotency_key,
                trigger="user_click",
                decision=decision,
                quota_ref=quota,
            )
        except Exception:
            daily_quota.refund_phone(
                user_id, quota["bucket"], quota.get("addon_id")
            )
            raise
        return {
            "success": True,
            "state": "in_progress",
            "error": "phone_in_progress",
            "message": "Estamos a confirmar o proprietário. Avisamos quando estiver pronto.",
            "payload": None,
            "quota": quota,
            "usage": daily_quota.usage_payload(user_id),
        }

    # 3) Sem dono confiavel / registo velho / entidade desligada: nao paga.
    return {
        "success": False,
        "state": "no_phone",
        "error": decision.reason,
        "message": "Sem telefone confirmado para este imóvel — a sua cota diária foi preservada.",
        "quota_preserved": True,
        "payload": None,
        "quota": None,
        "usage": usage,
    }

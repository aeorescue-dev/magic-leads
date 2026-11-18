"""Fase 3: quotas diárias e add-ons de 24h.

- Base diária: `users.daily_phone_limit` / `users.daily_letter_limit`.
- Contadores independentes em `user_daily_usage` (data local America/New_York).
- Telefones consomem base primeiro e depois add-ons ativos (mais antigo primeiro).
- Falha da Searchbug devolve a unidade ao bucket de origem.
- Add-ons duram 24h corridas e não alteram o plano semanal.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from . import billing_time, plans
from .db import get_connection


class QuotaError(Exception):
    def __init__(self, code: str, status_code: int = 429, detail: str = ""):
        super().__init__(detail or code)
        self.code = code
        self.status_code = status_code
        self.detail = detail or code


def _now(now: datetime | None = None) -> datetime:
    value = now or datetime.now(timezone.utc)
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _user_limits(conn, user_id: int) -> tuple[int, int, str]:
    row = conn.execute(
        "SELECT plan, daily_phone_limit, daily_letter_limit FROM users WHERE id=?",
        (int(user_id),),
    ).fetchone()
    if not row:
        raise QuotaError("user_not_found", 404)
    phone_limit = int(row["daily_phone_limit"] or 0)
    letter_limit = int(row["daily_letter_limit"] or 0)
    plan_code = str(row["plan"] or "")
    plan = plans.get_plan(plan_code)
    if plan:
        phone_limit = phone_limit or int(plan["daily_phone_limit"])
        letter_limit = letter_limit or int(plan["daily_letter_limit"])
    elif plan_code not in ("", "free"):
        # Contas legacy ainda ativas (ex.: pro) mantêm o teto antigo de 10/dia
        # até serem migradas para um dos 7 planos semanais.
        phone_limit = phone_limit or 10
        letter_limit = letter_limit or 10
    return phone_limit, letter_limit, plan_code


def _ensure_usage(conn, user_id: int, now: datetime) -> dict[str, Any]:
    today = billing_time.local_date(now)
    reset_at = billing_time.next_reset_utc(now)
    phone_limit, letter_limit, _plan = _user_limits(conn, user_id)
    conn.execute(
        """
        INSERT OR IGNORE INTO user_daily_usage
          (user_id, date, phone_used, phone_limit, letter_used, letter_limit, reset_at)
        VALUES (?, ?, 0, ?, 0, ?, ?)
        """,
        (int(user_id), today, phone_limit, letter_limit, reset_at),
    )
    conn.execute(
        """
        UPDATE user_daily_usage
           SET phone_limit=?, letter_limit=?, reset_at=?
         WHERE user_id=? AND date=?
        """,
        (phone_limit, letter_limit, reset_at, int(user_id), today),
    )
    return {
        "date": today,
        "phone_limit": phone_limit,
        "letter_limit": letter_limit,
        "reset_at": reset_at,
    }


def _addon_summary(conn, user_id: int, now: datetime) -> dict[str, Any]:
    now_iso = now.isoformat()
    row = conn.execute(
        """
        SELECT COALESCE(SUM(phone_count - used_count), 0) AS remaining,
               MIN(expires_at) AS nearest
          FROM phone_addons
         WHERE user_id=? AND status='active'
           AND datetime(expires_at) > datetime(?)
           AND used_count < phone_count
        """,
        (int(user_id), now_iso),
    ).fetchone()
    return {
        "addon_remaining": int(row["remaining"] or 0),
        "addon_expires_at": row["nearest"],
    }


def usage_payload(user_id: int, now: datetime | None = None) -> dict[str, Any]:
    moment = _now(now)
    conn = get_connection()
    try:
        base = _ensure_usage(conn, user_id, moment)
        row = conn.execute(
            "SELECT * FROM user_daily_usage WHERE user_id=? AND date=?",
            (int(user_id), base["date"]),
        ).fetchone()
        addon = _addon_summary(conn, user_id, moment)
        phone_limit = int(row["phone_limit"] or 0)
        phone_used = int(row["phone_used"] or 0)
        letter_limit = int(row["letter_limit"] or 0)
        letter_used = int(row["letter_used"] or 0)
        return {
            "date": base["date"],
            "plan": _user_limits(conn, user_id)[2],
            "phone_limit": phone_limit,
            "phone_used": phone_used,
            "phone_remaining": max(0, phone_limit - phone_used) + addon["addon_remaining"],
            "letter_limit": letter_limit,
            "letter_used": letter_used,
            "letter_remaining": max(0, letter_limit - letter_used),
            "reset_at": row["reset_at"] or base["reset_at"],
            **addon,
        }
    finally:
        conn.close()


def consume_letter(user_id: int, now: datetime | None = None) -> dict[str, Any]:
    moment = _now(now)
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        base = _ensure_usage(conn, user_id, moment)
        cur = conn.execute(
            """
            UPDATE user_daily_usage
               SET letter_used = letter_used + 1
             WHERE user_id=? AND date=? AND letter_used < letter_limit
            """,
            (int(user_id), base["date"]),
        )
        if cur.rowcount <= 0:
            conn.rollback()
            raise QuotaError(
                "letter_quota_exhausted",
                429,
                "Limite diário de 10 cartas/visitas atingido.",
            )
        conn.commit()
        row = conn.execute(
            "SELECT letter_used, letter_limit, reset_at FROM user_daily_usage "
            "WHERE user_id=? AND date=?",
            (int(user_id), base["date"]),
        ).fetchone()
        return {
            "bucket": "letter",
            "used": int(row["letter_used"] or 0),
            "limit": int(row["letter_limit"] or 0),
            "reset_at": row["reset_at"],
        }
    except QuotaError:
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def consume_phone(user_id: int, now: datetime | None = None) -> dict[str, Any]:
    """Consome 1 telefone: base primeiro, depois add-on mais antigo."""
    moment = _now(now)
    now_iso = moment.isoformat()
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        base = _ensure_usage(conn, user_id, moment)
        cur = conn.execute(
            """
            UPDATE user_daily_usage
               SET phone_used = phone_used + 1
             WHERE user_id=? AND date=? AND phone_used < phone_limit
            """,
            (int(user_id), base["date"]),
        )
        if cur.rowcount > 0:
            conn.commit()
            row = conn.execute(
                "SELECT phone_used, phone_limit, reset_at FROM user_daily_usage "
                "WHERE user_id=? AND date=?",
                (int(user_id), base["date"]),
            ).fetchone()
            return {
                "bucket": "base",
                "addon_id": None,
                "used": int(row["phone_used"] or 0),
                "limit": int(row["phone_limit"] or 0),
                "reset_at": row["reset_at"],
            }

        addon = conn.execute(
            """
            SELECT id, phone_count, used_count, expires_at
              FROM phone_addons
             WHERE user_id=? AND status='active'
               AND datetime(expires_at) > datetime(?)
               AND used_count < phone_count
             ORDER BY datetime(expires_at) ASC, id ASC
             LIMIT 1
            """,
            (int(user_id), now_iso),
        ).fetchone()
        if addon:
            updated = conn.execute(
                "UPDATE phone_addons SET used_count = used_count + 1 "
                "WHERE id=? AND used_count < phone_count",
                (int(addon["id"]),),
            )
            if updated.rowcount > 0:
                conn.commit()
                return {
                    "bucket": "addon",
                    "addon_id": int(addon["id"]),
                    "used": int(addon["used_count"] or 0) + 1,
                    "limit": int(addon["phone_count"] or 0),
                    "expires_at": addon["expires_at"],
                    "reset_at": base["reset_at"],
                }
        conn.rollback()
        raise QuotaError("phone_quota_exhausted", 429, "Cota diária de telefones esgotada.")
    except QuotaError:
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def refund_phone(
    user_id: int,
    bucket: str,
    addon_id: int | None = None,
    now: datetime | None = None,
) -> None:
    moment = _now(now)
    conn = get_connection()
    try:
        if bucket == "addon" and addon_id:
            conn.execute(
                "UPDATE phone_addons SET used_count = MAX(0, used_count - 1) WHERE id=?",
                (int(addon_id),),
            )
        else:
            today = billing_time.local_date(moment)
            conn.execute(
                "UPDATE user_daily_usage SET phone_used = MAX(0, phone_used - 1) "
                "WHERE user_id=? AND date=?",
                (int(user_id), today),
            )
        conn.commit()
    finally:
        conn.close()


def refund_letter(user_id: int, now: datetime | None = None) -> None:
    moment = _now(now)
    today = billing_time.local_date(moment)
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE user_daily_usage SET letter_used = MAX(0, letter_used - 1) "
            "WHERE user_id=? AND date=?",
            (int(user_id), today),
        )
        conn.commit()
    finally:
        conn.close()


def add_addon(
    user_id: int,
    pack_code: str,
    *,
    stripe_session_id: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    pack = plans.get_addon(pack_code)
    if not pack:
        raise QuotaError("unknown_addon", 400)
    moment = _now(now)
    session_id = (stripe_session_id or "").strip() or f"mock:{user_id}:{uuid.uuid4().hex}"
    expires_at = (moment + timedelta(hours=24)).isoformat()
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO phone_addons
              (user_id, pack_code, phone_count, used_count, price_cents,
               stripe_session_id, purchased_at, expires_at, status)
            VALUES (?, ?, ?, 0, ?, ?, ?, ?, 'active')
            """,
            (
                int(user_id),
                str(pack["code"]),
                int(pack["phone_count"]),
                int(pack["price_cents"]),
                session_id,
                moment.isoformat(),
                expires_at,
            ),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM phone_addons WHERE stripe_session_id=?", (session_id,)
        ).fetchone()
        return dict(row) if row else {}
    finally:
        conn.close()


def expire_addons(now: datetime | None = None) -> int:
    moment = _now(now)
    conn = get_connection()
    try:
        cur = conn.execute(
            "UPDATE phone_addons SET status='expired' "
            "WHERE status='active' AND datetime(expires_at) <= datetime(?)",
            (moment.isoformat(),),
        )
        conn.commit()
        return int(cur.rowcount or 0)
    finally:
        conn.close()

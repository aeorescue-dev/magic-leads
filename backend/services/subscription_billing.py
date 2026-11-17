"""Fase 2: assinatura semanal Stripe, checkout e webhooks.

Este módulo NÃO altera a UI. Expõe:
- mapeamento `stripe_price_id -> plano -> limites diários`;
- checkout `mode=subscription` por `plan_code`;
- aplicação idempotente dos eventos de subscrição;
- ativação mock para QA (`BILLING_MOCK=1`).

Nunca cria `legacy_pro`: só existem os 7 planos do catálogo.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import stripe

from ..config import settings
from . import daily_quota, plans
from .db import get_connection

logger = logging.getLogger(__name__)

WEEKLY_SUBSCRIPTION_KIND = "weekly_subscription"
PHONE_ADDON_KIND = "phone_addon"

_ACTIVE_STRIPE_STATUSES = {"active", "trialing"}
_PAST_DUE_STRIPE_STATUSES = {"past_due", "unpaid", "incomplete", "incomplete_expired"}


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _from_unix(ts: Any) -> str | None:
    try:
        value = int(ts)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    return _iso(datetime.fromtimestamp(value, tz=timezone.utc))


def _now_plus_week() -> str:
    return _iso(datetime.now(timezone.utc) + timedelta(days=7))


def _db_plan_row(code: str) -> Optional[dict[str, Any]]:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM subscription_plans WHERE code=? AND active=1", (code,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def plan_for_price_id(price_id: str) -> Optional[dict[str, Any]]:
    """Mapeia Price ID Stripe -> plano (BD primeiro; env como fallback)."""
    price_id = str(price_id or "").strip()
    if not price_id:
        return None
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM subscription_plans WHERE stripe_price_id=? AND active=1",
            (price_id,),
        ).fetchone()
        if row:
            return dict(row)
    finally:
        conn.close()
    for plan in plans.list_plans():
        if plans.stripe_price_id_for(plan) == price_id:
            return _db_plan_row(plan["code"]) or dict(plan)
    return None


def plan_for_code(plan_code: str) -> Optional[dict[str, Any]]:
    return _db_plan_row(str(plan_code or "").strip())


def _user_id_for_customer_or_subscription(
    customer_id: str | None, subscription_id: str | None
) -> Optional[int]:
    conn = get_connection()
    try:
        if subscription_id:
            row = conn.execute(
                "SELECT id FROM users WHERE stripe_subscription_id=?",
                (subscription_id,),
            ).fetchone()
            if row:
                return int(row["id"])
        if customer_id:
            row = conn.execute(
                "SELECT id FROM users WHERE stripe_customer_id=?",
                (customer_id,),
            ).fetchone()
            if row:
                return int(row["id"])
    finally:
        conn.close()
    return None


def _status_from_stripe(stripe_status: str) -> str:
    status = str(stripe_status or "").lower()
    if status in _ACTIVE_STRIPE_STATUSES:
        return "active"
    if status in _PAST_DUE_STRIPE_STATUSES:
        return "past_due"
    return "expired"


def activate_weekly_subscription(
    user_id: int,
    plan_code: str,
    *,
    plan_until: str | None = None,
    status: str = "active",
    subscription_id: str | None = None,
    customer_id: str | None = None,
) -> dict[str, Any]:
    """Aplica plano + limites ao utilizador. Fonte de verdade no catálogo."""
    plan = plan_for_code(plan_code)
    if not plan:
        raise ValueError(f"unknown_plan:{plan_code}")
    effective_until = plan_until or _now_plus_week()
    conn = get_connection()
    try:
        conn.execute(
            """
            UPDATE users SET
              plan=?,
              subscription_status=?,
              plan_until=?,
              daily_phone_limit=?,
              daily_letter_limit=?,
              stripe_subscription_id=COALESCE(?, stripe_subscription_id),
              stripe_customer_id=COALESCE(?, stripe_customer_id)
            WHERE id=?
            """,
            (
                plan["code"],
                status,
                effective_until,
                int(plan["daily_phone_limit"]),
                int(plan["daily_letter_limit"]),
                subscription_id,
                customer_id,
                int(user_id),
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return {
        "user_id": int(user_id),
        "plan": plan["code"],
        "name": plan["name"],
        "status": status,
        "plan_until": effective_until,
        "daily_phone_limit": int(plan["daily_phone_limit"]),
        "daily_letter_limit": int(plan["daily_letter_limit"]),
    }


def set_subscription_status(user_id: int, status: str) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE users SET subscription_status=? WHERE id=?",
            (status, int(user_id)),
        )
        conn.commit()
    finally:
        conn.close()


def create_weekly_checkout(
    user_id: int,
    plan_code: str,
    *,
    locale: str = "en",
    email: str | None = None,
) -> dict[str, Any]:
    """Cria Checkout de subscrição semanal. Em mock, devolve mock=True."""
    plan = plan_for_code(plan_code)
    if not plan:
        raise ValueError("unknown_plan")
    lang = locale if locale in ("pt", "en", "es") else "en"
    price_id = str(plan.get("stripe_price_id") or "").strip() or plans.stripe_price_id_for(plan)
    stripe_key = str(getattr(settings, "STRIPE_API_KEY", "") or "").strip()
    if getattr(settings, "BILLING_MOCK", False) or not stripe_key or not price_id:
        return {
            "mock": True,
            "plan_code": plan["code"],
            "plan": plan,
            "checkout_url": None,
            "message": "Staging: use /api/billing/mock-activate para ativar o plano.",
        }

    stripe.api_key = stripe_key
    frontend = (getattr(settings, "FRONTEND_URL", "") or "https://www.magicleads.app").rstrip("/")
    success_url = f"{frontend}/{lang}/dashboard?billing=success&session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = f"{frontend}/{lang}/dashboard?billing=cancel"

    try:
        open_sessions = stripe.checkout.Session.list(
            client_reference_id=str(user_id), status="open", limit=5
        ).data
        for session in open_sessions:
            try:
                stripe.checkout.Session.expire(session.id)
            except Exception:
                pass
    except Exception as exc:
        logger.warning("[BILLING] não foi possível limpar sessões abertas: %s", exc)

    metadata = {
        "kind": WEEKLY_SUBSCRIPTION_KIND,
        "user_id": str(user_id),
        "plan_code": plan["code"],
        "daily_phone_limit": str(plan["daily_phone_limit"]),
        "daily_letter_limit": str(plan["daily_letter_limit"]),
    }
    session = stripe.checkout.Session.create(
        mode="subscription",
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=success_url,
        cancel_url=cancel_url,
        client_reference_id=str(user_id),
        customer_email=(email or "").strip().lower() or None,
        locale=lang,
        metadata=metadata,
        subscription_data={"metadata": metadata},
    )
    try:
        conn = get_connection()
        try:
            conn.execute(
                "INSERT OR IGNORE INTO checkout_sessions "
                "(user_id, session_id, email, amount_cents, currency, status, url) "
                "VALUES (?, ?, ?, ?, 'usd', 'open', ?)",
                (
                    int(user_id),
                    session.id,
                    (email or "").strip().lower() or None,
                    int(plan["price_cents"]),
                    session.url,
                ),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:
        logger.warning("[BILLING] falha ao registar checkout: %s", exc)
    return {
        "mock": False,
        "plan_code": plan["code"],
        "plan": plan,
        "checkout_url": session.url,
        "session_id": session.id,
    }


def create_addon_checkout(
    user_id: int,
    pack_code: str,
    *,
    locale: str = "en",
    email: str | None = None,
) -> dict[str, Any]:
    """Checkout one-time de add-on de telefones (24h)."""
    pack = plans.get_addon(pack_code)
    if not pack:
        raise ValueError("unknown_addon")
    lang = locale if locale in ("pt", "en", "es") else "en"
    stripe_key = str(getattr(settings, "STRIPE_API_KEY", "") or "").strip()
    if getattr(settings, "ADDONS_MOCK", False) or not stripe_key:
        return {
            "mock": True,
            "pack_code": pack["code"],
            "pack": pack,
            "checkout_url": None,
            "message": "Staging: add-on mock. Usa o script interno para injetar unidades.",
        }
    stripe.api_key = stripe_key
    frontend = (getattr(settings, "FRONTEND_URL", "") or "https://www.magicleads.app").rstrip("/")
    success_url = f"{frontend}/{lang}/dashboard?addon=success&session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = f"{frontend}/{lang}/dashboard?addon=cancel"
    metadata = {
        "kind": PHONE_ADDON_KIND,
        "user_id": str(user_id),
        "pack_code": pack["code"],
        "phone_count": str(pack["phone_count"]),
    }
    session = stripe.checkout.Session.create(
        mode="payment",
        line_items=[{
            "price_data": {
                "currency": "usd",
                "unit_amount": int(pack["price_cents"]),
                "product_data": {
                    "name": f"Magic Leads — +{pack['phone_count']} telefones (24h)",
                },
            },
            "quantity": 1,
        }],
        success_url=success_url,
        cancel_url=cancel_url,
        client_reference_id=str(user_id),
        customer_email=(email or "").strip().lower() or None,
        locale=lang,
        metadata=metadata,
    )
    try:
        conn = get_connection()
        try:
            conn.execute(
                "INSERT OR IGNORE INTO checkout_sessions "
                "(user_id, session_id, email, amount_cents, currency, status, url) "
                "VALUES (?, ?, ?, ?, 'usd', 'open', ?)",
                (
                    int(user_id),
                    session.id,
                    (email or "").strip().lower() or None,
                    int(pack["price_cents"]),
                    session.url,
                ),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:
        logger.warning("[BILLING] falha ao registar add-on checkout: %s", exc)
    return {
        "mock": False,
        "pack_code": pack["code"],
        "pack": pack,
        "checkout_url": session.url,
        "session_id": session.id,
    }


def _record_event(event_id: str, event_type: str, user_id: int | None) -> bool:
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT OR IGNORE INTO stripe_events (event_id, event_type, user_id, granted) "
            "VALUES (?, ?, ?, 0)",
            (event_id, event_type, user_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def _event_state(event_id: str) -> dict[str, Any] | None:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM stripe_events WHERE event_id=?", (event_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _mark_event_granted(event_id: str) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE stripe_events SET granted=1 WHERE event_id=?", (event_id,)
        )
        conn.commit()
    finally:
        conn.close()


def _apply_from_subscription(sub: dict[str, Any], fallback_plan: str | None = None) -> dict[str, Any]:
    meta = sub.get("metadata") or {}
    items = ((sub.get("items") or {}).get("data") or [])
    price_id = ""
    if items:
        price_id = str(((items[0] or {}).get("price") or {}).get("id") or "")
    plan = plan_for_price_id(price_id) if price_id else None
    if not plan and meta.get("plan_code"):
        plan = plan_for_code(str(meta["plan_code"]))
    if not plan and fallback_plan:
        plan = plan_for_code(fallback_plan)
    if not plan:
        raise ValueError("plan_not_found")
    user_id_raw = meta.get("user_id")
    try:
        user_id = int(user_id_raw) if user_id_raw else None
    except (TypeError, ValueError):
        user_id = None
    if not user_id:
        user_id = _user_id_for_customer_or_subscription(
            str(sub.get("customer") or ""), str(sub.get("id") or "")
        )
    if not user_id:
        raise ValueError("user_not_found")
    stripe_status = str(sub.get("status") or "").lower()
    status = _status_from_stripe(stripe_status)
    return activate_weekly_subscription(
        user_id,
        plan["code"],
        plan_until=_from_unix(sub.get("current_period_end")) or _now_plus_week(),
        status=status,
        subscription_id=str(sub.get("id") or "") or None,
        customer_id=str(sub.get("customer") or "") or None,
    )


def handle_billing_event(event: dict[str, Any]) -> dict[str, Any]:
    """Aplica um evento Stripe de subscrição de forma idempotente."""
    event_id = str(event.get("id") or "").strip()
    event_type = str(event.get("type") or "").strip()
    if not event_id:
        raise ValueError("event_without_id")
    existing = _event_state(event_id)
    if existing and int(existing.get("granted") or 0) == 1:
        return {"status": "received", "duplicate": True}
    if not existing:
        _record_event(event_id, event_type, None)

    obj = ((event.get("data") or {}).get("object") or {})
    try:
        if event_type == "checkout.session.completed":
            meta = obj.get("metadata") or {}
            if meta.get("kind") == PHONE_ADDON_KIND:
                pack_code = str(meta.get("pack_code") or "")
                pack = plans.get_addon(pack_code)
                if not pack:
                    raise ValueError("unknown_addon")
                try:
                    user_id = int(meta.get("user_id") or obj.get("client_reference_id") or 0)
                except (TypeError, ValueError):
                    user_id = 0
                if not user_id:
                    raise ValueError("user_not_found")
                addon = daily_quota.add_addon(
                    user_id,
                    pack_code,
                    stripe_session_id=str(obj.get("id") or "") or None,
                )
                _mark_event_granted(event_id)
                return {"status": "received", "handled": True, "addon": addon}
            if meta.get("kind") != WEEKLY_SUBSCRIPTION_KIND:
                _mark_event_granted(event_id)
                return {"status": "ignored", "reason": "not_weekly_subscription"}
            plan_code = str(meta.get("plan_code") or "")
            sub_id = str(obj.get("subscription") or "")
            customer_id = str(obj.get("customer") or "")
            period_end = _now_plus_week()
            stripe_status = "active"
            if sub_id and getattr(settings, "STRIPE_API_KEY", ""):
                try:
                    stripe.api_key = settings.STRIPE_API_KEY
                    sub = stripe.Subscription.retrieve(sub_id)
                    period_end = _from_unix(sub.get("current_period_end")) or period_end
                    stripe_status = str(sub.get("status") or "active")
                except Exception as exc:
                    logger.warning("[BILLING] retrieve subscription falhou: %s", exc)
            try:
                user_id = int(meta.get("user_id") or obj.get("client_reference_id") or 0)
            except (TypeError, ValueError):
                user_id = 0
            if not user_id:
                raise ValueError("user_not_found")
            activate_weekly_subscription(
                user_id,
                plan_code,
                plan_until=period_end,
                status=_status_from_stripe(stripe_status),
                subscription_id=sub_id or None,
                customer_id=customer_id or None,
            )
        elif event_type in (
            "customer.subscription.created",
            "customer.subscription.updated",
        ):
            _apply_from_subscription(obj)
        elif event_type == "invoice.paid":
            sub_id = str(obj.get("subscription") or "")
            user_id = _user_id_for_customer_or_subscription(
                str(obj.get("customer") or ""), sub_id
            )
            if not user_id:
                raise ValueError("user_not_found")
            conn = get_connection()
            try:
                row = conn.execute(
                    "SELECT plan FROM users WHERE id=?", (int(user_id),)
                ).fetchone()
            finally:
                conn.close()
            plan_code = str((dict(row) if row else {}).get("plan") or "")
            if not plan_code:
                raise ValueError("plan_not_found")
            activate_weekly_subscription(
                int(user_id),
                plan_code,
                plan_until=_from_unix(obj.get("period_end")) or _now_plus_week(),
                status="active",
                subscription_id=sub_id or None,
                customer_id=str(obj.get("customer") or "") or None,
            )
        elif event_type == "invoice.payment_failed":
            user_id = _user_id_for_customer_or_subscription(
                str(obj.get("customer") or ""), str(obj.get("subscription") or "")
            )
            if user_id:
                set_subscription_status(int(user_id), "past_due")
        elif event_type == "customer.subscription.deleted":
            user_id = _user_id_for_customer_or_subscription(
                str(obj.get("customer") or ""), str(obj.get("id") or "")
            )
            if user_id:
                set_subscription_status(int(user_id), "expired")
        else:
            _mark_event_granted(event_id)
            return {"status": "ignored", "reason": f"unhandled:{event_type}"}
    except Exception:
        # `granted` fica 0: o retry do Stripe volta a tentar.
        raise
    _mark_event_granted(event_id)
    return {"status": "received", "handled": True}

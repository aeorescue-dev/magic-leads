"""Fase 2: mapeamento Stripe, checkout mock e webhooks de subscrição."""
from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from backend.main import app
from backend.services import subscription_billing
from backend.services.db import DB_PATH, db_service  # noqa: F401
from backend.services.security import hash_password


def _conn():
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def _user(email: str) -> int:
    conn = _conn()
    try:
        cur = conn.execute(
            "INSERT INTO users (email, password_hash, company_name, plan, subscription_status) "
            "VALUES (?, ?, 'Billing QA', 'free', 'expired')",
            (email, hash_password("test-pass-123")),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def _cleanup(email: str, events: list[str]) -> None:
    conn = _conn()
    try:
        conn.execute("DELETE FROM users WHERE email=?", (email,))
        for event_id in events:
            conn.execute("DELETE FROM stripe_events WHERE event_id=?", (event_id,))
        conn.commit()
    finally:
        conn.close()


def test_activate_weekly_subscription_maps_limits() -> None:
    suffix = uuid.uuid4().hex[:8]
    email = f"billing-a-{suffix}@magic.test"
    uid = _user(email)
    try:
        result = subscription_billing.activate_weekly_subscription(
            uid, "weekly_6", plan_until="2030-01-01T00:00:00+00:00"
        )
        assert result["plan"] == "weekly_6"
        assert result["daily_phone_limit"] == 6
        assert result["daily_letter_limit"] == 10
        row = _conn().execute(
            "SELECT plan, daily_phone_limit, daily_letter_limit, subscription_status, plan_until "
            "FROM users WHERE id=?",
            (uid,),
        ).fetchone()
        assert row["plan"] == "weekly_6"
        assert row["daily_phone_limit"] == 6
        assert row["daily_letter_limit"] == 10
        assert row["subscription_status"] == "active"
        assert row["plan_until"] == "2030-01-01T00:00:00+00:00"
    finally:
        _cleanup(email, [])


def test_price_id_mapping() -> None:
    conn = _conn()
    try:
        original = conn.execute(
            "SELECT stripe_price_id FROM subscription_plans WHERE code='weekly_6'"
        ).fetchone()["stripe_price_id"]
        conn.execute(
            "UPDATE subscription_plans SET stripe_price_id='price_test_weekly_6' WHERE code='weekly_6'"
        )
        conn.commit()
        plan = subscription_billing.plan_for_price_id("price_test_weekly_6")
        assert plan is not None
        assert plan["code"] == "weekly_6"
        assert plan["daily_phone_limit"] == 6
        assert plan["daily_letter_limit"] == 10
    finally:
        conn.execute(
            "UPDATE subscription_plans SET stripe_price_id=? WHERE code='weekly_6'",
            (original,),
        )
        conn.commit()
        conn.close()


def test_checkout_mock_without_stripe_key() -> None:
    suffix = uuid.uuid4().hex[:8]
    email = f"billing-c-{suffix}@magic.test"
    uid = _user(email)
    try:
        result = subscription_billing.create_weekly_checkout(
            uid, "weekly_4", locale="pt"
        )
        assert result["mock"] is True
        assert result["plan_code"] == "weekly_4"
        assert result["checkout_url"] is None
    finally:
        _cleanup(email, [])


def test_subscription_webhook_lifecycle_and_idempotency() -> None:
    suffix = uuid.uuid4().hex[:8]
    email = f"billing-w-{suffix}@magic.test"
    uid = _user(email)
    event_ids = [f"evt_created_{suffix}", f"evt_failed_{suffix}", f"evt_deleted_{suffix}"]
    conn = _conn()
    try:
        original_price = conn.execute(
            "SELECT stripe_price_id FROM subscription_plans WHERE code='weekly_6'"
        ).fetchone()["stripe_price_id"]
        conn.execute(
            "UPDATE subscription_plans SET stripe_price_id='price_test_weekly_6' WHERE code='weekly_6'"
        )
        conn.commit()
    finally:
        conn.close()

    try:
        period_end = int(
            (datetime.now(timezone.utc) + timedelta(days=7)).timestamp()
        )
        created = {
            "id": event_ids[0],
            "type": "customer.subscription.created",
            "data": {
                "object": {
                    "id": f"sub_{suffix}",
                    "customer": f"cus_{suffix}",
                    "status": "active",
                    "current_period_end": period_end,
                    "metadata": {"user_id": str(uid), "plan_code": "weekly_6"},
                    "items": {
                        "data": [{"price": {"id": "price_test_weekly_6"}}]
                    },
                }
            },
        }
        first = subscription_billing.handle_billing_event(created)
        assert first["handled"] is True
        row = _conn().execute(
            "SELECT plan, daily_phone_limit, daily_letter_limit, subscription_status, "
            "stripe_subscription_id, stripe_customer_id FROM users WHERE id=?",
            (uid,),
        ).fetchone()
        assert row["plan"] == "weekly_6"
        assert row["daily_phone_limit"] == 6
        assert row["daily_letter_limit"] == 10
        assert row["subscription_status"] == "active"
        assert row["stripe_subscription_id"] == f"sub_{suffix}"
        assert row["stripe_customer_id"] == f"cus_{suffix}"

        duplicate = subscription_billing.handle_billing_event(created)
        assert duplicate["duplicate"] is True

        failed = {
            "id": event_ids[1],
            "type": "invoice.payment_failed",
            "data": {
                "object": {
                    "customer": f"cus_{suffix}",
                    "subscription": f"sub_{suffix}",
                }
            },
        }
        subscription_billing.handle_billing_event(failed)
        row = _conn().execute(
            "SELECT subscription_status FROM users WHERE id=?", (uid,)
        ).fetchone()
        assert row["subscription_status"] == "past_due"

        deleted = {
            "id": event_ids[2],
            "type": "customer.subscription.deleted",
            "data": {
                "object": {
                    "id": f"sub_{suffix}",
                    "customer": f"cus_{suffix}",
                }
            },
        }
        subscription_billing.handle_billing_event(deleted)
        row = _conn().execute(
            "SELECT subscription_status FROM users WHERE id=?", (uid,)
        ).fetchone()
        assert row["subscription_status"] == "expired"
    finally:
        conn = _conn()
        try:
            conn.execute(
                "UPDATE subscription_plans SET stripe_price_id=? WHERE code='weekly_6'",
                (original_price,),
            )
            conn.commit()
        finally:
            conn.close()
        _cleanup(email, event_ids)


def test_checkout_session_completed_activates_plan() -> None:
    suffix = uuid.uuid4().hex[:8]
    email = f"billing-s-{suffix}@magic.test"
    uid = _user(email)
    event_id = f"evt_checkout_{suffix}"
    try:
        event = {
            "id": event_id,
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": f"cs_{suffix}",
                    "client_reference_id": str(uid),
                    "subscription": "",
                    "customer": f"cus_{suffix}",
                    "metadata": {
                        "kind": subscription_billing.WEEKLY_SUBSCRIPTION_KIND,
                        "user_id": str(uid),
                        "plan_code": "weekly_4",
                    },
                }
            },
        }
        result = subscription_billing.handle_billing_event(event)
        assert result["handled"] is True
        row = _conn().execute(
            "SELECT plan, daily_phone_limit, daily_letter_limit, subscription_status "
            "FROM users WHERE id=?",
            (uid,),
        ).fetchone()
        assert row["plan"] == "weekly_4"
        assert row["daily_phone_limit"] == 4
        assert row["daily_letter_limit"] == 10
        assert row["subscription_status"] == "active"
    finally:
        _cleanup(email, [event_id])


def test_billing_plans_public_endpoint() -> None:
    client = TestClient(app)
    response = client.get("/api/billing/plans")
    assert response.status_code == 200
    body = response.json()
    assert len(body["plans"]) == 7
    assert body["plans"][0]["code"] == "weekly_2"
    assert body["plans"][0]["daily_phone_limit"] == 2
    assert body["plans"][0]["daily_letter_limit"] == 10
    assert body["plans"][-1]["code"] == "weekly_20"


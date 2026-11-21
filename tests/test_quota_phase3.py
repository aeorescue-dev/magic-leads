"""Fase 3: quotas diÃ¡rias, carta livre, telefone on-demand e add-ons 24h."""
from __future__ import annotations

import asyncio
import sqlite3
import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from backend.config import settings
from backend.main import _hash_token, app
from backend.services import (
    daily_quota,
    phone_jobs,
    phone_policy,
    subscription_billing,
    subscription_reveals,
)
from backend.services.db import DB_PATH, db_service  # noqa: F401
from backend.services.searchbug import PhoneLookupResult
from backend.services.security import hash_password


async def _no_resolve(*args, **kwargs):
    return None


def _drain_phone_jobs(lead_id: int | None = None) -> None:
    for job in phone_jobs.claim_due(limit=20, lead_id=lead_id):
        asyncio.run(phone_jobs.process_one(job))


def _conn():
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def _create_user(email: str, plan: str | None = None) -> int:
    conn = _conn()
    try:
        cur = conn.execute(
            "INSERT INTO users (email, password_hash, company_name, plan, subscription_status) "
            "VALUES (?, ?, 'Quota QA', 'free', 'expired')",
            (email, hash_password("test-pass-123")),
        )
        conn.commit()
        uid = int(cur.lastrowid)
    finally:
        conn.close()
    if plan:
        subscription_billing.activate_weekly_subscription(
            uid, plan, plan_until="2030-01-01T00:00:00+00:00"
        )
    return uid


def _user(email: str, plan: str = "weekly_2") -> int:
    return _create_user(email, plan)


def _auth(email: str, plan: str | None = None) -> tuple[dict[str, str], int]:
    """Cria user + sessão sem passar pelo rate limit de /api/auth/register."""
    uid = _create_user(email, plan)
    token = f"pytest-quota-{uuid.uuid4().hex}"
    db_service._service.create_user_session(uid, _hash_token(token), "Pytest", None)
    return {"Authorization": f"Bearer {token}"}, uid


def _lead(external_id: str, *, owner: str = "Alice Owner", mailing: str = "1 Mail St, New York, NY 10001") -> int:
    conn = _conn()
    address = f"{100 + (int(uuid.uuid4().hex[:6], 16) % 9000)} Quota Street"
    try:
        cur = conn.execute(
            "INSERT INTO leads (external_id, source_type, address, city, state, zip_code, "
            "issue_category, issue_description, owner_name, mailing_address, date_reported, "
            "is_qualified, is_junk, case_status, signal_type, signal_status, lead_status) "
            "VALUES (?, 'credits_seed', ?, 'NYC', 'NY', '10001', "
            "'Plumbing', 'Quota signal', ?, ?, ?, 1, 0, 'open', 'open_request', 'open', "
            "'available')",
            (
                external_id,
                address,
                owner,
                mailing,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def _cleanup(email: str, external_ids: list[str], event_ids: list[str]) -> None:
    conn = _conn()
    try:
        conn.execute("DELETE FROM users WHERE email=?", (email,))
        for ext in external_ids:
            conn.execute("DELETE FROM leads WHERE external_id=?", (ext,))
        for event_id in event_ids:
            conn.execute("DELETE FROM stripe_events WHERE event_id=?", (event_id,))
        conn.commit()
    finally:
        conn.close()


def test_letter_free_daily_limit_and_idempotency() -> None:
    suffix = uuid.uuid4().hex[:8]
    email = f"quota-l-{suffix}@magic.test"
    ext = f"quota-letter-{suffix}"
    uid = _user(email, "weekly_2")
    lead_id = _lead(ext)
    try:
        first = asyncio.run(
            subscription_reveals.reveal_letter(uid, lead_id)
        )
        assert first["duplicate"] is False
        assert first["payload"]["owner_name"] == "Alice Owner"
        assert first["payload"]["address"].endswith("Quota Street")
        assert first["payload"]["mailing_address"].startswith("1 Mail St")
        assert daily_quota.usage_payload(uid)["letter_used"] == 1

        duplicate = asyncio.run(
            subscription_reveals.reveal_letter(uid, lead_id)
        )
        assert duplicate["duplicate"] is True
        assert daily_quota.usage_payload(uid)["letter_used"] == 1

        for _ in range(9):
            daily_quota.consume_letter(uid)
        assert daily_quota.usage_payload(uid)["letter_remaining"] == 0
        with pytest.raises(daily_quota.QuotaError) as exc:
            daily_quota.consume_letter(uid)
        assert exc.value.code == "letter_quota_exhausted"
    finally:
        _cleanup(email, [ext], [])


def test_phone_mock_quota_addon_and_refund(monkeypatch) -> None:
    suffix = uuid.uuid4().hex[:8]
    email = f"quota-p-{suffix}@magic.test"
    ext1 = f"quota-phone-a-{suffix}"
    ext2 = f"quota-phone-b-{suffix}"
    ext3 = f"quota-phone-c-{suffix}"
    uid = _user(email, "weekly_2")
    lead1 = _lead(ext1)
    lead2 = _lead(ext2)
    lead3 = _lead(ext3)
    monkeypatch.setattr(settings, "SEARCHBUG_MOCK", True, raising=False)
    monkeypatch.setattr(phone_policy, "resolve_owner", _no_resolve)
    try:
        first = asyncio.run(
            subscription_reveals.reveal_phone(uid, lead1, f"idem-{suffix}-1")
        )
        assert first["success"] is True
        assert first["state"] == "in_progress"
        assert first["quota"]["bucket"] == "base"
        assert daily_quota.usage_payload(uid)["phone_remaining"] == 1
        _drain_phone_jobs(lead1)
        assert db_service._service.get_lead_by_id(lead1)["owner_phone"]

        duplicate = asyncio.run(
            subscription_reveals.reveal_phone(uid, lead1, f"idem-{suffix}-2")
        )
        assert duplicate["duplicate"] is True
        assert daily_quota.usage_payload(uid)["phone_remaining"] == 1

        second = asyncio.run(
            subscription_reveals.reveal_phone(uid, lead2, f"idem-{suffix}-3")
        )
        assert second["success"] is True
        assert second["state"] == "in_progress"
        _drain_phone_jobs(lead2)
        assert daily_quota.usage_payload(uid)["phone_remaining"] == 0

        with pytest.raises(daily_quota.QuotaError) as exhausted:
            daily_quota.consume_phone(uid)
        assert exhausted.value.code == "phone_quota_exhausted"

        addon = daily_quota.add_addon(uid, "addon_4")
        assert addon["phone_count"] == 4
        usage = daily_quota.usage_payload(uid)
        assert usage["addon_remaining"] == 4
        assert usage["phone_remaining"] == 4

        third = asyncio.run(
            subscription_reveals.reveal_phone(uid, lead3, f"idem-{suffix}-4")
        )
        assert third["success"] is True
        assert third["quota"]["bucket"] == "addon"
        _drain_phone_jobs(lead3)
        assert daily_quota.usage_payload(uid)["addon_remaining"] == 3
    finally:
        _cleanup(email, [ext1, ext2, ext3], [])


def test_phone_failure_preserves_quota(monkeypatch) -> None:
    suffix = uuid.uuid4().hex[:8]
    email = f"quota-f-{suffix}@magic.test"
    ext = f"quota-fail-{suffix}"
    uid = _user(email, "weekly_2")
    lead_id = _lead(ext)
    monkeypatch.setattr(settings, "SEARCHBUG_MOCK", False, raising=False)
    monkeypatch.setattr(phone_policy, "resolve_owner", _no_resolve)

    async def _fail(*args, **kwargs):
        return PhoneLookupResult(success=False, error="no_results")

    monkeypatch.setattr(phone_jobs.searchbug_service, "lookup_phone", _fail)
    try:
        result = asyncio.run(
            subscription_reveals.reveal_phone(uid, lead_id, f"idem-{suffix}-fail")
        )
        assert result["success"] is True
        assert result["state"] == "in_progress"
        _drain_phone_jobs(lead_id)
        usage = daily_quota.usage_payload(uid)
        assert usage["phone_used"] == 0
        assert usage["phone_remaining"] == 2
    finally:
        _cleanup(email, [ext], [])


def test_addon_webhook_injects_24h_units_and_is_idempotent() -> None:
    suffix = uuid.uuid4().hex[:8]
    email = f"quota-a-{suffix}@magic.test"
    uid = _user(email, "weekly_2")
    event_id = f"evt_addon_{suffix}"
    try:
        event = {
            "id": event_id,
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": f"cs_addon_{suffix}",
                    "client_reference_id": str(uid),
                    "metadata": {
                        "kind": subscription_billing.PHONE_ADDON_KIND,
                        "user_id": str(uid),
                        "pack_code": "addon_4",
                    },
                }
            },
        }
        first = subscription_billing.handle_billing_event(event)
        assert first["handled"] is True
        usage = daily_quota.usage_payload(uid)
        assert usage["addon_remaining"] == 4
        duplicate = subscription_billing.handle_billing_event(event)
        assert duplicate["duplicate"] is True
        assert daily_quota.usage_payload(uid)["addon_remaining"] == 4
    finally:
        _cleanup(email, [], [event_id])


def test_addon_expiry_is_ignored() -> None:
    suffix = uuid.uuid4().hex[:8]
    email = f"quota-e-{suffix}@magic.test"
    uid = _user(email, "weekly_2")
    try:
        daily_quota.add_addon(uid, "addon_2")
        conn = _conn()
        try:
            conn.execute(
                "UPDATE phone_addons SET expires_at='2000-01-01T00:00:00+00:00' WHERE user_id=?",
                (uid,),
            )
            conn.commit()
        finally:
            conn.close()
        assert daily_quota.usage_payload(uid)["addon_remaining"] == 0
        assert daily_quota.expire_addons() >= 1
    finally:
        _cleanup(email, [], [])


def test_subscription_usage_letter_and_phone_endpoints(monkeypatch) -> None:
    suffix = uuid.uuid4().hex[:8]
    email = f"quota-api-{suffix}@magicleads.app"
    ext = f"quota-api-{suffix}"
    monkeypatch.setattr(settings, "SEARCHBUG_MOCK", True, raising=False)
    monkeypatch.setattr(phone_policy, "resolve_owner", _no_resolve)
    client = TestClient(app)
    headers, uid = _auth(email, "weekly_2")
    lead_id = _lead(ext)
    try:
        usage = client.get("/api/subscription/usage", headers=headers)
        assert usage.status_code == 200, usage.text
        assert usage.json()["phone_limit"] == 2
        assert usage.json()["letter_limit"] == 10

        letter = client.post(
            f"/api/subscription/leads/{lead_id}/reveal-letter", headers=headers
        )
        assert letter.status_code == 200, letter.text
        assert letter.json()["payload"]["owner_name"] == "Alice Owner"

        phone = client.post(
            f"/api/subscription/leads/{lead_id}/reveal-phone",
            headers=headers,
            json={"idempotency_key": f"api-{suffix}"},
        )
        assert phone.status_code == 200, phone.text
        assert phone.json()["success"] is True
        assert phone.json()["state"] == "in_progress"
        _drain_phone_jobs(lead_id)
        assert db_service._service.get_lead_by_id(lead_id)["owner_phone"]

        after = client.get("/api/subscription/usage", headers=headers).json()
        assert after["letter_used"] == 1
        assert after["phone_used"] == 1
        assert after["phone_remaining"] == 1
    finally:
        _cleanup(email, [ext], [])



def test_staging_mock_checkout_and_addon_endpoints(monkeypatch) -> None:
    """Staging: BILLING_MOCK/ADDONS_MOCK ativam plano e injetam add-on 24h."""
    suffix = uuid.uuid4().hex[:8]
    email = f"quota-mock-{suffix}@magicleads.app"
    monkeypatch.setattr(settings, "BILLING_MOCK", True, raising=False)
    monkeypatch.setattr(settings, "ADDONS_MOCK", True, raising=False)
    client = TestClient(app)
    headers, _uid = _auth(email)
    try:
        checkout = client.post(
            "/api/billing/mock-checkout",
            headers=headers,
            json={"plan_code": "weekly_2"},
        )
        assert checkout.status_code == 200, checkout.text
        assert checkout.json()["plan"] == "weekly_2"

        usage = client.get("/api/subscription/usage", headers=headers).json()
        assert usage["phone_limit"] == 2
        assert usage["letter_limit"] == 10

        addon = client.post(
            "/api/billing/addons/mock-pay",
            headers=headers,
            json={"pack_code": "addon_4"},
        )
        assert addon.status_code == 200, addon.text
        body = addon.json()
        assert body["addon"]["phone_count"] == 4
        assert body["usage"]["addon_remaining"] == 4
        assert body["usage"]["phone_remaining"] == 6
    finally:
        _cleanup(email, [], [])


def test_staging_mock_endpoints_are_404_when_disabled(monkeypatch) -> None:
    """Sem as flags de staging os endpoints não existem (404, não 200)."""
    suffix = uuid.uuid4().hex[:8]
    email = f"quota-mock-off-{suffix}@magicleads.app"
    monkeypatch.setattr(settings, "BILLING_MOCK", False, raising=False)
    monkeypatch.setattr(settings, "ADDONS_MOCK", False, raising=False)
    client = TestClient(app)
    headers, _uid = _auth(email)
    try:
        checkout = client.post(
            "/api/billing/mock-checkout",
            headers=headers,
            json={"plan_code": "weekly_2"},
        )
        assert checkout.status_code == 404, checkout.text
        addon = client.post(
            "/api/billing/addons/mock-pay",
            headers=headers,
            json={"pack_code": "addon_4"},
        )
        assert addon.status_code == 404, addon.text
    finally:
        _cleanup(email, [], [])

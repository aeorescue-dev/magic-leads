"""Bonus free: canonical email, grants, consumo atomico, refund e circuit breaker."""
from __future__ import annotations

import pytest

from backend.config import settings
from backend.services import free_unlocks


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    free_unlocks._INIT["ready"] = False
    monkeypatch.setattr(settings, "FREE_UNLOCKS_ENABLED", True)
    monkeypatch.setattr(settings, "FREE_UNLOCKS_PHONE_TOTAL", 2)
    monkeypatch.setattr(settings, "FREE_UNLOCKS_LETTER_TOTAL", 3)
    monkeypatch.setattr(settings, "FREE_UNLOCKS_DAILY_CAP", 25)
    monkeypatch.setattr(settings, "FREE_UNLOCKS_MONTHLY_BUDGET_USD", 75.0)
    monkeypatch.setattr(settings, "FREE_UNLOCKS_PHONE_COST_CENTS", 20)
    free_unlocks.init()
    from backend.services.db import get_connection

    conn = get_connection()
    try:
        for table in (
            "free_unlock_grants",
            "free_unlock_keys",
            "free_unlock_events",
            "free_unlock_daily",
            "free_unlock_pending",
            "free_unlock_circuit",
        ):
            conn.execute(f"DELETE FROM {table}")
        conn.commit()
    finally:
        conn.close()
    yield


def test_canonical_email_normalizes_aliases():
    assert free_unlocks.canonical_email("John.Doe+ads@Gmail.com") == "johndoe@gmail.com"
    assert free_unlocks.canonical_email("john+tag@example.com") == "john@example.com"
    assert free_unlocks.canonical_email("JOHN@EXAMPLE.COM") == "john@example.com"


def test_disposable_domains_detected():
    assert free_unlocks.is_disposable("a@mailinator.com") is True
    assert free_unlocks.is_disposable("a@sub.mailinator.com") is True
    assert free_unlocks.is_disposable("a@magicleads.app") is False


def test_grant_package_and_balance():
    result = free_unlocks.grant(101, "a@example.com", "device-1")
    assert result["ok"] is True and result["granted"] is True
    balance = free_unlocks.balance(101)
    assert balance["phone"] == {"total": 2, "used": 0, "remaining": 2}
    assert balance["letter"] == {"total": 3, "used": 0, "remaining": 3}
    again = free_unlocks.grant(101, "a@example.com", "device-1")
    assert again["granted"] is False


def test_grant_blocked_by_same_device_or_email():
    assert free_unlocks.grant(102, "same@example.com", "device-x")["granted"] is True
    by_device = free_unlocks.grant(103, "other@example.com", "device-x")
    assert by_device["reason"] == "device_already_used"
    by_email = free_unlocks.grant(104, "same+alias@example.com", "device-y")
    assert by_email["reason"] == "email_already_used"


def test_consume_phone_and_letter_until_exhausted():
    free_unlocks.grant(105, "c@example.com", "device-c")
    assert free_unlocks.consume_phone(105, 1)["ok"] is True
    assert free_unlocks.consume_phone(105, 2)["ok"] is True
    third = free_unlocks.consume_phone(105, 3)
    assert third == {"ok": False, "reason": "exhausted"}
    assert free_unlocks.balance(105)["phone"]["used"] == 2

    for lead in (1, 2, 3):
        assert free_unlocks.consume_letter(105, lead)["ok"] is True
    assert free_unlocks.consume_letter(105, 4)["ok"] is False


def test_refund_restores_unit():
    free_unlocks.grant(106, "d@example.com", "device-d")
    assert free_unlocks.consume_phone(106, 10)["ok"] is True
    assert free_unlocks.balance(106)["phone"]["used"] == 1
    free_unlocks.refund_phone(106, 10)
    assert free_unlocks.balance(106)["phone"]["used"] == 0


def test_daily_cap_pauses_grants(monkeypatch):
    monkeypatch.setattr(settings, "FREE_UNLOCKS_DAILY_CAP", 1)
    assert free_unlocks.grant(107, "e@example.com", "device-e")["granted"] is True
    blocked = free_unlocks.grant(108, "f@example.com", "device-f")
    assert blocked["ok"] is False
    assert blocked["reason"] == "daily_cap"


def test_monthly_budget_pauses(monkeypatch):
    monkeypatch.setattr(settings, "FREE_UNLOCKS_MONTHLY_BUDGET_USD", 0.01)
    free_unlocks.grant(109, "g@example.com", "device-g")
    free_unlocks.consume_phone(109, 20)
    free_unlocks.add_phone_cost(109, 20)
    blocked = free_unlocks.grant(110, "h@example.com", "device-h")
    assert blocked["ok"] is False
    assert blocked["reason"] == "monthly_budget"


def test_email_token_roundtrip():
    token = free_unlocks.email_token(111, "i@example.com", ttl_seconds=60)
    data = free_unlocks.read_email_token(token)
    assert data == {"ok": True, "user_id": 111, "email": "i@example.com"}
    assert free_unlocks.read_email_token(token + "x")["ok"] is False
    expired = free_unlocks.email_token(111, "i@example.com", ttl_seconds=-5)
    assert free_unlocks.read_email_token(expired)["reason"] == "expired"


def test_flag_off_grants_nothing(monkeypatch):
    monkeypatch.setattr(settings, "FREE_UNLOCKS_ENABLED", False)
    assert free_unlocks.grant(112, "j@example.com", "device-j")["reason"] == "disabled"
    assert free_unlocks.consume_phone(112, 1)["reason"] == "disabled"
    assert free_unlocks.balance(112)["enabled"] is False

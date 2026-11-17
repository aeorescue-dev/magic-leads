"""Fase 1: catálogo de planos semanais, tabelas e relógio America/New_York."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from backend.services import plans
from backend.services.billing_time import (
    local_date,
    local_day_bounds_utc,
    next_reset_utc,
)
from backend.services.db import DB_PATH, db_service  # noqa: F401


def test_seven_weekly_plans_catalog() -> None:
    catalog = plans.list_plans()
    assert len(catalog) == 7
    assert [p["code"] for p in catalog] == [
        "weekly_2",
        "weekly_4",
        "weekly_6",
        "weekly_8",
        "weekly_10",
        "weekly_15",
        "weekly_20",
    ]
    assert [p["name"] for p in catalog] == [
        "Starter",
        "Essential",
        "Growth",
        "Pro",
        "Business",
        "Scale",
        "Agency",
    ]
    assert [p["price_cents"] for p in catalog] == [
        2590,
        5020,
        7434,
        10090,
        12600,
        17850,
        23100,
    ]
    assert [p["daily_phone_limit"] for p in catalog] == [2, 4, 6, 8, 10, 15, 20]
    assert [p["weekly_phone_total"] for p in catalog] == [14, 28, 42, 56, 70, 105, 140]
    assert all(p["daily_letter_limit"] == 10 for p in catalog)
    assert all(p["code"] != "legacy_pro" for p in catalog)


def test_addon_catalog() -> None:
    assert len(plans.list_addons()) == 7
    assert [(a["phone_count"], a["price_cents"]) for a in plans.list_addons()] == [
        (2, 250),
        (4, 480),
        (6, 720),
        (8, 960),
        (10, 1200),
        (15, 1800),
        (20, 2400),
    ]


def test_billing_tables_and_seed() -> None:
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    try:
        tables = {
            r["name"]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert {"subscription_plans", "user_daily_usage", "phone_addons"} <= tables

        columns = {r["name"] for r in conn.execute("PRAGMA table_info(users)")}
        assert {"daily_phone_limit", "daily_letter_limit"} <= columns

        rows = conn.execute(
            "SELECT code, name, price_cents, daily_phone_limit, daily_letter_limit, "
            "weekly_phone_total, active FROM subscription_plans ORDER BY sort_order"
        ).fetchall()
        assert len(rows) == 7
        assert all(int(row["active"]) == 1 for row in rows)
        assert rows[0]["code"] == "weekly_2"
        assert rows[-1]["code"] == "weekly_20"
        assert rows[2]["daily_phone_limit"] == 6
        assert rows[2]["weekly_phone_total"] == 42
        assert all(int(row["daily_letter_limit"]) == 10 for row in rows)
        assert not any(row["code"] == "legacy_pro" for row in rows)

        addon_cols = {r["name"] for r in conn.execute("PRAGMA table_info(phone_addons)")}
        assert {
            "user_id",
            "pack_code",
            "phone_count",
            "used_count",
            "price_cents",
            "expires_at",
            "status",
        } <= addon_cols
    finally:
        conn.close()


def test_billing_timezone_reset() -> None:
    winter = datetime(2026, 1, 15, 4, 30, tzinfo=timezone.utc)
    assert local_date(winter) == "2026-01-14"
    assert next_reset_utc(winter).startswith("2026-01-15T05:00:00")

    summer = datetime(2026, 7, 15, 3, 30, tzinfo=timezone.utc)
    assert local_date(summer) == "2026-07-14"
    assert next_reset_utc(summer).startswith("2026-07-15T04:00:00")

    start, end = local_day_bounds_utc(winter)
    assert start.startswith("2026-01-14T05:00:00")
    assert end.startswith("2026-01-15T05:00:00")

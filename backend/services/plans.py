"""Catálogo único dos planos semanais e add-ons de telefone.

Fonte de verdade para:
- preço semanal;
- cota diária de telefones;
- limite diário de cartas/visitas (10 em todos os planos);
- total semanal de telefones (daily * 7);
- Price ID recorrente da Stripe (via env).

Não há plano legacy: o produto trabalha apenas com estes 7 planos.
O reset diário é feito em `America/New_York` (Billing_timezone).
"""
from __future__ import annotations

import os
from typing import Any

BILLING_TIMEZONE = "America/New_York"
DAILY_LETTER_LIMIT = 10

PLAN_CATALOG: tuple[dict[str, Any], ...] = (
    {
        "code": "weekly_2",
        "name": "Starter",
        "price_cents": 2590,
        "daily_phone_limit": 2,
        "daily_letter_limit": DAILY_LETTER_LIMIT,
        "weekly_phone_total": 14,
        "stripe_price_env": "STRIPE_PRICE_WEEKLY_2",
        "sort_order": 1,
    },
    {
        "code": "weekly_4",
        "name": "Essential",
        "price_cents": 5020,
        "daily_phone_limit": 4,
        "daily_letter_limit": DAILY_LETTER_LIMIT,
        "weekly_phone_total": 28,
        "stripe_price_env": "STRIPE_PRICE_WEEKLY_4",
        "sort_order": 2,
    },
    {
        "code": "weekly_6",
        "name": "Growth",
        "price_cents": 7434,
        "daily_phone_limit": 6,
        "daily_letter_limit": DAILY_LETTER_LIMIT,
        "weekly_phone_total": 42,
        "stripe_price_env": "STRIPE_PRICE_WEEKLY_6",
        "sort_order": 3,
    },
    {
        "code": "weekly_8",
        "name": "Pro",
        "price_cents": 10090,
        "daily_phone_limit": 8,
        "daily_letter_limit": DAILY_LETTER_LIMIT,
        "weekly_phone_total": 56,
        "stripe_price_env": "STRIPE_PRICE_WEEKLY_8",
        "sort_order": 4,
    },
    {
        "code": "weekly_10",
        "name": "Business",
        "price_cents": 12600,
        "daily_phone_limit": 10,
        "daily_letter_limit": DAILY_LETTER_LIMIT,
        "weekly_phone_total": 70,
        "stripe_price_env": "STRIPE_PRICE_WEEKLY_10",
        "sort_order": 5,
    },
    {
        "code": "weekly_15",
        "name": "Scale",
        "price_cents": 17850,
        "daily_phone_limit": 15,
        "daily_letter_limit": DAILY_LETTER_LIMIT,
        "weekly_phone_total": 105,
        "stripe_price_env": "STRIPE_PRICE_WEEKLY_15",
        "sort_order": 6,
    },
    {
        "code": "weekly_20",
        "name": "Agency",
        "price_cents": 23100,
        "daily_phone_limit": 20,
        "daily_letter_limit": DAILY_LETTER_LIMIT,
        "weekly_phone_total": 140,
        "stripe_price_env": "STRIPE_PRICE_WEEKLY_20",
        "sort_order": 7,
    },
)

PLAN_BY_CODE: dict[str, dict[str, Any]] = {plan["code"]: plan for plan in PLAN_CATALOG}

# Add-ons de 24h. Preços em cents; cada pack injeta `phone_count` unidades.
ADDON_PACKS: tuple[dict[str, Any], ...] = (
    {"code": "addon_2", "phone_count": 2, "price_cents": 250},
    {"code": "addon_4", "phone_count": 4, "price_cents": 480},
    {"code": "addon_6", "phone_count": 6, "price_cents": 720},
    {"code": "addon_8", "phone_count": 8, "price_cents": 960},
    {"code": "addon_10", "phone_count": 10, "price_cents": 1200},
    {"code": "addon_15", "phone_count": 15, "price_cents": 1800},
    {"code": "addon_20", "phone_count": 20, "price_cents": 2400},
)

ADDON_BY_CODE: dict[str, dict[str, Any]] = {pack["code"]: pack for pack in ADDON_PACKS}


def get_plan(code: str) -> dict[str, Any] | None:
    return PLAN_BY_CODE.get(str(code or "").strip())


def list_plans() -> list[dict[str, Any]]:
    return list(PLAN_CATALOG)


def get_addon(code: str) -> dict[str, Any] | None:
    return ADDON_BY_CODE.get(str(code or "").strip())


def list_addons() -> list[dict[str, Any]]:
    return list(ADDON_PACKS)


def stripe_price_id_for(plan: dict[str, Any]) -> str:
    """Price ID recorrente semanal; vazio até a Stripe test/live estar criada."""
    env_key = str(plan.get("stripe_price_env") or "").strip()
    return (os.environ.get(env_key, "") if env_key else "").strip()

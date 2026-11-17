"""Provisiona os 7 planos semanais na Stripe e grava os Price IDs na BD.

Uso (staging/test):
    STRIPE_API_KEY=sk_test_... python backend/scripts/setup_stripe_weekly_plans.py --apply

Sem `--apply` faz dry-run e não altera a BD.
Nunca aceita `sk_live_` sem `--allow-live`.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys

import stripe

from backend.services.db import DB_PATH
from backend.services.plans import PLAN_CATALOG


def _find_product(plan_code: str):
    products = stripe.Product.list(active=True, limit=100).data
    for product in products:
        if (product.metadata or {}).get("plan_code") == plan_code:
            return product
    return None


def _find_weekly_price(product_id: str, plan: dict):
    prices = stripe.Price.list(product=product_id, active=True, limit=100).data
    for price in prices:
        recurring = price.recurring or {}
        if (
            recurring.get("interval") == "week"
            and int(price.unit_amount or 0) == int(plan["price_cents"])
            and str(price.currency or "").lower() == "usd"
        ):
            return price
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Grava Price IDs na BD")
    parser.add_argument("--allow-live", action="store_true", help="Permite chave sk_live_")
    args = parser.parse_args()

    key = (os.environ.get("STRIPE_API_KEY") or "").strip()
    if not key:
        print("STRIPE_API_KEY em falta.", file=sys.stderr)
        return 2
    if key.startswith("sk_live_") and not args.allow_live:
        print("Chave LIVE recusada sem --allow-live.", file=sys.stderr)
        return 2
    stripe.api_key = key

    rows: list[tuple[str, str, str, str]] = []
    for plan in PLAN_CATALOG:
        product = _find_product(plan["code"])
        if product is None:
            if not args.apply:
                rows.append((plan["code"], "(novo produto)", "(novo preço)", "dry-run"))
                continue
            product = stripe.Product.create(
                name=f"Magic Leads — {plan['name']}",
                description=f"{plan['daily_phone_limit']} revelações de telefone/dia · {plan['weekly_phone_total']}/semana",
                metadata={
                    "plan_code": plan["code"],
                    "daily_phone_limit": str(plan["daily_phone_limit"]),
                    "daily_letter_limit": str(plan["daily_letter_limit"]),
                    "weekly_phone_total": str(plan["weekly_phone_total"]),
                },
            )
        price = _find_weekly_price(product.id, plan)
        if price is None:
            if not args.apply:
                rows.append((plan["code"], product.id, "(novo preço)", "dry-run"))
                continue
            price = stripe.Price.create(
                product=product.id,
                unit_amount=int(plan["price_cents"]),
                currency="usd",
                recurring={"interval": "week"},
                metadata={
                    "plan_code": plan["code"],
                    "daily_phone_limit": str(plan["daily_phone_limit"]),
                    "daily_letter_limit": str(plan["daily_letter_limit"]),
                },
            )
        rows.append((plan["code"], product.id, price.id, "ok"))

    if args.apply:
        conn = sqlite3.connect(DB_PATH, timeout=20)
        try:
            for code, _product_id, price_id, state in rows:
                if state != "ok":
                    continue
                conn.execute(
                    "UPDATE subscription_plans SET stripe_price_id=?, stripe_product_id=? WHERE code=?",
                    (price_id, _product_id, code),
                )
            conn.commit()
        finally:
            conn.close()

    print(f"{'PLAN':12} {'PRODUCT':24} {'PRICE':24} STATE")
    for code, product_id, price_id, state in rows:
        print(f"{code:12} {product_id:24} {price_id:24} {state}")
    if not args.apply:
        print("\nDry-run: nada foi alterado. Repete com --apply para gravar.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Teste de ponta a ponta do checkout de assinatura (Stripe real).

Valida o fluxo completo contra um backend em execucao:

1. Registra um usuario novo e unico;
2. Autentica com o token retornado;
3. Chama POST /api/billing/checkout;
4. Garante que a resposta NAO e mock e traz uma checkout_url real do Stripe;
5. Confirma que a pagina hospedada do Stripe responde (link funcional).

O teste e pulado automaticamente quando E2E_API_URL nao esta definido,
para nao depender de rede/producao no CI padrao.

Uso:
    set E2E_API_URL=https://magic-leads-production.up.railway.app   (Windows)
    export E2E_API_URL=https://magic-leads-production.up.railway.app (bash)
    pytest tests/test_e2e_checkout.py -v
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

import pytest

API_URL = os.environ.get("E2E_API_URL", "").rstrip("/")

pytestmark = pytest.mark.skipif(
    not API_URL,
    reason="Defina E2E_API_URL para rodar o teste de ponta a ponta do checkout.",
)


def _post(path: str, payload: dict, token: str | None = None, timeout: int = 30):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(
        f"{API_URL}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise AssertionError(f"POST {path} -> HTTP {exc.code}: {body}") from exc


def _get_ok(url: str, timeout: int = 45) -> int:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status


def test_new_user_checkout_returns_functional_stripe_url():
    email = f"e2e-checkout-{int(time.time())}-{os.getpid()}@gmail.com"
    status, registered = _post(
        "/api/auth/register",
        {"email": email, "password": "Teste12345!", "company_name": "E2E Checkout Test"},
    )
    assert status == 200, registered
    token = registered.get("token")
    assert token, f"register nao retornou token: {registered}"

    status, checkout = _post("/api/billing/checkout", {}, token=token)
    assert status == 200, checkout

    assert checkout.get("mock") is False, (
        "checkout retornou mock=True — Stripe nao configurado no backend de producao: "
        f"{checkout}"
    )

    url = checkout.get("checkout_url")
    assert url, f"checkout_url ausente na resposta: {checkout}"
    assert url.startswith("https://checkout.stripe.com/"), url
    assert "cs_" in url, f"checkout_url nao parece uma sessao Stripe: {url}"

    plan = checkout.get("plan") or {}
    assert isinstance(plan, dict)
    assert plan.get("amount_cents") == 7900 or plan.get("amount_usd") == 79, plan

    page_status = _get_ok(url)
    assert page_status == 200, f"pagina do Stripe respondeu HTTP {page_status}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

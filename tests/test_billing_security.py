"""Regressão de segurança: o pagamento só pode ser ativado pelo Stripe.

Histórico: existia POST /api/billing/mock-activate, que chamava
db_service.activate_week(..., days=7) sem verificar pagamento. Qualquer
utilizador autenticado podia chamar o endpoint e auto-conceder 7 dias de plano
Pro — bypass completo de faturação.

Invariantes fixados aqui:
1. /api/billing/mock-activate responde 410 e NÃO altera o acesso do utilizador.
2. A ativação legítima (extend_access, chamada pelo webhook Stripe verificado)
   continua a funcionar — a remoção do mock não pode quebrar o caminho real.
3. Sem Stripe configurado, o checkout é fail-closed: sem checkout_url, o
   frontend não consegue ativar nada.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.services.db import db_service

EMAIL = "pytest-billing-bypass@magicleads.app"
PASSWORD = "senhaBilling123"


@pytest.fixture(scope="module")
def auth_client():
    """Utilizador registado uma vez por módulo (a BD de teste persiste na sessão)."""
    client = TestClient(app)
    r = client.post(
        "/api/auth/register",
        json={"email": EMAIL, "password": PASSWORD, "company_name": "Pytest Billing"},
    )
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    return client, {"Authorization": f"Bearer {token}"}


def test_mock_activate_is_disabled_and_grants_nothing(auth_client):
    """O endpoint de mock não pode_exists nem conceder acesso."""
    client, headers = auth_client

    before = client.get("/api/auth/me", headers=headers).json()
    plan_until_before = before.get("plan_until")

    r = client.post("/api/billing/mock-activate", headers=headers)
    # 410 Gone = removido. O essencial é que NÃO seja 200.
    assert r.status_code == 410, f"mock-activate Deveria estar desativado, devolveu {r.status_code}: {r.text}"
    assert "mock" not in r.text.lower() or "desativado" in r.text.lower()

    after = client.get("/api/auth/me", headers=headers).json()
    assert after.get("plan_until") == plan_until_before, "mock-activate alterou o acesso do utilizador"
    assert after.get("plan") == before.get("plan"), "mock-activate alterou o plano do utilizador"


def test_legitimate_stripe_activation_still_works(auth_client):
    """O caminho real (usado pelo webhook) continua a estender o acesso."""
    client, headers = auth_client
    me = client.get("/api/auth/me", headers=headers).json()
    user = me.get("user", me)
    user_id = user["id"]

    before = db_service._service.get_user_by_id(user_id)
    updated = db_service._service.extend_access(user_id, days=7)

    assert updated is not None
    assert updated["plan"] == "pro"
    assert updated["subscription_status"] == "active"
    assert updated["plan_until"] > (before["plan_until"] or ""), "plan_until não avançou"


def test_checkout_is_fail_closed_without_stripe(monkeypatch, auth_client):
    """Sem Stripe configurado, o checkout devolve mock=True e checkout_url=None.

    O frontend trata a ausência de checkout_url como erro e não ativa nada.
    Este teste garante que o "mock" do checkout nunca vem acompanhado de um
    URL que permitiria ativar um plano.
    """
    client, headers = auth_client
    monkeypatch.setattr("backend.main._stripe_configured", lambda: False)

    r = client.post("/api/billing/checkout", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mock"] is True
    assert body["checkout_url"] is None, "não deve haver URL de checkout sem Stripe configurado"

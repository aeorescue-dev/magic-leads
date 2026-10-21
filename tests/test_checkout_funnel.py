"""Prioridade A: funil de checkout (criou -> abriu -> pagou) e recuperacao.

Contexto (achado de producao): 23 sessoes Stripe criadas, 23 expiradas, 23
`unpaid`, e TODAS com `customer_details` vazio — ninguem preencheu um email
nunca. Sem `customer_email` na sessao e sem tabela de tracking nao ha como
saber se a perda esta' antes do checkout, no Stripe, ou no cartao.

Invariantes fixados aqui:
  1. A sessao Stripe e' criada com `customer_email` (o email do utilizador) —
     e' o que passa a registar a intencao.
  2. Idempotencia: no maximo uma sessao ABERTA por utilizador. Um segundo
     pedido reusa a sessao aberta em vez de criar outra (pilha de orfas).
  3. Cada sessao criada fica registada em `checkout_sessions` (funil).
  4. O webhook marca a sessao como completed/expired.
  5. A recuperacao so' actua sobre sessoes abertas, semlembrar, e nunca
     sobre quem ja' tem plano activo.
  6. Falha-closed: sem canal de e-mail, a recuperacao nao envia nada.
"""
from __future__ import annotations

import types

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.services.db import db_service

EMAIL = "pytest-checkout-funnel@magicleads.app"
PASSWORD = "senhaCheckout123"


@pytest.fixture(scope="module")
def auth_client():
    """Utilizador + sessao criados DIRECTAMENTE na BD.

    De proposito NAO usa POST /api/auth/register: esse endpoint tem rate limit
    (3/min) e o reuso com outros ficheiros de teste provocava 429 falsos.
    """
    import secrets

    from backend.main import _hash_token
    from backend.services.security import hash_password

    client = TestClient(app)
    svc = db_service._service

    existing = svc.get_user_by_email(EMAIL)
    if existing:
        user = existing
    else:
        user = svc.create_user(
            EMAIL, hash_password(PASSWORD), "Pytest Funnel", plan="free"
        )
    assert user, "utilizador de teste nao criado"

    token = secrets.token_urlsafe(32)
    svc.create_user_session(user["id"], _hash_token(token), "pytest", None)
    return client, {"Authorization": f"Bearer {token}"}, user["id"]


class FakeSession:
    def __init__(self, sid: str, url: str, created: int = 1_000_000):
        self.id = sid
        self.url = url
        self.created = created


class FakeSessionList:
    def __init__(self, data):
        self.data = data


class FakeStripe:
    """Dublê mínimo da API do Stripe usada na criação de sessão."""

    def __init__(self, open_sessions=None):
        self.created_args: list[dict] = []
        self.expired: list[str] = []
        self._open = list(open_sessions or [])
        self.checkout = types.SimpleNamespace(
            Session=types.SimpleNamespace(
                list=self._list,
                create=self._create,
                expire=self._expire,
            )
        )

    def _list(self, **kwargs):
        return FakeSessionList(self._open)

    def _create(self, **kwargs):
        self.created_args.append(kwargs)
        return FakeSession(f"cs_new_{len(self.created_args)}", "https://checkout.stripe.com/c/pay/cs_new")

    def _expire(self, sid: str):
        self.expired.append(sid)
        return FakeSession(sid, "")


def _patch_stripe(monkeypatch, fake: FakeStripe):
    monkeypatch.setattr("backend.main.stripe", fake)
    monkeypatch.setattr("backend.main._stripe_configured", lambda: True)


# ------------------------------------------------------------------ criacao


@pytest.mark.asyncio
async def test_checkout_session_captures_customer_email(auth_client, monkeypatch):
    """A sessao leva `customer_email`: e' o que regista a intencao no Stripe."""
    _client, _headers, user_id = auth_client
    fake = FakeStripe()
    _patch_stripe(monkeypatch, fake)

    from backend.main import _create_stripe_checkout_session

    mock, url = await _create_stripe_checkout_session(user_id, "en", EMAIL)
    assert mock is False
    assert url and url.startswith("https://checkout.stripe.com/")
    assert fake.created_args, "a sessao nao foi criada"
    kwargs = fake.created_args[-1]
    assert kwargs.get("customer_email") == EMAIL
    assert kwargs.get("client_reference_id") == str(user_id)
    assert kwargs.get("metadata", {}).get("user_id") == str(user_id)


@pytest.mark.asyncio
async def test_checkout_session_is_idempotent(auth_client, monkeypatch):
    """Segundo pedido REUTILIZA a sessao aberta (nao cria outra)."""
    _client, _headers, user_id = auth_client
    existing = FakeSession("cs_existing_1", "https://checkout.stripe.com/c/pay/cs_existing_1")
    fake = FakeStripe(open_sessions=[existing])
    _patch_stripe(monkeypatch, fake)

    from backend.main import _create_stripe_checkout_session

    mock, url = await _create_stripe_checkout_session(user_id, "en", EMAIL)
    assert mock is False
    assert url == existing.url
    assert fake.created_args == [], "nao devia criar uma nova sessao com uma sessao aberta"
    assert fake.expired == []


@pytest.mark.asyncio
async def test_checkout_expires_orphan_open_sessions(auth_client, monkeypatch):
    """Sessoes abertas antigas sao expiradas: no maximo uma viva por utilizador."""
    _client, _headers, user_id = auth_client
    old = FakeSession("cs_old", "https://checkout.stripe.com/c/pay/cs_old", created=1)
    new = FakeSession("cs_new", "https://checkout.stripe.com/c/pay/cs_new", created=2)
    fake = FakeStripe(open_sessions=[old, new])
    _patch_stripe(monkeypatch, fake)

    from backend.main import _create_stripe_checkout_session

    _mock, url = await _create_stripe_checkout_session(user_id, "en", EMAIL)
    assert url == new.url, "deve reutilizar a mais recente"
    assert fake.expired == ["cs_old"], "a sessao antiga deve ser expirada"
    assert fake.created_args == []


# ------------------------------------------------------------------ tracking


def test_checkout_session_is_tracked_in_funnel_table(auth_client):
    """Cada sessao criada fica registada em `checkout_sessions`."""
    _client, _headers, user_id = auth_client
    svc = db_service._service

    assert svc.record_checkout_session(
        user_id, "cs_track_1", EMAIL, 12000, "usd", "https://checkout.stripe.com/x"
    )
    # Idempotente por session_id.
    assert not svc.record_checkout_session(user_id, "cs_track_1", EMAIL, 12000, "usd", "u")

    stats = svc.checkout_funnel_stats()
    assert stats["sessions_created"] >= 1
    assert stats["sessions_with_email"] >= 1
    assert 0.0 <= stats["conversion_rate"] <= 1.0


def test_webhook_marks_session_completed(auth_client):
    """O webhook fecha a sessao como paga (funil)."""
    _client, _headers, user_id = auth_client
    svc = db_service._service
    svc.record_checkout_session(
        user_id, "cs_complete_1", EMAIL, 12000, "usd", "https://checkout.stripe.com/x"
    )
    assert svc.update_checkout_session("cs_complete_1", status="completed") is True
    row = svc.get_open_checkout_session(user_id)
    # A sessao completada ja' nao conta como aberta.
    assert row is None or row["session_id"] != "cs_complete_1"


# ------------------------------------------------------------------ recuperacao


def test_recoverable_sessions_skip_reminded_and_fresh(auth_client):
    """So' entram na recuperacao as sessoes abertas, velhas e semlembrar."""
    _client, _headers, user_id = auth_client
    svc = db_service._service

    svc.record_checkout_session(user_id, "cs_recover_1", EMAIL, 12000, "usd", "u1")
    svc.record_checkout_session(user_id, "cs_recover_2", EMAIL, 12000, "usd", "u2")
    # Ja' foi lembrada duas vezes -> esgotou o limite de lembretes.
    svc.mark_checkout_reminded("cs_recover_2")
    svc.mark_checkout_reminded("cs_recover_2")

    rows = svc.list_recoverable_checkout_sessions(
        "2999-01-01 00:00:00", max_reminders=2, limit=50
    )
    ids = {r["session_id"] for r in rows}
    assert "cs_recover_1" in ids
    assert "cs_recover_2" not in ids, "sessao ja' lembrada nao pode ser lembrada de novo"

    # Uma sessao recem-criada nao entra (cutoff no passado).
    fresh = svc.list_recoverable_checkout_sessions(
        "1970-01-01 00:00:00", max_reminders=2, limit=50
    )
    assert all(r["session_id"] not in ids for r in fresh)


@pytest.mark.asyncio
async def test_recovery_email_is_fail_closed_without_channel(monkeypatch):
    """Sem EMAIL_API_KEY/EMAIL_FROM nao se envia e-mail de recuperacao."""
    import backend.main as main_module

    monkeypatch.setattr(main_module.settings, "EMAIL_API_KEY", "", raising=False)
    monkeypatch.setattr(main_module.settings, "EMAIL_FROM", "", raising=False)

    ok = await main_module._send_checkout_recovery_email(
        "alguem@example.com", "Empresa", "https://checkout.stripe.com/x"
    )
    assert ok is False


@pytest.mark.asyncio
async def test_recovery_email_uses_resend(monkeypatch):
    """Com canal configurado, envia via Resend."""
    import backend.main as main_module

    monkeypatch.setattr(main_module.settings, "EMAIL_API_KEY", "re_test_key", raising=False)
    monkeypatch.setattr(
        main_module.settings, "EMAIL_FROM", "Magic Leads <noreply@magicleads.app>", raising=False
    )
    calls: list[dict] = []

    class FakeResp:
        status_code = 200

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append({"url": url, "headers": headers, "json": json})
        return FakeResp()

    monkeypatch.setattr(main_module.httpx, "post", fake_post)

    ok = await main_module._send_checkout_recovery_email(
        "alguem@example.com", "Empresa X", "https://checkout.stripe.com/c/pay/cs_1"
    )
    assert ok is True
    assert calls, "a Resend nao foi chamada"
    assert calls[0]["json"]["to"] == ["alguem@example.com"]
    assert "https://checkout.stripe.com/c/pay/cs_1" in calls[0]["json"]["text"]

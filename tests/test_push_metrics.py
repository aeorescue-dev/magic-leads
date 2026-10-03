"""Fase 2: telemetria das entregas de push notification.

Invariantes fixados aqui:

  1. `accepted` NÃO é entrega. É o serviço de push a aceitar a mensagem.
     A distinção está nos nomes e nas_metricas, para ninguém ler este
     número como "notificações vistas".
  2. `expired` (404 e 410) é o outcome operacionalmente mais importante:
     subscrição morta que o serviço remove a seguir.
  3. `not_configured` tem de ser registado mesmo quando o push está
     desligado — é o modo de falha mais silencioso que existe (tudo
     devolve 0, nada aparece no log, ninguém percebe).
  4. O valor de retorno de `_send_single` não muda: True, False ou
     "expired". A telemetria é aditiva.
  5. `_record` nunca levanta: telemetria rota não pode impedir um envio.
  6. O caminho de debug (`_send_single_debug`) NÃO é instrumentado: um
     broadcast de teste não pode distorcer a taxa de entrega real.
  7. Contagem: uma subscrição = uma linha, com `attempts` a dizer quantas
     vezes foi tentado.
"""
from __future__ import annotations

from unittest.mock import Mock

import anyio
import pytest

from backend.services.db import db_service, get_connection
from backend.services.metrics import push_metrics
from backend.services.push_service import (
    PushService,
    classify_push_outcome,
)

SUB = {"endpoint": "https://push.example/abc", "p256dh": "k", "auth": "a", "user_id": 7}


@pytest.fixture(autouse=True)
def _clean_deliveries():
    """Isola cada teste: esvazia a tabela E o buffer partilhado.

    `push_metrics` e um singleton de modulo. Sem drenar o buffer, um evento
    de um teste que nao chegou a ser escrito aparecia no teste seguinte e
    tornava o resultado dependente da ordem de execucao.
    """
    push_metrics._drain_for_test()
    conn = get_connection()
    try:
        conn.execute("DELETE FROM push_deliveries")
        conn.commit()
    finally:
        conn.close()
    yield
    push_metrics._drain_for_test()


def _rows() -> list[dict]:
    conn = get_connection()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM push_deliveries ORDER BY id")]
    finally:
        conn.close()


def _svc_configured(monkeypatch) -> PushService:
    svc = PushService()
    svc._configured = True
    svc._vapid_private_key = "priv"
    svc._vapid_claims = {"sub": "mailto:x@y.z"}
    return svc


def _patch_webpush(monkeypatch, result=None, exc: Exception | None = None):
    """Substitui o webpush por um stub que não sai à rede."""
    calls: list[dict] = []

    def _fake(**kwargs):
        calls.append(kwargs)
        if exc is not None:
            raise exc
        return result

    monkeypatch.setattr("backend.services.push_service.webpush", _fake)
    return calls


def _webpush_exception(status: int, headers: dict | None = None) -> Exception:
    from pywebpush import WebPushException

    response = Mock()
    response.status_code = status
    response.headers = headers or {}
    return WebPushException("mock", response=response)


async def _flush(expected: int | None = None) -> list[dict]:
    """Esvazia o buffer e devolve as linhas persistidas.

    `expected` impede que um flush que falhou em silencio passe: o
    contador de `flush_errors` é a defesa real em produção, e é
    exactamente o que o flush devolve se a escrita falhar.
    """
    written = await push_metrics.flush_once()
    if expected is not None:
        assert written == expected, (
            f"flush escreveu {written} linha(s), esperado {expected}"
        )
    return _rows()


# ------------------------------------------------------ taxonomia

@pytest.mark.parametrize(
    "status,error,expected",
    [
        (410, None, "expired"),
        (404, None, "expired"),
        (429, None, "rate_limited"),
        (400, None, "rejected"),
        (413, None, "rejected"),
        (500, None, "error"),
        (503, None, "error"),
        (None, "Read timed out", "timeout"),
        (None, "connection reset", "error"),
        (None, None, "error"),
    ],
)
def test_classify_push_outcome(status, error, expected):
    assert classify_push_outcome(status, error) == expected


# ------------------------------------------------------ caminho feliz

def test_accepted_is_recorded(monkeypatch):
    svc = _svc_configured(monkeypatch)
    _patch_webpush(monkeypatch)

    result = anyio.run(svc._send_single, SUB, {"title": "t"})
    assert result is True

    rows = anyio.run(_flush, 1)
    assert len(rows) == 1
    assert rows[0]["outcome"] == "accepted"
    assert rows[0]["attempts"] == 1
    assert rows[0]["user_id"] == 7
    assert rows[0]["latency_ms"] is not None


def test_kind_is_propagated(monkeypatch):
    svc = _svc_configured(monkeypatch)
    _patch_webpush(monkeypatch)

    anyio.run(svc._send_single, SUB, {"title": "t"}, "lead_alert")

    rows = anyio.run(_flush, 1)
    assert rows[0]["kind"] == "lead_alert"


# ------------------------------------------------------ expiradas

@pytest.mark.parametrize("status", [404, 410])
def test_expired_is_recorded_and_returned(monkeypatch, status):
    svc = _svc_configured(monkeypatch)
    _patch_webpush(monkeypatch, exc=_webpush_exception(status))

    result = anyio.run(svc._send_single, SUB, {"title": "t"})
    assert result == "expired", "o valor de retorno não pode mudar"

    rows = anyio.run(_flush, 1)
    assert rows[0]["outcome"] == "expired"
    assert rows[0]["http_status"] == status
    assert rows[0]["attempts"] == 1, "404/410 não faz retry"


def test_expired_does_not_retry(monkeypatch):
    """410 é terminal: insistir seria tráfegoonto ao serviço sem ganho."""
    svc = _svc_configured(monkeypatch)
    calls = _patch_webpush(monkeypatch, exc=_webpush_exception(410))

    anyio.run(svc._send_single, SUB, {"title": "t"})
    assert len(calls) == 1


# ------------------------------------------------------ retries

def test_retry_then_success_counts_attempts(monkeypatch):
    svc = _svc_configured(monkeypatch)
    attempts = {"n": 0}

    def _flaky(**kwargs):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise _webpush_exception(500)

    monkeypatch.setattr("backend.services.push_service.webpush", _flaky)

    result = anyio.run(svc._send_single, SUB, {"title": "t"})
    assert result is True

    rows = anyio.run(_flush, 1)
    assert rows[0]["outcome"] == "accepted"
    assert rows[0]["attempts"] == 2, "o painel precisa de saber que houve retry"


def test_retries_exhausted_is_an_error(monkeypatch):
    svc = _svc_configured(monkeypatch)
    calls = _patch_webpush(monkeypatch, exc=_webpush_exception(500))

    result = anyio.run(svc._send_single, SUB, {"title": "t"})
    assert result is False
    assert len(calls) == 3, "MAX_RETRIES = 3"

    rows = anyio.run(_flush, 1)
    assert rows[0]["outcome"] == "error"
    assert rows[0]["attempts"] == 3
    assert rows[0]["http_status"] == 500


def test_rate_limited_is_distinguished(monkeypatch):
    """429 é pressão do serviço, não um erro da subscrição."""
    svc = _svc_configured(monkeypatch)
    calls = _patch_webpush(
        monkeypatch, exc=_webpush_exception(429, headers={"Retry-After": "0"})
    )

    result = anyio.run(svc._send_single, SUB, {"title": "t"})
    assert result is False
    assert len(calls) == 3

    rows = anyio.run(_flush, 1)
    assert rows[0]["outcome"] == "rate_limited"
    assert rows[0]["http_status"] == 429


def test_rejected_on_4xx(monkeypatch):
    svc = _svc_configured(monkeypatch)
    _patch_webpush(monkeypatch, exc=_webpush_exception(400))

    result = anyio.run(svc._send_single, SUB, {"title": "t"})
    assert result is False

    rows = anyio.run(_flush, 1)
    assert rows[0]["outcome"] == "rejected"


def test_generic_exception_is_timeout(monkeypatch):
    svc = _svc_configured(monkeypatch)
    _patch_webpush(monkeypatch, exc=TimeoutError("Read timed out"))

    anyio.run(svc._send_single, SUB, {"title": "t"})

    rows = anyio.run(_flush, 1)
    assert rows[0]["outcome"] == "timeout"


# ------------------------------------------------------ not_configured

def test_not_configured_is_visible(monkeypatch):
    """O modo de falha silencioso tem de aparecer no painel."""
    svc = PushService()
    svc._configured = False

    result = anyio.run(svc._send_single, SUB, {"title": "t"})
    assert result is False

    rows = anyio.run(_flush, 1)
    assert rows[0]["outcome"] == "not_configured"
    assert rows[0]["attempts"] == 0


@pytest.mark.asyncio
async def test_send_to_user_records_not_configured(monkeypatch):
    """O early return de send_to_user impede _send_single de correr, logo
    o record tem de acontecer aqui."""
    svc = PushService()
    svc._configured = False

    sent = await svc.send_to_user(42, {"title": "t"}, "lead_alert")
    assert sent == 0

    rows = await _flush(1)
    assert len(rows) == 1
    assert rows[0]["outcome"] == "not_configured"
    assert rows[0]["user_id"] == 42
    assert rows[0]["kind"] == "lead_alert"


@pytest.mark.asyncio
async def test_broadcast_kinds_are_labelled_on_the_real_path(monkeypatch):
    """Regressao: os broadcasts so rotulavam o caminho `not_configured`.

    No caminho normal `send_to_category` chamava `send_to_user` sem `kind`, e
    `send_to_user` sem kind assume `custom`. O painel via tudo como
    notificacao de lead e perdia a separacao por tipo de envio.
    """
    svc = _svc_configured(monkeypatch)
    _patch_webpush(monkeypatch)

    async def _users(category):
        return [{"id": 42}]

    async def _subs():
        return [{"user_id": 42, "endpoint": "https://push.example/42",
                 "p256dh": "k", "auth": "a"}]

    async def _user_subs(user_id):
        return [{"endpoint": "https://push.example/42", "p256dh": "k", "auth": "a", "user_id": user_id}]

    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr(db_service, "get_users_interested_in", _users)
    monkeypatch.setattr(db_service, "get_all_push_subscriptions", _subs)
    monkeypatch.setattr(db_service, "get_user_push_subscriptions", _user_subs)
    monkeypatch.setattr(db_service, "remove_push_subscription", _noop)

    assert await svc.send_to_category("restaurants", {"title": "t"}) == 1
    assert await svc.send_to_all({"title": "t"}) == 1

    rows = await _flush(2)
    kinds = {r["kind"] for r in rows}
    assert kinds == {"category_broadcast", "broadcast"}, f"kinds errados: {kinds}"
    assert {r["outcome"] for r in rows} == {"accepted"}


# ------------------------------------------------------ robustez

def test_metrics_failure_does_not_break_delivery(monkeypatch):
    """Contrato mais importante: telemetria rota não pode impedir envio."""
    svc = _svc_configured(monkeypatch)
    _patch_webpush(monkeypatch)

    def _boom(**kwargs):
        raise RuntimeError("metrics backend em chamas")

    monkeypatch.setattr("backend.services.push_service.push_metrics.record", _boom)

    assert anyio.run(svc._send_single, SUB, {"title": "t"}) is True


def test_one_row_per_subscription(monkeypatch):
    """Uma subscrição = uma linha, mesmo com 3 tentativas."""
    svc = _svc_configured(monkeypatch)
    _patch_webpush(monkeypatch, exc=_webpush_exception(500))

    anyio.run(svc._send_single, SUB, {"title": "t"})

    rows = anyio.run(_flush, 1)
    assert len(rows) == 1, "as tentativas não são linhas separadas"
    assert rows[0]["attempts"] == 3


def test_debug_path_is_not_instrumented(monkeypatch):
    """Um broadcast de teste não pode distorcer a taxa de entrega."""
    svc = _svc_configured(monkeypatch)
    _patch_webpush(monkeypatch)

    result = svc._send_single_debug(SUB, {"title": "t"})
    assert result == {"ok": True}

    rows = anyio.run(_flush, 0)
    assert rows == [], "o caminho de debug não gera telemetria"


def test_error_is_truncated(monkeypatch):
    svc = _svc_configured(monkeypatch)
    _patch_webpush(monkeypatch, exc=ValueError("X" * 5000))

    anyio.run(svc._send_single, SUB, {"title": "t"})

    rows = anyio.run(_flush, 1)
    assert len(rows[0]["error"]) <= 300

"""Regressão: o Web Push deve repassar `urgency` via `headers`.

A versão instalada do pywebpush (2.x) não aceita o kwarg `urgency` em
`webpush()` — passá-lo fazia todo envio falhar com
"webpush() got an unexpected keyword argument 'urgency'".
"""

import anyio

from backend.services import push_service


def _fake_webpush_factory(calls: dict):
    def fake_webpush(**kwargs):
        calls.clear()
        calls.update(kwargs)
        return "ok"

    return fake_webpush


def _configured_service(monkeypatch):
    svc = push_service.push_service
    monkeypatch.setattr(svc, "_configured", True)
    monkeypatch.setattr(svc, "_vapid_private_key", "x")
    monkeypatch.setattr(svc, "_vapid_claims", {"sub": "mailto:test@test.com"})
    return svc


def test_send_single_uses_headers_not_urgency(monkeypatch):
    calls: dict = {}
    monkeypatch.setattr(push_service, "webpush", _fake_webpush_factory(calls))
    svc = _configured_service(monkeypatch)

    sub = {"endpoint": "https://example.invalid/ep", "p256dh": "a", "auth": "b"}
    assert anyio.run(svc._send_single, sub, {"title": "t"}) is True
    assert calls.get("headers") == {"Urgency": "high"}
    assert "urgency" not in calls


def test_send_single_debug_uses_headers_not_urgency(monkeypatch):
    calls: dict = {}
    monkeypatch.setattr(push_service, "webpush", _fake_webpush_factory(calls))
    svc = _configured_service(monkeypatch)

    sub = {"endpoint": "https://example.invalid/ep", "p256dh": "a", "auth": "b"}
    assert svc._send_single_debug(sub, {"title": "t"}) == {"ok": True}
    assert calls.get("headers") == {"Urgency": "high"}
    assert calls.get("ttl") == 3600
    assert "urgency" not in calls


def test_send_to_user_respects_push_enabled_flag(monkeypatch):
    """Com push_enabled desligado, não lê subscriptions nem envia nada."""
    svc = _configured_service(monkeypatch)
    calls: dict = {}
    monkeypatch.setattr(push_service, "webpush", _fake_webpush_factory(calls))

    async def _disabled(user_id):
        return False

    async def _boom(user_id):
        raise AssertionError("não devia ler subscriptions com push desligado")

    monkeypatch.setattr(push_service.db_service, "is_push_enabled", _disabled)
    monkeypatch.setattr(push_service.db_service, "get_user_push_subscriptions", _boom)

    assert anyio.run(svc.send_to_user, 7, {"title": "t"}, "lead_alert") == 0
    assert calls == {}


# ---------------------------------------------------------------------------
# 401/403 de VAPID inválido -> subscription morta removida da BD (Ponto 2)
# ---------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, status_code: int, text: str):
        self.status_code = status_code
        self.text = text
        self.headers: dict = {}


def _wire_subscription(monkeypatch, store):
    async def _enabled(user_id):
        return True

    async def _subs(user_id):
        return [{
            "endpoint": "https://example.invalid/dead",
            "p256dh": "a",
            "auth": "b",
            "user_id": user_id,
        }]

    async def _remove(user_id, endpoint):
        store.append((user_id, endpoint))
        return True

    monkeypatch.setattr(push_service.db_service, "is_push_enabled", _enabled)
    monkeypatch.setattr(push_service.db_service, "get_user_push_subscriptions", _subs)
    monkeypatch.setattr(push_service.db_service, "remove_push_subscription", _remove)


def test_vapid_403_removes_subscription(monkeypatch):
    from pywebpush import WebPushException

    svc = _configured_service(monkeypatch)

    def _boom(*args, **kwargs):
        raise WebPushException(
            "VAPID error", response=_FakeResponse(403, '{"reason":"VapidPkHashMismatch"}')
        )

    monkeypatch.setattr(push_service, "webpush", _boom)
    removed: list = []
    _wire_subscription(monkeypatch, removed)

    assert anyio.run(svc.send_to_user, 7, {"title": "t"}, "lead_alert") == 0
    assert removed == [(7, "https://example.invalid/dead")]


def test_vapid_401_removes_subscription(monkeypatch):
    from pywebpush import WebPushException

    svc = _configured_service(monkeypatch)

    def _boom(*args, **kwargs):
        raise WebPushException(
            "unauthorized", response=_FakeResponse(401, "UnauthorizedRegistration")
        )

    monkeypatch.setattr(push_service, "webpush", _boom)
    removed: list = []
    _wire_subscription(monkeypatch, removed)

    assert anyio.run(svc.send_to_user, 7, {"title": "t"}, "lead_alert") == 0
    assert removed == [(7, "https://example.invalid/dead")]


def test_is_dead_subscription_classifier():
    assert push_service._is_dead_subscription(403, "VapidPkHashMismatch")
    assert push_service._is_dead_subscription(401, "VAPID public key mismatch")
    assert push_service._is_dead_subscription(403, "UnauthorizedRegistration")
    assert push_service._is_dead_subscription(
        403,
        "the VAPID credentials in the authorization header do not correspond "
        "to the credentials used to create the subscriptions.",
    )
    assert not push_service._is_dead_subscription(403, "Forbidden")
    assert not push_service._is_dead_subscription(500, "vapid")
    assert not push_service._is_dead_subscription(None, "vapid")


def test_is_dead_subscription_empty_body_is_dead():
    """401/403 com corpo vazio = rejeição de credencial sem detalhe -> morta."""
    assert push_service._is_dead_subscription(401, "")
    assert push_service._is_dead_subscription(401, None)
    assert push_service._is_dead_subscription(403, "   ")
    # Um 404/410/500 com corpo vazio continua a NÃO ser tratado aqui.
    assert not push_service._is_dead_subscription(404, "")
    assert not push_service._is_dead_subscription(500, "")


def test_vapid_401_empty_body_removes_subscription(monkeypatch):
    """Reproduz o padrão de produção: 401 com body vazio remove a subscription."""
    from pywebpush import WebPushException

    svc = _configured_service(monkeypatch)

    def _boom(*args, **kwargs):
        raise WebPushException("Push failed: 401 Unauthorized", response=_FakeResponse(401, ""))

    monkeypatch.setattr(push_service, "webpush", _boom)
    removed: list = []
    _wire_subscription(monkeypatch, removed)

    assert anyio.run(svc.send_to_user, 7, {"title": "t"}, "lead_alert") == 0
    assert removed == [(7, "https://example.invalid/dead")]


def test_vapid_403_fcm_text_removes_subscription(monkeypatch):
    """O texto real do FCM ('do not correspond to the credentials') é mortal."""
    from pywebpush import WebPushException

    svc = _configured_service(monkeypatch)

    def _boom(*args, **kwargs):
        raise WebPushException(
            "Forbidden",
            response=_FakeResponse(
                403,
                "the VAPID credentials in the authorization header do not "
                "correspond to the credentials used to create the subscriptions.",
            ),
        )

    monkeypatch.setattr(push_service, "webpush", _boom)
    removed: list = []
    _wire_subscription(monkeypatch, removed)

    assert anyio.run(svc.send_to_user, 7, {"title": "t"}, "lead_alert") == 0
    assert removed == [(7, "https://example.invalid/dead")]


def test_generic_403_with_body_does_not_remove_subscription(monkeypatch):
    """Um 403 com corpo não-vazio e sem indício de VAPID NÃO remove."""
    from pywebpush import WebPushException

    svc = _configured_service(monkeypatch)
    monkeypatch.setattr(push_service, "MAX_RETRIES", 1)  # sem sleep de backoff

    def _boom(*args, **kwargs):
        raise WebPushException("forbidden", response=_FakeResponse(403, "Forbidden"))

    monkeypatch.setattr(push_service, "webpush", _boom)
    removed: list = []
    _wire_subscription(monkeypatch, removed)

    assert anyio.run(svc.send_to_user, 7, {"title": "t"}, "lead_alert") == 0
    assert removed == []

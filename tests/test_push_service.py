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

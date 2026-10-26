"""Testes do micro-worker VPS (sem rede): classificacao e deteccao de catch-all."""
import pytest

from backend.services import vps_worker_server as w


class FakeSMTP:
    target_code = 250
    random_code = 250
    fail = False

    def __init__(self, timeout=None):
        self.timeout = timeout

    def connect(self, host, port):
        if FakeSMTP.fail:
            raise OSError("unreachable")
        return 220, b"ok"

    def helo(self, name):
        return 250, b"ok"

    def mail(self, sender):
        return 250, b"ok"

    def rcpt(self, addr):
        if addr.startswith("probe-"):
            return FakeSMTP.random_code, b"rcpt"
        return FakeSMTP.target_code, b"rcpt"

    def quit(self):
        return 221, b"bye"

    def close(self):
        pass


@pytest.fixture(autouse=True)
def _patch(monkeypatch):
    monkeypatch.setattr(w, "_mx_host", lambda domain: "mx.test")
    monkeypatch.setattr(w.smtplib, "SMTP", FakeSMTP)
    FakeSMTP.target_code = 250
    FakeSMTP.random_code = 550
    FakeSMTP.fail = False


def _call():
    return w.validate_smtp(w.SMTPCheckRequest(email="a@test.com", domain="test.com"), "token")


def test_valid_when_target_accepted_and_random_rejected():
    out = _call()
    assert out["status"] == "valid"
    assert out["catch_all"] is False


def test_catch_all_when_both_accepted():
    FakeSMTP.random_code = 250
    out = _call()
    assert out["status"] == "catch_all"
    assert out["catch_all"] is True


def test_invalid_when_target_rejected():
    FakeSMTP.target_code = 550
    out = _call()
    assert out["status"] == "invalid"


def test_inconclusive_on_network_error():
    FakeSMTP.fail = True
    out = _call()
    assert out["status"] == "inconclusive"
    assert out["catch_all"] is False


def test_rejects_mismatched_domain():
    with pytest.raises(Exception):
        w.validate_smtp(w.SMTPCheckRequest(email="a@other.com", domain="test.com"), "token")


def test_verify_token_rejects_missing_config(monkeypatch):
    from fastapi import HTTPException

    monkeypatch.setattr(w, "VPS_WORKER_SECRET", "")
    with pytest.raises(HTTPException) as exc:
        w.verify_token("Bearer anything")
    assert exc.value.status_code == 503


def test_verify_token_rejects_wrong_token(monkeypatch):
    from fastapi import HTTPException

    monkeypatch.setattr(w, "VPS_WORKER_SECRET", "s3cret")
    with pytest.raises(HTTPException) as exc:
        w.verify_token("Bearer wrong")
    assert exc.value.status_code == 403
    assert w.verify_token("Bearer s3cret") == "s3cret"


# --------------------------- cliente HTTP (prober) ---------------------------


def _no_network(request):
    raise AssertionError("prober nao devia chamar a rede sem configuracao")


def test_prober_fails_closed_without_config(monkeypatch):
    from backend.services import vps_prober as p

    monkeypatch.delenv("VPS_WORKER_URL", raising=False)
    monkeypatch.delenv("VPS_WORKER_SECRET", raising=False)
    import httpx

    out = p.probe_smtp_via_vps(
        "a@test.com", "test.com", transport=httpx.MockTransport(_no_network)
    )
    assert out["status"] == "inconclusive"
    assert out["catch_all"] is False
    assert "ausentes" in out["error"]


def test_prober_passes_through_worker_response(monkeypatch):
    import httpx

    from backend.services import vps_prober as p

    monkeypatch.setenv("VPS_WORKER_URL", "https://worker.test")
    monkeypatch.setenv("VPS_WORKER_SECRET", "s3cret")
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = request.content
        return httpx.Response(
            200,
            json={"status": "catch_all", "catch_all": True, "code": 250},
        )

    out = p.probe_smtp_via_vps(
        "A@Test.com", "test.com", transport=httpx.MockTransport(handler)
    )
    assert out["status"] == "catch_all"
    assert seen["url"] == "https://worker.test/validate-smtp"
    assert seen["auth"] == "Bearer s3cret"
    assert b"a@test.com" in seen["body"]


def test_prober_maps_http_error_to_inconclusive(monkeypatch):
    import httpx

    from backend.services import vps_prober as p

    monkeypatch.setenv("VPS_WORKER_URL", "https://worker.test")
    monkeypatch.setenv("VPS_WORKER_SECRET", "s3cret")
    out = p.probe_smtp_via_vps(
        "a@test.com",
        "test.com",
        transport=httpx.MockTransport(lambda request: httpx.Response(500)),
    )
    assert out["status"] == "inconclusive"
    assert "HTTP 500" in out["error"]


def test_prober_maps_network_error_to_inconclusive(monkeypatch):
    import httpx

    from backend.services import vps_prober as p

    monkeypatch.setenv("VPS_WORKER_URL", "https://worker.test")
    monkeypatch.setenv("VPS_WORKER_SECRET", "s3cret")

    def boom(request):
        raise httpx.ConnectError("no route")

    out = p.probe_smtp_via_vps(
        "a@test.com", "test.com", transport=httpx.MockTransport(boom)
    )
    assert out["status"] == "inconclusive"
    assert out["catch_all"] is False


def test_prober_rejects_domain_mismatch_without_http(monkeypatch):
    import httpx

    from backend.services import vps_prober as p

    monkeypatch.setenv("VPS_WORKER_URL", "https://worker.test")
    monkeypatch.setenv("VPS_WORKER_SECRET", "s3cret")
    out = p.probe_smtp_via_vps(
        "a@other.com", "test.com", transport=httpx.MockTransport(_no_network)
    )
    assert out["status"] == "inconclusive"
    assert "mismatch" in out["error"]

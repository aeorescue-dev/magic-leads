"""
Regressão: fluxo completo de recuperação de senha (tolerância zero).
Cria token valido -> valida -> consome -> confirma login com a nova senha.
Usa o mesmo formato de payload do frontend.
"""
import logging

from fastapi.testclient import TestClient

from backend.main import app
from backend.services.db import DatabaseService

TEST_EMAIL = "pytest-reset@magicleads.app"
OLD_PASS = "senhaAntiga1"
NEW_PASS = "novaSenha123"


def _capture_reset_log(logger_name="garimpador"):
    """Captura os logs do garimpador para extrair o link impresso (modo logs)."""
    captured = []

    class CaptureHandler(logging.Handler):
        def emit(self, record):
            captured.append(self.format(record))

    handler = CaptureHandler()
    logging.getLogger(logger_name).addHandler(handler)
    return captured, handler


def test_forgot_password_full_flow(monkeypatch):
    """Fluxo completo: cria token -> valida -> consome -> login com a nova senha.

    O transporte de e-mail é interceptado para capturar o token. Isolar o envio
    mantém este teste focado no ciclo de vida do token (o transporte tem os seus
    próprios testes) e não depende de existir canal de e-mail configurado.
    """
    client = TestClient(app)

    # Registra usuário real
    r = client.post(
        "/api/auth/register",
        json={"email": TEST_EMAIL, "password": OLD_PASS, "company_name": "Pytest"},
    )
    assert r.status_code == 200, r.text

    # Email inexistente não revela existência (padrão de segurança)
    r = client.post("/api/auth/forgot-password", json={"email": "ghost@magicleads.app"})
    assert r.status_code == 200, r.text

    # Intercepta o envio para capturar o token (o endpoint ignora o retorno,
    # preservando a resposta anti-enumeracao)
    sent = {}

    async def _capture(email, token):
        sent["email"] = email
        sent["token"] = token
        return True

    monkeypatch.setattr("backend.main.db_service.send_password_reset_email", _capture)

    r = client.post("/api/auth/forgot-password", json={"email": TEST_EMAIL})
    assert r.status_code == 200, r.text
    assert r.json().get("status") == "ok"

    token = sent.get("token")
    assert token, "token não foi enviado"
    assert sent["email"] == TEST_EMAIL

    # Redefine a senha com o mesmo payload do frontend
    r = client.post(
        "/api/auth/reset-password",
        json={"token": token, "new_password": NEW_PASS, "confirm_password": NEW_PASS},
    )
    assert r.status_code == 200, r.text
    assert r.json().get("status") == "ok"

    # Token já consumido não pode ser reutilizado
    r = client.post(
        "/api/auth/reset-password",
        json={"token": token, "new_password": "outra123", "confirm_password": "outra123"},
    )
    assert r.status_code == 400, r.text

    # Login com a NOVA senha funciona
    r = client.post("/api/auth/login", json={"email": TEST_EMAIL, "password": NEW_PASS})
    assert r.status_code == 200, r.text

    # Login com a senha ANTIGA falha
    r = client.post("/api/auth/login", json={"email": TEST_EMAIL, "password": OLD_PASS})
    assert r.status_code in (400, 401), r.text


def test_forgot_password_no_email_reveal():
    client = TestClient(app)
    r = client.post("/api/auth/forgot-password", json={"email": "nunca-existiu@magicleads.app"})
    assert r.status_code == 200, r.text


def test_reset_password_invalid_token():
    client = TestClient(app)
    r = client.post(
        "/api/auth/reset-password",
        json={"token": "token-invalido", "new_password": NEW_PASS, "confirm_password": NEW_PASS},
    )
    assert r.status_code == 400, r.text


def test_reset_password_mismatch_and_short():
    client = TestClient(app)
    token = "x"

    r = client.post(
        "/api/auth/reset-password",
        json={"token": token, "new_password": "abc123", "confirm_password": "abc124"},
    )
    assert r.status_code == 422, r.text
    assert "não coincidem" in r.json().get("detail", "")

    r = client.post(
        "/api/auth/reset-password",
        json={"token": token, "new_password": "123", "confirm_password": "123"},
    )
    assert r.status_code == 422, r.text


def test_reset_password_empty_payload_422():
    client = TestClient(app)
    r = client.post("/api/auth/forgot-password", json={})
    assert r.status_code == 422, r.text


def test_no_email_channel_does_not_leak_token(monkeypatch):
    """Sem canal de e-mail, o token NÃO pode aparecer em log (fail-closed).

    Regressão de segurança: o "modo logs" imprimia o link de reset em claro.
    Em produção os logs são agregados e legíveis por qualquer pessoa com acesso
    ao Railway, o que transformava cada reset num takeover de conta.
    """
    monkeypatch.setattr("backend.services.db.settings", type("S", (), {
        "FRONTEND_URL": "https://app.magicleads.com",
        "EMAIL_API_KEY": "",
        "EMAIL_FROM": "",
        "SMTP_HOST": "smtp.gmail.com",
        "SMTP_PORT": 587,
        "SMTP_USER": "",
        "SMTP_PASS": "",
        "SMTP_FROM": "helpmagicleads@gmail.com",
    })())
    captured, handler = _capture_reset_log()
    try:
        ok = DatabaseService().send_password_reset_email("logs-test@magicleads.app", "tok123")
    finally:
        logging.getLogger("garimpador").removeHandler(handler)

    joined = "\n".join(captured)
    assert ok is False, "sem canal de e-mail o envio deve falhar, não fingir sucesso"
    # O token e o link NUNCA podem estar em log
    assert "tok123" not in joined, "TOKEN VAZADO EM LOG"
    assert "reset-password?token=" not in joined, "LINK DE RESET VAZADO EM LOG"
    # O operador vê a causa, sem conteúdo do token
    assert "Nenhum canal de e-mail configurado" in joined
    assert "NAO foi gerado" in joined


def test_smtp_auth_failure_logs_detailed_error(monkeypatch, capsys):
    """Falha de autenticação SMTP: log detalhado com código 535, SEM vazar o token."""
    import smtplib

    class FakeAuthError(smtplib.SMTPAuthenticationError):
        def __init__(self):
            super().__init__(535, b"5.7.8 Username and Password not accepted")

    def _raise_auth(*args, **kwargs):
        raise FakeAuthError()

    monkeypatch.setattr("backend.services.db.settings", type("S", (), {
        "FRONTEND_URL": "https://app.magicleads.com",
        "EMAIL_API_KEY": "",
        "EMAIL_FROM": "",
        "SMTP_HOST": "smtp.gmail.com",
        "SMTP_PORT": 465,
        "SMTP_USER": "helpmagicleads@gmail.com",
        "SMTP_PASS": "senha-errada",
        "SMTP_FROM": "helpmagicleads@gmail.com",
    })())
    monkeypatch.setattr("backend.services.db._SmtpConnect", _raise_auth)

    captured, handler = _capture_reset_log()
    try:
        ok = DatabaseService().send_password_reset_email("authfail@magicleads.app", "authtok")
    finally:
        logging.getLogger("garimpador").removeHandler(handler)

    joined = "\n".join(captured) + "\n" + capsys.readouterr().out
    # Diagnóstico útil ao operador preservado
    assert "FALHA DE AUTENTICAÇÃO SMTP" in joined
    assert "535" in joined
    assert "App Password inválida" in joined
    # Mas o token não pode vazar
    assert ok is False
    assert "authtok" not in joined, "TOKEN VAZADO EM LOG"
    assert "reset-password?token=authtok" not in joined


def test_smtp_failure_does_not_leak_token(monkeypatch):
    """SMTP configurado mas aligação falha: log da causa, sem token em log."""
    monkeypatch.setattr("backend.services.db.settings", type("S", (), {
        "FRONTEND_URL": "https://app.magicleads.com",
        "EMAIL_API_KEY": "",
        "EMAIL_FROM": "",
        "SMTP_HOST": "smtp.nenhum.server.invalido",
        "SMTP_PORT": 587,
        "SMTP_USER": "user",
        "SMTP_PASS": "pass",
        "SMTP_FROM": "",
    })())
    captured, handler = _capture_reset_log()
    try:
        ok = DatabaseService().send_password_reset_email("fallback@magicleads.app", "fallbacktok")
    finally:
        logging.getLogger("garimpador").removeHandler(handler)

    joined = "\n".join(captured)
    assert ok is False
    assert "fallbacktok" not in joined, "TOKEN VAZADO EM LOG"
    assert "reset-password?token=fallbacktok" not in joined


class FakeResendResponse:
    def __init__(self, status_code, text="", json_data=None):
        self.status_code = status_code
        self.text = text
        self._json = json_data or {}

    def json(self):
        return self._json


def test_forgot_password_endpoint_resend_full_flow(monkeypatch, capsys):
    """Integração local: register -> forgot-password com EMAIL_API_KEY ativo.

    Simula o endpoint da Resend validando o payload que o backend monta
    (from/to/subject/body com o link) e responde 200. O endpoint deve
    responder 200 sem cair no fallback de logs e sem ERRO EMAIL DETALHADO.
    """
    from fastapi.testclient import TestClient

    monkeypatch.setattr("backend.services.db.settings", type("S", (), {
        "EMAIL_API_KEY": "re_INTEGRATION",
        "EMAIL_FROM": "Magic Leads <noreply@seudominio.com>",
        "FRONTEND_URL": "",
        "SMTP_HOST": "", "SMTP_PORT": 465,
        "SMTP_USER": "", "SMTP_PASS": "", "SMTP_FROM": "",
    })())

    received = {}

    def fake_resend_post(url, headers=None, json=None, timeout=None):
        received["url"] = url
        received["auth"] = headers.get("Authorization")
        received["content_type"] = headers.get("Content-Type")
        received["payload"] = json
        # Simula a Resend: qualquer payload malformado aqui devolveria 422;
        # como o payload do backend é válido, responde 200.
        return FakeResendResponse(200, json_data={"id": "integration-id-1"})

    monkeypatch.setattr("backend.services.db.httpx.post", fake_resend_post)

    client = TestClient(app)
    email = "resend-flow@magicleads.app"

    # registra usuário real (mesmo fluxo do frontend)
    r = client.post("/api/auth/register", json={
        "email": email, "password": OLD_PASS, "company_name": "Intel Teste",
    })
    assert r.status_code == 200, r.text
    assert r.json()["user"]["email"] == email

    out_before = capsys.readouterr().out
    del out_before

    # dispara recuperação de senha
    r = client.post("/api/auth/forgot-password", json={"email": email})
    assert r.status_code == 200, r.text
    assert r.json().get("status") == "ok"

    out = capsys.readouterr().out

    # chamou a Resend corretamente
    assert received["url"] == "https://api.resend.com/emails"
    assert received["auth"] == "Bearer re_INTEGRATION"
    assert received["content_type"] == "application/json"
    body = received["payload"]
    assert body["from"] == "Magic Leads <noreply@seudominio.com>"
    assert body["to"] == [email]
    assert "Recuperação de senha" in body["subject"]
    assert body["text"]
    assert "reset-password?token=" in body["text"]

    # sucesso: sem ERRO e sem cair no fallback de logs
    assert "via Resend" in out
    assert "ERRO EMAIL DETALHADO" not in out
    assert "link de teste" not in out


def _resend_settings(**overrides):
    base = {
        "FRONTEND_URL": "https://app.magicleads.com",
        "EMAIL_API_KEY": "re_test_123",
        "EMAIL_FROM": "Magic Leads <noreply@magicleads.com>",
        "SMTP_HOST": "smtp.gmail.com",
        "SMTP_PORT": 465,
        "SMTP_USER": "",
        "SMTP_PASS": "",
        "SMTP_FROM": "",
    }
    base.update(overrides)
    return type("S", (), base)()


def test_resend_api_success_sends_email(monkeypatch, capsys):
    """Com EMAIL_API_KEY, o envio vai pela API HTTPS da Resend (porta 443) e não cai em logs."""
    monkeypatch.setattr("backend.services.db.settings", _resend_settings())
    called = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        called["url"] = url
        called["auth"] = headers["Authorization"]
        called["to"] = json["to"]
        called["subject"] = json["subject"]
        return FakeResendResponse(200, json_data={"id": "abc123"})

    monkeypatch.setattr("backend.services.db.httpx.post", fake_post)

    ok = DatabaseService().send_password_reset_email("user@example.com", "tokresend")
    out = capsys.readouterr().out

    assert ok is True
    assert called["url"] == "https://api.resend.com/emails"
    assert called["auth"] == "Bearer re_test_123"
    assert called["to"] == ["user@example.com"]
    assert "Recuperação de senha" in called["subject"]
    assert "via Resend" in out
    assert "link de teste" not in out


def test_resend_api_rejection_does_not_leak_token(monkeypatch, capsys):
    """Se a Resend recusar (ex.: domínio não verificado), diagnostica mas NÃO expõe o token."""
    monkeypatch.setattr("backend.services.db.settings", _resend_settings(EMAIL_API_KEY="re_bad"))

    def fake_post(url, headers=None, json=None, timeout=None):
        return FakeResendResponse(403, text='{"message":"domain not verified"}')

    monkeypatch.setattr("backend.services.db.httpx.post", fake_post)

    captured, handler = _capture_reset_log()
    try:
        ok = DatabaseService().send_password_reset_email("user@example.com", "tokrej")
    finally:
        logging.getLogger("garimpador").removeHandler(handler)

    out = "\n".join(captured) + "\n" + capsys.readouterr().out
    # Diagnóstico preservado
    assert "ERRO EMAIL DETALHADO" in out
    assert "403" in out
    assert "domain not verified" in out
    # Sem fuga de credencial
    assert ok is False
    assert "tokrej" not in out, "TOKEN VAZADO EM LOG"
    assert "reset-password?token=tokrej" not in out
    assert "link de teste" not in out

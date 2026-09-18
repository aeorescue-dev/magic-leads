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


def test_forgot_password_full_flow():
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

    # Extrai o link impresso nos logs (modo logs, zero custo)
    captured, handler = _capture_reset_log()
    try:
        r = client.post("/api/auth/forgot-password", json={"email": TEST_EMAIL})
        assert r.status_code == 200, r.text
        assert r.json().get("status") == "ok"
    finally:
        logging.getLogger("garimpador").removeHandler(handler)

    token = None
    for line in captured:
        if "reset-password?token=" in line:
            token = line.split("reset-password?token=")[1].strip()
            break
    assert token, "token não encontrado no link impresso nos logs"
    # O link impresso deve ser legível e conter o token extraído
    assert any("Link   :" in line and token in line for line in captured), "linha 'Link:' ausente/ilegível"

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


def test_logs_mode_prints_readable_link(monkeypatch):
    """Sem canal de e-mail configurado, o link de reset é impresso de forma legível nos logs."""
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
        assert ok is True
    finally:
        logging.getLogger("garimpador").removeHandler(handler)

    joined = "\n".join(captured)
    assert "PASSWORD RESET" in joined
    assert "logs-test@magicleads.app" in joined
    assert "https://app.magicleads.com/reset-password?token=tok123" in joined

    # O link é um record próprio (linha única), copiável sem fricção
    link_lines = [line for line in captured if line.strip().startswith("Link") and "reset-password?token=tok123" in line]
    assert link_lines, "link não encontrado em linha própria"
    assert len(link_lines) == 1
    assert link_lines[0].endswith("reset-password?token=tok123"), "token deve ser o fim da linha"


def test_smtp_auth_failure_logs_detailed_error(monkeypatch, capsys):
    """Falha de autenticação SMTP deve imprimir tipo + código exato (535) e cair para modo logs."""
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
        assert ok is True
    finally:
        logging.getLogger("garimpador").removeHandler(handler)

    joined = "\n".join(captured) + "\n" + capsys.readouterr().out
    assert "FALHA DE AUTENTICAÇÃO SMTP" in joined
    assert "535" in joined
    assert "App Password inválida" in joined
    # ainda cai em modo logs
    assert "PASSWORD RESET" in joined
    assert "reset-password?token=authtok" in joined


def test_smtp_failure_falls_back_to_logs(monkeypatch):
    """Se SMTP_HOST estiver configurado mas falhar, a função cai para modo logs e não levanta exceção."""
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
        assert ok is True
    finally:
        logging.getLogger("garimpador").removeHandler(handler)

    joined = "\n".join(captured)
    assert "PASSWORD RESET" in joined
    assert "fallback@magicleads.app" in joined
    assert any("reset-password?token=fallbacktok" in line for line in captured)


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


def test_resend_api_rejection_falls_back_to_logs(monkeypatch, capsys):
    """Se a Resend recusar (ex.: domínio não verificado), imprime o corpo do erro e cai em logs."""
    monkeypatch.setattr("backend.services.db.settings", _resend_settings(EMAIL_API_KEY="re_bad"))

    def fake_post(url, headers=None, json=None, timeout=None):
        return FakeResendResponse(403, text='{"message":"domain not verified"}')

    monkeypatch.setattr("backend.services.db.httpx.post", fake_post)

    captured, handler = _capture_reset_log()
    try:
        ok = DatabaseService().send_password_reset_email("user@example.com", "tokrej")
        assert ok is True
    finally:
        logging.getLogger("garimpador").removeHandler(handler)

    out = "\n".join(captured) + "\n" + capsys.readouterr().out
    assert "ERRO EMAIL DETALHADO" in out
    assert "403" in out
    assert "domain not verified" in out
    # caiu em modo logs, mantendo o fluxo de reset utilizável
    assert "link de teste" in out
    assert "reset-password?token=tokrej" in out

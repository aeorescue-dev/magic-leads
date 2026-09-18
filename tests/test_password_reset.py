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
    """Sem SMTP configurado, o link de reset é impresso de forma legível nos logs."""
    monkeypatch.setattr("backend.services.db.settings", type("S", (), {
        "FRONTEND_URL": "https://app.magicleads.com",
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


def test_smtp_failure_falls_back_to_logs(monkeypatch):
    """Se SMTP_HOST estiver configurado mas falhar, a função cai para modo logs e não levanta exceção."""
    monkeypatch.setattr("backend.services.db.settings", type("S", (), {
        "FRONTEND_URL": "https://app.magicleads.com",
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

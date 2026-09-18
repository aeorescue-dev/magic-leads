"""
Regressão: fluxo completo de recuperação de senha (tolerância zero).
Cria token valido -> valida -> consome -> confirma login com a nova senha.
Usa o mesmo formato de payload do frontend.
"""
import logging

from fastapi.testclient import TestClient
from backend.main import app

TEST_EMAIL = "pytest-reset@magicleads.app"
OLD_PASS = "senhaAntiga1"
NEW_PASS = "novaSenha123"


def _capture_mock_email_log(logger_name="garimpador"):
    """Captura a linha do email mock para extrair o token enviado."""
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

    # Extrai o token do email mock
    captured, handler = _capture_mock_email_log()
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
    assert token, "token não encontrado no email mock"

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
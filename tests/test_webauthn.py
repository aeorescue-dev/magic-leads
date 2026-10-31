"""WebAuthn/Passkeys — endpoints, challenge single-use e sessão A2.

A criptografia real é exercitada no e2e com virtual authenticator. Aqui
mockamos a verificação da biblioteca para testar o glue (DB, challenge,
sessão, autorização e falhas).
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from webauthn.helpers import bytes_to_base64url

import backend.main as main_module
from backend.main import _hash_token, app
from backend.services.db import db_service, get_connection

EMAIL = "pytest-passkey@magicleads.app"
TOKEN = "pytest-passkey-token"
ORIGIN = "https://www.magicleads.app"


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def _user() -> int:
    svc = db_service._service
    user = svc.get_user_by_email(EMAIL) or svc.create_user(
        EMAIL, "pytest-hash", "Pytest Passkey", plan="pro",
        subscription_status="active",
    )
    try:
        svc.create_user_session(user["id"], _hash_token(TOKEN), "Pytest", None)
    except Exception:
        pass
    svc.extend_access(user["id"], days=7)
    # Base limpa para o teste.
    conn = get_connection()
    try:
        conn.execute("DELETE FROM webauthn_credentials WHERE user_id = ?", (user["id"],))
        conn.commit()
    finally:
        conn.close()
    return user["id"]


def _headers() -> dict:
    return {"Authorization": f"Bearer {TOKEN}", "Origin": ORIGIN}


def _client_data(challenge: str) -> str:
    raw = json.dumps(
        {"type": "webauthn.create", "challenge": challenge, "origin": ORIGIN}
    ).encode()
    return bytes_to_base64url(raw)


def test_register_options_requires_auth(client):
    assert client.post("/api/auth/webauthn/register/options").status_code == 401


def test_register_options_and_verify_store_public_key(client, monkeypatch):
    user_id = _user()
    r = client.post(
        "/api/auth/webauthn/register/options", headers=_headers()
    )
    assert r.status_code == 200, r.text
    options = r.json()
    challenge = options["challenge"]
    assert options["rp"]["id"] == main_module.settings.WEBAUTHN_RP_ID
    assert options["user"]["id"]

    verified = SimpleNamespace(
        credential_id=b"credential-bytes",
        credential_public_key=b"public-key-bytes",
        sign_count=0,
        aaguid="00000000-0000-0000-0000-000000000000",
    )
    monkeypatch.setattr(
        main_module, "verify_registration_response", lambda **_k: verified
    )

    payload = {
        "id": "credential-bytes-b64",
        "rawId": "credential-bytes-b64",
        "type": "public-key",
        "response": {
            "clientDataJSON": _client_data(challenge),
            "attestationObject": "att",
            "transports": ["internal"],
        },
    }
    r = client.post(
        "/api/auth/webauthn/register/verify",
        headers=_headers(),
        json=payload,
    )
    assert r.status_code == 200, r.text

    rows = db_service._service.list_webauthn_credentials(user_id)
    assert len(rows) == 1
    assert rows[0]["credential_id"] == bytes_to_base64url(b"credential-bytes")
    assert rows[0]["device_label"]

    # Challenge é de uso único.
    again = client.post(
        "/api/auth/webauthn/register/verify",
        headers=_headers(),
        json=payload,
    )
    assert again.status_code == 400


def test_login_options_does_not_enumerate_accounts(client):
    r = client.post(
        "/api/auth/webauthn/login/options",
        json={"email": "ghost@magicleads.app"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["challenge"]


def test_login_verify_creates_session(client, monkeypatch):
    user_id = _user()
    credential_id = bytes_to_base64url(b"login-credential")
    db_service._service.add_webauthn_credential(
        user_id=user_id,
        credential_id=credential_id,
        public_key=bytes_to_base64url(b"login-public-key"),
        sign_count=3,
        transports=json.dumps(["internal"]),
        device_label="Pytest",
    )

    challenge = "login-challenge-123"
    db_service._service.create_webauthn_challenge(challenge, "auth", user_id)

    class FakeVerified:
        new_sign_count = 4

    monkeypatch.setattr(
        main_module, "verify_authentication_response", lambda **_k: FakeVerified()
    )

    r = client.post(
        "/api/auth/webauthn/login/verify",
        json={
            "id": credential_id,
            "rawId": credential_id,
            "type": "public-key",
            "response": {
                "clientDataJSON": _client_data(challenge),
                "authenticatorData": "auth-data",
                "signature": "sig",
                "userHandle": None,
            },
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["token"]
    assert body["user"]["id"] == user_id

    me = client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {body['token']}"}
    )
    assert me.status_code == 200

    stored = db_service._service.get_webauthn_credential(credential_id)
    assert stored["sign_count"] == 4


def test_login_verify_rejects_unknown_credential(client):
    challenge = "auth-unknown"
    db_service._service.create_webauthn_challenge(challenge, "auth")
    r = client.post(
        "/api/auth/webauthn/login/verify",
        json={
            "id": "does-not-exist",
            "response": {"clientDataJSON": _client_data(challenge)},
        },
    )
    assert r.status_code == 401


def test_list_and_delete_passkeys(client):
    user_id = _user()
    credential_id = bytes_to_base64url(b"list-delete-credential")
    db_service._service.add_webauthn_credential(
        user_id=user_id,
        credential_id=credential_id,
        public_key=bytes_to_base64url(b"list-delete-public-key"),
        sign_count=1,
        transports=json.dumps(["internal"]),
        device_label="Pytest",
    )
    r = client.get("/api/users/me/passkeys", headers=_headers())
    assert r.status_code == 200
    passkeys = r.json()["passkeys"]
    assert passkeys

    credential_id = passkeys[0]["credential_id"]
    assert client.delete(
        f"/api/users/me/passkeys/{credential_id}", headers=_headers()
    ).status_code == 200
    assert client.delete(
        f"/api/users/me/passkeys/{credential_id}", headers=_headers()
    ).status_code == 404

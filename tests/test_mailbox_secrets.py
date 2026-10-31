"""Encriptação em repouso dos auth_ref (OAuth refresh tokens)."""

from __future__ import annotations

import json

from cryptography.fernet import Fernet

from backend.services import secrets
from backend.services.db import db_service, get_connection
from backend.services.gmail import parse_auth_ref


def test_encrypt_decrypt_roundtrip(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("MAILBOX_SECRET_KEY", key)
    raw = json.dumps({"client_id": "c", "refresh_token": "r"})
    enc = secrets.encrypt_secret(raw)
    assert enc.startswith("enc:v1:")
    assert "refresh_token" not in enc
    assert secrets.decrypt_secret(enc) == raw
    assert parse_auth_ref(enc)["refresh_token"] == "r"


def test_sem_chave_mantem_texto_simples(monkeypatch):
    monkeypatch.delenv("MAILBOX_SECRET_KEY", raising=False)
    raw = json.dumps({"refresh_token": "r"})
    assert secrets.encrypt_secret(raw) == raw
    assert parse_auth_ref(raw)["refresh_token"] == "r"


def test_upsert_grava_encriptado(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("MAILBOX_SECRET_KEY", key)
    email = "enc-box@example.com"
    conn = get_connection()
    try:
        conn.execute("DELETE FROM sending_mailboxes WHERE email=?", (email,))
        conn.commit()
    finally:
        conn.close()

    row = db_service._service.upsert_sending_mailbox(
        email=email,
        auth_ref=json.dumps({"client_id": "c", "refresh_token": "secret-token"}),
    )
    assert row
    assert row["auth_ref"].startswith("enc:v1:")
    assert "secret-token" not in row["auth_ref"]
    assert parse_auth_ref(row["auth_ref"])["refresh_token"] == "secret-token"

    conn = get_connection()
    try:
        conn.execute("DELETE FROM sending_mailboxes WHERE email=?", (email,))
        conn.commit()
    finally:
        conn.close()

"""Regressao: o refresh token do AMBIENTE tem de vencer o `auth_ref` da BD.

Bug real: ao adicionar o scope `gmail.readonly`, o token foi atualizado no
Railway mas o codigo continuava a usar a copia antiga guardada em
`sending_mailboxes.auth_ref` — o sync devolvia `no_permission` para sempre.
"""
from __future__ import annotations

import json

from backend.services import inbox_sync
from backend.services.gmail import GmailSender


def _mailbox(email: str, rt_in_db: str) -> dict:
    return {
        "email": email,
        "auth_ref": json.dumps({
            "client_id": "cid",
            "client_secret": "csec",
            "refresh_token": rt_in_db,
        }),
    }


def test_inbox_sync_prefers_env_token(monkeypatch):
    monkeypatch.setenv("GMAIL_REFRESH_TOKEN_PAMELA", "NOVO_TOKEN")
    creds = inbox_sync._credentials(_mailbox("pamela@magicleads.app", "TOKEN_ANTIGO"))
    assert creds is not None
    assert creds["refresh_token"] == "NOVO_TOKEN"


def test_inbox_sync_falls_back_to_auth_ref(monkeypatch):
    monkeypatch.delenv("GMAIL_REFRESH_TOKEN_PAMELA", raising=False)
    creds = inbox_sync._credentials(_mailbox("pamela@magicleads.app", "TOKEN_ANTIGO"))
    assert creds is not None
    assert creds["refresh_token"] == "TOKEN_ANTIGO"


def test_gmail_sender_prefers_env_token(monkeypatch):
    monkeypatch.setenv("GMAIL_REFRESH_TOKEN_PEDRO", "NOVO_TOKEN")
    creds = GmailSender()._credentials(_mailbox("pedro@magicleads.app", "ANTIGO"))
    assert creds["refresh_token"] == "NOVO_TOKEN"


def test_gmail_sender_falls_back_to_auth_ref(monkeypatch):
    monkeypatch.delenv("GMAIL_REFRESH_TOKEN_PEDRO", raising=False)
    creds = GmailSender()._credentials(_mailbox("pedro@magicleads.app", "ANTIGO"))
    assert creds["refresh_token"] == "ANTIGO"

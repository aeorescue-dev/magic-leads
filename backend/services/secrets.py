"""Encriptação em repouso dos segredos das caixas (OAuth refresh tokens).

`MAILBOX_SECRET_KEY` deve ser uma chave Fernet (base64, 32 bytes). Sem chave,
os valores ficam como estavam (compatibilidade); com chave, tudo o que é
gravado por `upsert_sending_mailbox` fica com o prefixo `enc:v1:` e é
desencriptado na leitura pelo `gmail.parse_auth_ref`.
"""
from __future__ import annotations

import os
from typing import Optional

PREFIX = "enc:v1:"


def _fernet():
    key = (os.getenv("MAILBOX_SECRET_KEY") or "").strip()
    if not key:
        return None
    try:
        from cryptography.fernet import Fernet  # import local: dependência opcional

        return Fernet(key.encode())
    except Exception:
        return None


def is_encrypted(value: Optional[str]) -> bool:
    return bool(value) and str(value).startswith(PREFIX)


def encrypt_secret(value: Optional[str]) -> Optional[str]:
    if not value or is_encrypted(value):
        return value
    f = _fernet()
    if not f:
        return value
    return PREFIX + f.encrypt(str(value).encode()).decode()


def decrypt_secret(value: Optional[str]) -> Optional[str]:
    if not value or not is_encrypted(value):
        return value
    f = _fernet()
    if not f:
        raise RuntimeError(
            "auth_ref encriptado mas MAILBOX_SECRET_KEY está ausente/inválida"
        )
    return f.decrypt(str(value)[len(PREFIX):].encode()).decode()

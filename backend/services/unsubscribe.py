"""Token assinado e URL de opt-out do outbound (CAN-SPAM / List-Unsubscribe).

O token e' `base64url(email) + "." + hmac`, para o link nao expor o e-mail em
claro e nao ser forjavel. Sem segredo configurado nada e' assinado (fail-closed):
o e-mail continua a ter a instrucao "reply unsubscribe", que e' um mecanismo de
opt-out valido; o link so' aparece quando ha' segredo.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
from typing import Optional

from ..config import settings

PUBLIC_BASE_URL = "https://www.magicleads.app"
UNSUBSCRIBE_PATH = "/unsubscribe"


def _secret() -> str:
    return (
        getattr(settings, "UNSUBSCRIBE_SECRET", "")
        or getattr(settings, "PUSH_CLICK_SECRET", "")
        or getattr(settings, "CRON_SECRET", "")
        or ""
    )


def _b64(email: str) -> str:
    return base64.urlsafe_b64encode(email.encode("utf-8")).decode("ascii").rstrip("=")


def _unb64(value: str) -> Optional[str]:
    try:
        padded = value + "=" * (-len(value) % 4)
        return base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
    except Exception:  # noqa: BLE001
        return None


def sign_email(email: str) -> str:
    secret = _secret()
    if not secret or not email:
        return ""
    message = f"unsubscribe:{email.strip().lower()}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()[:24]


def make_token(email: str) -> str:
    sig = sign_email(email)
    if not sig:
        return ""
    return f"{_b64(email.strip().lower())}.{sig}"


def verify_token(token: str) -> Optional[str]:
    """Devolve o e-mail se a assinatura for valida; None caso contrario."""
    if not token or "." not in token:
        return None
    payload, _, sig = token.rpartition(".")
    email = _unb64(payload)
    if not email or "@" not in email:
        return None
    expected = sign_email(email)
    if not expected or not hmac.compare_digest(expected, sig):
        return None
    return email


def unsubscribe_url(email: str) -> str:
    token = make_token(email)
    if not token:
        return f"{PUBLIC_BASE_URL}{UNSUBSCRIBE_PATH}"
    return f"{PUBLIC_BASE_URL}{UNSUBSCRIBE_PATH}?token={token}"

"""Gmail API sender (Outbound Frio - Fase 2).

Envia e-mail real via Google Workspace/Gmail API usando OAuth2 (refresh token).
As credenciais por caixa vivem em `sending_mailboxes.auth_ref` (JSON:
{"client_id","client_secret","refresh_token"}); quando ausentes cai nas env vars
globais GMAIL_CLIENT_ID/GMAIL_CLIENT_SECRET/GMAIL_REFRESH_TOKEN.

Fail-soft: qualquer falha devolve SendResult(success=False, error=...) e nunca
levanta. Nada aqui toca Dashboard, ingestao, Landing, Push ou Resend.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import time
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from typing import Optional

import httpx

from ..config import settings
from ..utils.logger import logger


@dataclass
class SendResult:
    success: bool
    provider_id: Optional[str] = None
    error: Optional[str] = None
    provider: str = "gmail"
    http_status: Optional[int] = None


def parse_auth_ref(auth_ref: Optional[str]) -> dict:
    """Extrai credenciais OAuth de `sending_mailboxes.auth_ref` (JSON ou vazio)."""
    if not auth_ref:
        return {}
    try:
        data = json.loads(auth_ref)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def build_raw_message(
    to_email: str,
    subject: str,
    body_text: str,
    from_email: str,
    from_name: Optional[str] = None,
) -> str:
    """Constroi uma mensagem MIME em base64url (formato exigido pela API)."""
    msg = EmailMessage()
    msg["To"] = to_email
    msg["From"] = f"{from_name} <{from_email}>" if from_name else from_email
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=False)
    msg["Message-ID"] = make_msgid(domain=from_email.split("@")[-1] if "@" in from_email else None)
    msg.set_content(body_text)
    return base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")


class GmailSender:
    def __init__(self) -> None:
        self.token_url = getattr(settings, "GMAIL_TOKEN_URL", "https://oauth2.googleapis.com/token")
        self.api_url = (getattr(settings, "GMAIL_API_URL", "") or "https://gmail.googleapis.com/gmail/v1").rstrip("/")
        self.timeout = float(getattr(settings, "GMAIL_TIMEOUT_SECONDS", 20.0) or 20.0)
        self._client: Optional[httpx.AsyncClient] = None
        self._tokens: dict[str, tuple[str, float]] = {}
        self._lock = asyncio.Lock()

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(self.timeout, connect=10.0))
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:
                pass
            self._client = None

    def _credentials(self, mailbox: dict) -> dict:
        auth = parse_auth_ref(mailbox.get("auth_ref"))
        # O refresh token por caixa no AMBIENTE manda sobre o `auth_ref` da BD.
        # Caso contrario, rotacionar o token no Railway nao tinha efeito nenhum:
        # o codigo continuava a usar a copia antiga guardada na base (foi o que
        # aconteceu ao adicionar o scope gmail.readonly).
        local = (mailbox.get("email") or "").split("@")[0].upper()
        env_token = (os.getenv(f"GMAIL_REFRESH_TOKEN_{local}") or "").strip()
        return {
            "client_id": auth.get("client_id") or getattr(settings, "GMAIL_CLIENT_ID", ""),
            "client_secret": auth.get("client_secret") or getattr(settings, "GMAIL_CLIENT_SECRET", ""),
            "refresh_token": (
                env_token
                or auth.get("refresh_token")
                or getattr(settings, "GMAIL_REFRESH_TOKEN", "")
            ),
        }

    async def _access_token(self, creds: dict) -> Optional[str]:
        client_id = creds.get("client_id")
        refresh_token = creds.get("refresh_token")
        if not (client_id and creds.get("client_secret") and refresh_token):
            return None
        cache_key = f"{client_id}:{refresh_token[:12]}"
        cached = self._tokens.get(cache_key)
        if cached and time.monotonic() < cached[1]:
            return cached[0]
        async with self._lock:
            cached = self._tokens.get(cache_key)
            if cached and time.monotonic() < cached[1]:
                return cached[0]
            try:
                resp = await self._get_client().post(
                    self.token_url,
                    data={
                        "client_id": client_id,
                        "client_secret": creds.get("client_secret"),
                        "refresh_token": refresh_token,
                        "grant_type": "refresh_token",
                    },
                )
            except Exception as e:
                logger.warning(f"[GMAIL] Falha ao renovar token: {e}")
                return None
            if resp.status_code != 200:
                logger.warning(f"[GMAIL] Token HTTP {resp.status_code}: {resp.text[:200]}")
                return None
            try:
                token = resp.json().get("access_token")
            except Exception:
                token = None
            if not token:
                return None
            expires = int(resp.json().get("expires_in") or 3600)
            self._tokens[cache_key] = (token, time.monotonic() + max(60, expires - 60))
            return token

    async def send(
        self,
        mailbox: dict,
        to_email: str,
        subject: str,
        body_text: str,
        from_name: Optional[str] = None,
    ) -> SendResult:
        """Envia um e-mail real pela caixa indicada. Nunca levanta excecao."""
        if not to_email:
            return SendResult(success=False, error="missing recipient")
        creds = self._credentials(mailbox)
        token = await self._access_token(creds)
        if not token:
            return SendResult(success=False, error="gmail not configured")

        from_email = mailbox.get("email")
        if not from_email:
            return SendResult(success=False, error="mailbox has no email")
        display = from_name or mailbox.get("display_name")
        raw = build_raw_message(to_email, subject, body_text, from_email, display)
        try:
            resp = await self._get_client().post(
                f"{self.api_url}/users/{from_email}/messages/send",
                headers={"Authorization": f"Bearer {token}"},
                json={"raw": raw},
            )
        except Exception as e:
            return SendResult(success=False, error=str(e))
        if resp.status_code >= 300:
            return SendResult(
                success=False,
                error=f"HTTP {resp.status_code}: {resp.text[:200]}",
                http_status=resp.status_code,
            )
        try:
            provider_id = resp.json().get("id")
        except Exception:
            provider_id = None
        return SendResult(success=True, provider_id=provider_id, http_status=resp.status_code)


gmail_sender = GmailSender()

"""
Cliente HTTP do micro-worker SMTP em VPS dedicado (Etapas 1 e 2).

O backend no Railway tem a porta 25 de saida bloqueada; este modulo delega a
validacao RCPT ao worker que corre num VPS com porta 25 aberta e PTR
configurado. Nao envia e-mail (nunca usa DATA).

Contrato:
  POST {VPS_WORKER_URL}/validate-smtp
    body: {"email": "contact@contractor.com", "domain": "contractor.com"}
    header: Authorization: Bearer <VPS_WORKER_SECRET>
    response: {"status": "valid"|"invalid"|"catch_all"|"inconclusive",
               "catch_all": bool, "mx_host": str|null,
               "latency_ms": float, "code": int|null, "error": str|null}

  GET {VPS_WORKER_URL}/health -> {"status": "healthy", ...}

Sem VPS_WORKER_URL/VPS_WORKER_SECRET o cliente falha fechado
(status="inconclusive", sem chamada HTTP): nunca ha' probe nao autenticado.
"""

from __future__ import annotations

import os
from typing import Any, Dict

import httpx

DEFAULT_TIMEOUT = 15.0


def _config() -> tuple[str, str]:
    url = (os.getenv("VPS_WORKER_URL") or "").strip()
    secret = (os.getenv("VPS_WORKER_SECRET") or "").strip()
    return url, secret


def _inconclusive(error: str) -> Dict[str, Any]:
    return {"status": "inconclusive", "catch_all": False, "error": error}


def probe_smtp_via_vps(
    email: str,
    domain: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    transport: httpx.BaseTransport | None = None,
) -> Dict[str, Any]:
    """Pede ao worker VPS a validacao RCPT de `email` no dominio `domain`.

    Nunca levanta por falha de rede/config: devolve sempre um dicionario com
    `status` para o chamador guardar como inconclusivo.
    """
    email = (email or "").strip().lower()
    domain = (domain or "").strip().lower()
    if not email or not domain:
        return _inconclusive("email/domain vazios")
    if "@" not in email or email.rsplit("@", 1)[1] != domain:
        return _inconclusive("email/domain mismatch")

    base_url, secret = _config()
    if not base_url or not secret:
        return _inconclusive(
            "VPS_WORKER_URL/VPS_WORKER_SECRET ausentes; probe nao executado"
        )

    url = f"{base_url.rstrip('/')}/validate-smtp"
    headers = {
        "Authorization": f"Bearer {secret}",
        "Content-Type": "application/json",
    }
    payload = {"email": email, "domain": domain}

    try:
        with httpx.Client(timeout=timeout, transport=transport) as client:
            resp = client.post(url, json=payload, headers=headers)
    except Exception as exc:  # rede/timeout/TLS: inconclusivo, nunca "invalid"
        return _inconclusive(f"worker inacessivel: {exc}")

    if resp.status_code != 200:
        return _inconclusive(f"HTTP {resp.status_code}")

    try:
        data = resp.json()
    except ValueError:
        return _inconclusive("resposta nao-JSON do worker")

    if not isinstance(data, dict) or "status" not in data:
        return _inconclusive("resposta sem campo status")
    return data


def worker_health(*, timeout: float = 10.0) -> Dict[str, Any]:
    """GET /health do worker (usado na homologacao do VPS)."""
    base_url, _ = _config()
    if not base_url:
        return {"status": "unconfigured", "error": "VPS_WORKER_URL ausente"}
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.get(f"{base_url.rstrip('/')}/health")
        if resp.status_code != 200:
            return {"status": "unhealthy", "error": f"HTTP {resp.status_code}"}
        return resp.json()
    except Exception as exc:
        return {"status": "unreachable", "error": str(exc)}

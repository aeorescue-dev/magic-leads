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

Resiliencia:
  * `probe_smtp_via_vps_async` (preferida em codigo async) usa
    `httpx.AsyncClient` e NUNCA bloqueia o event loop;
  * ambas as variantes repetem em falhas transitorias (rede/5xx) com backoff
    exponencial — 451/timeout sao a norma em gateways corporativos;
  * falha persistente continua a devolver `inconclusive`, nunca `valid`.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Dict, Sequence

import httpx

DEFAULT_TIMEOUT = 15.0
# Tentativas extra em falhas transitorias (rede, timeout, 5xx).
DEFAULT_RETRIES = 2
RETRY_BACKOFF: Sequence[float] = (0.7, 2.0)


def _config() -> tuple[str, str]:
    url = (os.getenv("VPS_WORKER_URL") or "").strip()
    secret = (os.getenv("VPS_WORKER_SECRET") or "").strip()
    return url, secret


def _inconclusive(error: str) -> Dict[str, Any]:
    return {"status": "inconclusive", "catch_all": False, "error": error}


def _validate_inputs(email: str, domain: str) -> tuple[str, str] | Dict[str, Any]:
    email = (email or "").strip().lower()
    domain = (domain or "").strip().lower()
    if not email or not domain:
        return _inconclusive("email/domain vazios")
    if "@" not in email or email.rsplit("@", 1)[1] != domain:
        return _inconclusive("email/domain mismatch")
    return email, domain


def _is_transient(result: Dict[str, Any]) -> bool:
    """Falhas que vale a pena repetir (rede/5xx). `invalid`/`valid` nao."""
    status = result.get("status")
    if status in ("valid", "invalid", "catch_all"):
        return False
    error = str(result.get("error") or "")
    if error.startswith("HTTP 5"):
        return True
    # `inconclusive` por rede/timeout/worker inacessivel.
    return True


def _parse_response(status_code: int, body: Any) -> Dict[str, Any]:
    if status_code != 200:
        return _inconclusive(f"HTTP {status_code}")
    if not isinstance(body, dict) or "status" not in body:
        return _inconclusive("resposta sem campo status")
    return body


def probe_smtp_via_vps(
    email: str,
    domain: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    transport: httpx.BaseTransport | None = None,
    retries: int = DEFAULT_RETRIES,
) -> Dict[str, Any]:
    """Versao sincrona (dev/CLI/threads). Use a `_async` em codigo async."""
    checked = _validate_inputs(email, domain)
    if isinstance(checked, dict):
        return checked
    email, domain = checked

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

    attempts = max(1, retries + 1)
    last = _inconclusive("sem resposta do worker")
    for attempt in range(attempts):
        try:
            with httpx.Client(timeout=timeout, transport=transport) as client:
                resp = client.post(url, json=payload, headers=headers)
            last = _parse_response(resp.status_code, _safe_json(resp))
        except Exception as exc:  # rede/timeout/TLS: inconclusivo
            last = _inconclusive(f"worker inacessivel: {exc}")
        if not _is_transient(last) or attempt == attempts - 1:
            return last
        import time

        time.sleep(RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF) - 1)])
    return last


async def probe_smtp_via_vps_async(
    email: str,
    domain: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    transport: httpx.AsyncBaseTransport | None = None,
    retries: int = DEFAULT_RETRIES,
) -> Dict[str, Any]:
    """Versao async: nao bloqueia o event loop do backend no Railway."""
    checked = _validate_inputs(email, domain)
    if isinstance(checked, dict):
        return checked
    email, domain = checked

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

    attempts = max(1, retries + 1)
    last = _inconclusive("sem resposta do worker")
    for attempt in range(attempts):
        try:
            async with httpx.AsyncClient(timeout=timeout, transport=transport) as client:
                resp = await client.post(url, json=payload, headers=headers)
            last = _parse_response(resp.status_code, _safe_json(resp))
        except Exception as exc:
            last = _inconclusive(f"worker inacessivel: {exc}")
        if not _is_transient(last) or attempt == attempts - 1:
            return last
        await asyncio.sleep(RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF) - 1)])
    return last


def _safe_json(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except ValueError:
        return None


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

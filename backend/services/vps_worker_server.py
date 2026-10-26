"""
Servidor do Micro-Worker de validacao SMTP (VPS dedicado).

Corre atras de FastAPI/Uvicorn num VPS com porta 25 de saida liberada e PTR
configurado. O backend no Railway (egress bloqueado na 25) chama este servico
por HTTP autenticado.

Regras de seguranca:
  * Bearer token obrigatorio (VPS_WORKER_SECRET).
  * Rate-limit simples por dominio (VPS_RATE_LIMIT_SECONDS, default 1s).
  * MAIL FROM vazio (null sender) - nunca usa dominio nosso nem de terceiros.
  * Catch-all real: depois de testar o endereco alvo, testa um local-part
    aleatorio no mesmo dominio. Se ambos forem aceites, o dominio e' catch-all.
  * Nao envia DATA: apenas RCPT + QUIT.
"""

from __future__ import annotations

import hmac
import os
import random
import smtplib
import string
import threading
import time
from typing import Dict

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="Garimpador SMTP Micro-Worker", version="1.1.0")

VPS_WORKER_SECRET = os.getenv("VPS_WORKER_SECRET", "")
VPS_HELO = os.getenv("VPS_HELO", "localhost.localdomain")
VPS_RATE_LIMIT_SECONDS = float(os.getenv("VPS_RATE_LIMIT_SECONDS", "1.0"))

ACCEPT_CODES = frozenset({250, 251})
REJECT_CODES = frozenset({501, 503, 550, 551, 552, 553, 554})

_rate_lock = threading.Lock()
_last_probe: Dict[str, float] = {}


class SMTPCheckRequest(BaseModel):
    email: str = Field(..., max_length=320)
    domain: str = Field(..., max_length=255)


def verify_token(authorization: str = Header(...)) -> str:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header format")
    if not VPS_WORKER_SECRET:
        raise HTTPException(status_code=503, detail="Worker secret not configured")
    if not hmac.compare_digest(authorization.split(" ", 1)[1], VPS_WORKER_SECRET):
        raise HTTPException(status_code=403, detail="Unauthorized worker token")
    return VPS_WORKER_SECRET


def _mx_host(domain: str) -> str:
    # Import tardio: o backend (Railway) nunca corre o worker e nao precisa de
    # dnspython so' para importar o modulo nos testes.
    import dns.resolver

    answers = dns.resolver.resolve(domain, "MX", lifetime=4.0)
    hosts = sorted((r.preference, str(r.exchange).rstrip(".")) for r in answers)
    if not hosts:
        raise dns.resolver.NoAnswer
    return hosts[0][1]


def _throttle(domain: str) -> None:
    with _rate_lock:
        now = time.monotonic()
        last = _last_probe.get(domain, 0.0)
        wait = VPS_RATE_LIMIT_SECONDS - (now - last)
        if wait > 0:
            time.sleep(wait)
        _last_probe[domain] = time.monotonic()


def _random_local() -> str:
    token = "".join(random.choices(string.ascii_lowercase + string.digits, k=16))
    return f"probe-{token}"


def _classify(code: int) -> str:
    if code in ACCEPT_CODES:
        return "accepted"
    if code in REJECT_CODES:
        return "rejected"
    return "inconclusive"


@app.get("/health")
def health_check() -> dict:
    return {"status": "healthy", "service": "garimpador-smtp-vps-worker"}


@app.post("/validate-smtp")
def validate_smtp(payload: SMTPCheckRequest, _: str = Depends(verify_token)) -> dict:
    email = payload.email.strip().lower()
    domain = payload.domain.strip().lower()

    if "@" not in email or email.rsplit("@", 1)[1] != domain:
        raise HTTPException(status_code=400, detail="email/domain mismatch")
    if not domain or "." not in domain:
        raise HTTPException(status_code=400, detail="invalid domain")

    _throttle(domain)

    try:
        mx_host = _mx_host(domain)
    except Exception as exc:
        return {"status": "inconclusive", "catch_all": False, "mx_host": None,
                "error": f"MX lookup failed: {exc}"}

    started = time.monotonic()
    target_code = None
    random_code = None
    try:
        smtp = smtplib.SMTP(timeout=8.0)
        smtp.connect(mx_host, 25)
        smtp.helo(VPS_HELO)
        smtp.mail("")  # null sender: nenhum dominio nosso ou de terceiros
        target_code, _ = smtp.rcpt(email)
        random_code, _ = smtp.rcpt(f"{_random_local()}@{domain}")
        try:
            smtp.quit()
        except Exception:
            smtp.close()
    except Exception as exc:
        latency = round((time.monotonic() - started) * 1000, 1)
        return {"status": "inconclusive", "catch_all": False, "mx_host": mx_host,
                "latency_ms": latency, "error": str(exc)}

    latency = round((time.monotonic() - started) * 1000, 1)
    target = _classify(target_code)
    rand = _classify(random_code)

    if target == "accepted" and rand == "accepted":
        return {"status": "catch_all", "catch_all": True, "mx_host": mx_host,
                "latency_ms": latency, "code": target_code}
    if target == "accepted":
        return {"status": "valid", "catch_all": False, "mx_host": mx_host,
                "latency_ms": latency, "code": target_code}
    if target == "rejected":
        return {"status": "invalid", "catch_all": False, "mx_host": mx_host,
                "latency_ms": latency, "code": target_code}
    return {"status": "inconclusive", "catch_all": False, "mx_host": mx_host,
            "latency_ms": latency, "code": target_code}

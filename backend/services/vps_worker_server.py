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
import re
import smtplib
import string
import threading
import time
from typing import Dict

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

app = FastAPI(title="Garimpador SMTP Micro-Worker", version="1.1.0")

VPS_WORKER_SECRET = os.getenv("VPS_WORKER_SECRET", "")
VPS_HELO = os.getenv("VPS_HELO", "localhost.localdomain")
VPS_RATE_LIMIT_SECONDS = float(os.getenv("VPS_RATE_LIMIT_SECONDS", "1.0"))

# Backups da base de dados de producao (Railway -> VPS). Destino off-site,
# noutro fornecedor: se o volume do Railway se perder, ha' copia aqui.
BACKUP_DIR = os.getenv("VPS_BACKUP_DIR", "/opt/garimpador-backups")
BACKUP_KEEP = int(os.getenv("VPS_BACKUP_KEEP", "7"))
MAX_BACKUP_BYTES = int(os.getenv("VPS_BACKUP_MAX_BYTES", str(300 * 1024 * 1024)))
BACKUP_NAME_RE = re.compile(r"^leads-\d{4}-\d{2}-\d{2}\.db\.gz$")

os.makedirs(BACKUP_DIR, exist_ok=True)


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

    try:
        answers = dns.resolver.resolve(domain, "MX", lifetime=4.0)
        hosts = sorted((r.preference, str(r.exchange).rstrip(".")) for r in answers)
        if hosts:
            return hosts[0][1]
    except Exception:
        pass

    # RFC 5321 5.1: sem registo MX, o A do proprio dominio e' o MX implicito.
    # Sem isto, empresas com mail no proprio host eram descartadas ("no_mx")
    # sem sequer se tentar o RCPT.
    dns.resolver.resolve(domain, "A", lifetime=4.0)
    return domain


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

# ------------------------------------------------------------------ backups

@app.post("/backup")
async def upload_backup(
    request: Request, name: str, _: str = Depends(verify_token)
) -> dict:
    """Recebe um snapshot gzip da base de producao (autenticado).

    - nome validado (evita path traversal e nomes arbitrarios);
    - escrita em `.part` e rename atomico (nunca deixa ficheiro a meio);
    - tamanho maximo configuravel;
    - retencao: mantem as BACKUP_KEEP copias mais recentes.
    """
    if not BACKUP_NAME_RE.match(name or ""):
        raise HTTPException(status_code=400, detail="nome de backup invalido")

    os.makedirs(BACKUP_DIR, exist_ok=True)
    final_path = os.path.join(BACKUP_DIR, name)
    part_path = final_path + ".part"

    total = 0
    try:
        with open(part_path, "wb") as fh:
            async for chunk in request.stream():
                if not chunk:
                    continue
                total += len(chunk)
                if total > MAX_BACKUP_BYTES:
                    raise HTTPException(status_code=413, detail="backup demasiado grande")
                fh.write(chunk)
    except HTTPException:
        try:
            os.remove(part_path)
        except OSError:
            pass
        raise
    except Exception as exc:  # noqa: BLE001
        try:
            os.remove(part_path)
        except OSError:
            pass
        raise HTTPException(status_code=500, detail=f"falha ao escrever: {exc}") from exc

    os.replace(part_path, final_path)

    # retencao
    files = sorted(
        (f for f in os.listdir(BACKUP_DIR) if BACKUP_NAME_RE.match(f)),
        reverse=True,
    )
    removed = []
    for old in files[BACKUP_KEEP:]:
        try:
            os.remove(os.path.join(BACKUP_DIR, old))
            removed.append(old)
        except OSError:
            pass

    return {
        "status": "ok",
        "name": name,
        "bytes": total,
        "kept": files[:BACKUP_KEEP],
        "pruned": removed,
    }


@app.get("/backup/list")
def list_backups(_: str = Depends(verify_token)) -> dict:
    entries = []
    for name in sorted(
        (f for f in os.listdir(BACKUP_DIR) if BACKUP_NAME_RE.match(f)), reverse=True
    ):
        path = os.path.join(BACKUP_DIR, name)
        entries.append({"name": name, "bytes": os.path.getsize(path),
                        "mtime": int(os.path.getmtime(path))})
    return {"status": "ok", "backups": entries}


@app.get("/backup/latest")
def latest_backup(_: str = Depends(verify_token)):
    """Devolve o backup mais recente (usado pelo teste de restauro)."""
    files = sorted(
        (f for f in os.listdir(BACKUP_DIR) if BACKUP_NAME_RE.match(f)), reverse=True
    )
    if not files:
        raise HTTPException(status_code=404, detail="sem backups")
    return FileResponse(os.path.join(BACKUP_DIR, files[0]),
                        media_type="application/gzip", filename=files[0])


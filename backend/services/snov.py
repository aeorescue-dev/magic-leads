"""Snov.io e-mail enrichment client (Outbound Frio - Fase 2).

Responsabilidade unica: dado um lead (empresa/contacto/dominio), localizar e
VALIDAR e-mails corporativos. A regra anti-spam e' rigida: so' e-mails cujo
status de verificacao e' `valid` podem seguir para a fila de envio. Qualquer
outro status (`unknown`, `accept_all`, `invalid`, `risky`) e' descartado.

O modulo e' fail-soft e isolado: sem credenciais (`SNOV_CLIENT_ID` /
`SNOV_CLIENT_SECRET`) devolve `not_configured` e nunca levanta excecao. Toda a
telemetria vai para a tabela `outbound_enrichment_calls` (dominio outbound) e
nunca interfere no fluxo de envio.

Nada aqui toca Dashboard, ingestao, Landing, Push ou Resend.
"""
from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field
from typing import Any, List, Optional

import httpx

from ..config import settings
from ..utils.logger import logger
from .searchbug import is_corporate_name, split_person_name

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")


def normalize_email(value: Optional[str]) -> Optional[str]:
    """Lowercase + trim + valida formato; None se invalido."""
    if not value:
        return None
    email = str(value).strip().strip(".,;:").lower()
    return email if _EMAIL_RE.match(email) else None


def email_domain(email: Optional[str]) -> Optional[str]:
    if not email or "@" not in email:
        return None
    domain = email.rsplit("@", 1)[1].strip().lower()
    # Descarta webmails publicos: nao identificam a empresa.
    if domain in {
        "gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "aol.com",
        "icloud.com", "msn.com", "live.com", "protonmail.com",
    }:
        return None
    return domain or None


@dataclass
class EmailLookupResult:
    success: bool
    email: Optional[str] = None
    status: Optional[str] = None
    provider: str = "snov"
    error: Optional[str] = None
    outcome: str = "error"
    billed_calls: int = 0
    spend_usd: float = 0.0
    http_status: Optional[int] = None
    latency_ms: Optional[int] = None
    candidates: List[dict] = field(default_factory=list)


# --------------------------------------------------------------- parsing
#
# A API do Snov.io devolve shapes diferentes por endpoint/versao. Estes
# extratores normalizam tudo para listas de dicts com `email`/`status`.

def _extract_email_records(data: Any) -> List[dict]:
    records: List[dict] = []
    if not data:
        return records
    payload = data.get("data", data) if isinstance(data, dict) else data
    if isinstance(payload, dict):
        emails = payload.get("emails")
        if isinstance(emails, list):
            for item in emails:
                if isinstance(item, dict) and item.get("email"):
                    records.append(item)
        else:
            # Shape antigo: {"email@x": {...}}
            for key, val in payload.items():
                if isinstance(val, dict) and _EMAIL_RE.match(str(key)):
                    row = dict(val)
                    row.setdefault("email", key)
                    records.append(row)
    elif isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict) and item.get("email"):
                records.append(item)
    return records


def _extract_verification(data: Any, email: str) -> Optional[str]:
    """Devolve o status de verificacao ("valid"/"invalid"/...) ou None."""
    if not data:
        return None
    payload = data.get("data", data) if isinstance(data, dict) else data
    target = email.lower()
    if isinstance(payload, dict):
        node = payload.get(email) or payload.get(target)
        if isinstance(node, dict):
            return str(node.get("status") or node.get("emailStatus") or "").lower() or None
        if isinstance(node, str):
            return node.lower() or None
        result = payload.get("result")
        if isinstance(result, dict):
            return str(result.get("status") or "").lower() or None
        if isinstance(result, list):
            for item in result:
                if isinstance(item, dict) and str(item.get("email", "")).lower() == target:
                    return str(item.get("status") or "").lower() or None
        if payload.get("status"):
            return str(payload.get("status")).lower()
    elif isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict) and str(item.get("email", "")).lower() == target:
                return str(item.get("status") or "").lower() or None
    return None


def _outcome_for_status(status: Optional[str]) -> str:
    if status == "valid":
        return "success"
    return "invalid_email"


class SnovService:
    """Cliente Snov.io com token OAuth2, cache e telemetria."""

    POSITIVE_TTL = 30 * 24 * 3600
    NEGATIVE_TTL = 24 * 3600

    def __init__(self) -> None:
        self.base_url = (getattr(settings, "SNOV_BASE_URL", "") or "https://api.snov.io").rstrip("/")
        self.client_id = getattr(settings, "SNOV_CLIENT_ID", "") or ""
        self.client_secret = getattr(settings, "SNOV_CLIENT_SECRET", "") or ""
        self.timeout = float(getattr(settings, "SNOV_TIMEOUT_SECONDS", 20.0) or 20.0)
        self.max_verifications = int(getattr(settings, "SNOV_MAX_VERIFICATIONS", 5) or 5)
        self.per_email_usd = float(getattr(settings, "SNOV_PER_EMAIL_USD", 0.015) or 0.015)
        self._token: Optional[str] = None
        self._token_exp: float = 0.0
        self._lock = asyncio.Lock()
        self._client: Optional[httpx.AsyncClient] = None
        self._cache: dict[str, tuple[float, EmailLookupResult]] = {}

    # ------------------------------------------------------------ lifecycle

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

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

    # ------------------------------------------------------------ token

    async def _get_token(self) -> Optional[str]:
        if self._token and time.monotonic() < self._token_exp:
            return self._token
        async with self._lock:
            if self._token and time.monotonic() < self._token_exp:
                return self._token
            try:
                resp = await self._get_client().post(
                    f"{self.base_url}/v2/oauth/access_token",
                    data={
                        "grant_type": "client_credentials",
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                    },
                )
            except Exception as e:
                logger.warning(f"[SNOV] Falha ao obter token: {e}")
                return None
            if resp.status_code != 200:
                logger.warning(f"[SNOV] Token HTTP {resp.status_code}: {resp.text[:200]}")
                return None
            try:
                data = resp.json()
            except Exception:
                return None
            token = data.get("access_token")
            if not token and isinstance(data.get("data"), dict):
                token = data["data"].get("access_token")
            if not token:
                return None
            expires = int(data.get("expires_in") or 3600)
            self._token = token
            self._token_exp = time.monotonic() + max(60, expires - 60)
            return token

    # ------------------------------------------------------------ http

    async def _post(self, path: str, payload: dict) -> tuple[Any, Optional[int]]:
        token = await self._get_token()
        if not token:
            return None, None
        try:
            resp = await self._get_client().post(
                f"{self.base_url}{path}",
                params={"access_token": token},
                headers={"Authorization": f"Bearer {token}"},
                json=payload,
            )
        except Exception as e:
            return {"__error__": str(e)}, None
        try:
            data = resp.json()
        except Exception:
            data = {"__raw__": resp.text[:200]}
        return data, resp.status_code

    # ------------------------------------------------------------ cache

    def _cache_get(self, key: str) -> Optional[EmailLookupResult]:
        entry = self._cache.get(key)
        if not entry:
            return None
        ts, result = entry
        ttl = self.POSITIVE_TTL if (result.success and result.status == "valid") else self.NEGATIVE_TTL
        if time.monotonic() - ts > ttl:
            self._cache.pop(key, None)
            return None
        cached = EmailLookupResult(**{**result.__dict__})
        cached.provider = "cache"
        return cached

    def _cache_put(self, key: str, result: EmailLookupResult) -> None:
        if len(self._cache) > 5000:
            self._cache.clear()
        self._cache[key] = (time.monotonic(), result)

    # ------------------------------------------------------------ lookups

    async def verify_email(self, email: str) -> tuple[Optional[str], Optional[int]]:
        data, status = await self._post(
            "/v1/get-emails-verification-status", {"emails": [email]}
        )
        return _extract_verification(data, email), status

    async def domain_emails(self, domain: str, limit: int = 20) -> tuple[List[dict], Optional[int]]:
        data, status = await self._post(
            "/v1/get-domain-emails", {"domain": domain, "type": "all", "limit": limit}
        )
        return _extract_email_records(data), status

    async def emails_from_names(
        self, first_name: str, last_name: str, domain: str
    ) -> tuple[List[dict], Optional[int]]:
        data, status = await self._post(
            "/v1/get-emails-from-names",
            {"firstName": first_name, "lastName": last_name, "domain": domain},
        )
        return _extract_email_records(data), status

    # ------------------------------------------------------------ orchestration

    async def find_and_verify(
        self,
        owner_email: Optional[str] = None,
        company_name: Optional[str] = None,
        contact_name: Optional[str] = None,
        domain: Optional[str] = None,
        city: Optional[str] = None,
    ) -> EmailLookupResult:
        """Localiza e valida o melhor e-mail corporativo para um lead.

        So' devolve `success=True` com `status == "valid"`. Regista SEMPRE uma
        linha em `outbound_enrichment_calls` (telemetria), com o custo das
        verificacoes pagas.
        """
        started = time.monotonic()

        if not self.configured:
            result = EmailLookupResult(
                success=False, outcome="not_configured", error="snov not configured"
            )
            self._record(result, city, owner_email)
            return result

        clean_email = normalize_email(owner_email)
        clean_domain = (domain or "").strip().lower() or email_domain(clean_email)
        cache_key = clean_email or f"{clean_domain}|{company_name or ''}|{contact_name or ''}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            self._record(cached, city, clean_email)
            return cached

        first_name = last_name = ""
        if contact_name and not is_corporate_name(contact_name):
            first_name, last_name = split_person_name(contact_name)

        candidates: List[dict] = []
        http_status: Optional[int] = None
        provider_error: Optional[str] = None

        # 1) E-mail ja' conhecido do lead: verificar primeiro.
        if clean_email:
            candidates.append({"email": clean_email, "source": "lead"})

        # 2) Busca por nome + dominio (quando ha pessoa identificada).
        if clean_domain and first_name and last_name:
            records, st = await self.emails_from_names(first_name, last_name, clean_domain)
            http_status = st or http_status
            if st is None:
                provider_error = "name search network error"
            for rec in records:
                candidates.append({**rec, "source": "name_search"})

        # 3) Busca por dominio (catch-all corporativo).
        if clean_domain:
            records, st = await self.domain_emails(clean_domain)
            http_status = st or http_status
            if st is None:
                provider_error = provider_error or "domain search network error"
            for rec in records:
                candidates.append({**rec, "source": "domain_search"})

        # Dedupe preservando ordem.
        seen: set[str] = set()
        unique: List[dict] = []
        for cand in candidates:
            email = normalize_email(cand.get("email"))
            if not email or email in seen:
                continue
            seen.add(email)
            unique.append({**cand, "email": email})

        if not unique:
            outcome = "http_error" if provider_error else "no_domain"
            result = EmailLookupResult(
                success=False,
                outcome=outcome,
                error=provider_error or "no candidate email found",
                http_status=http_status,
                latency_ms=int((time.monotonic() - started) * 1000),
            )
            self._record(result, city, clean_email)
            self._cache_put(cache_key, result)
            return result

        # Verificacao rigorosa: apenas `valid` passa. Ordem: lead -> nome -> dominio.
        billed_calls = 0
        last_status: Optional[str] = None
        for cand in unique[: self.max_verifications]:
            status, vst = await self.verify_email(cand["email"])
            http_status = vst or http_status
            if vst is not None:
                billed_calls += 1
            last_status = status or last_status
            if status == "valid":
                result = EmailLookupResult(
                    success=True,
                    email=cand["email"],
                    status="valid",
                    outcome="success",
                    billed_calls=billed_calls,
                    spend_usd=round(billed_calls * self.per_email_usd, 4),
                    http_status=http_status,
                    latency_ms=int((time.monotonic() - started) * 1000),
                    candidates=unique,
                )
                self._record(result, city, cand["email"])
                self._cache_put(cache_key, result)
                return result

        result = EmailLookupResult(
            success=False,
            outcome="invalid_email",
            status=last_status,
            error="no valid email found",
            billed_calls=billed_calls,
            spend_usd=round(billed_calls * self.per_email_usd, 4),
            http_status=http_status,
            latency_ms=int((time.monotonic() - started) * 1000),
            candidates=unique,
        )
        self._record(result, city, clean_email)
        self._cache_put(cache_key, result)
        return result

    # ------------------------------------------------------------ telemetry

    def _record(self, result: EmailLookupResult, city: Optional[str], email: Optional[str]) -> None:
        try:
            from .db import record_outbound_enrichment_call

            record_outbound_enrichment_call(
                outcome=result.outcome,
                billed=1 if result.billed_calls > 0 else 0,
                latency_ms=result.latency_ms,
                http_status=result.http_status,
                city=city,
                email=email or result.email,
                error=result.error,
                provider=result.provider,
            )
        except Exception as e:  # noqa: BLE001
            # Nunca falhar o envio por telemetria, mas perder custo em silêncio
            # impede a reconciliação. Logar sempre.
            logger.warning("[SNOV] Falha ao registar custo de enriquecimento: %s", e)


snov_service = SnovService()

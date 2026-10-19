"""EmailListVerify e-mail enrichment client (Outbound Frio - Fase 2).

Substitui o antigo Snov.io. Dado um lead (e-mail conhecido / contacto /
dominio), localiza e VALIDA e-mails corporativos em duas frentes:

  1. e-mail ja' conhecido do lead -> `GET /api/verifyEmail` (1 credito);
  2. pessoa (nome + dominio) -> `POST /api/findContact` (5 creditos quando acha);
     dominio sozinho -> `POST /api/findContact` (10 creditos quando acha).

A regra anti-spam e' rigida: so' e-mails COMPROVADAMENTE deliveraveis
(`result`/`status` em {"ok", "valid"}) E com confianca media/alta
(`{"high", "medium"}`) seguem para a fila de envio. Todo o resto (unknown,
accept_all, disposal, catch-all, low/unknown confidence) e' descartado.

O modulo e' fail-soft e isolado: sem `EMAILLISTVERIFY_API_KEY` devolve
`not_configured` e nunca levanta excecao. Toda a telemetria vai para a tabela
`outbound_enrichment_calls` (dominio outbound) e nunca interfere no fluxo de
envio.

Nada aqui toca Dashboard, ingestao, Landing, Push ou Resend.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, List, Optional

import httpx

from ..config import settings
from ..utils.logger import logger
from .searchbug import is_corporate_name, split_person_name

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")

# Status de deliverabilidade considerados "validos" (aceitos para envio).
_VALID_DELIVERABILITY = {"ok", "valid"}
# Confianca exigida quando o provedor devolve o campo `confidence`.
_VALID_CONFIDENCE = {"high", "medium"}


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
    provider: str = "emaillistverify"
    error: Optional[str] = None
    outcome: str = "error"
    billed_calls: int = 0
    spend_usd: float = 0.0
    http_status: Optional[int] = None
    latency_ms: Optional[int] = None
    candidates: List[dict] = field(default_factory=list)


# --------------------------------------------------------------- parsing

def _extract_contacts(data: Any) -> List[dict]:
    """Normaliza a resposta do `findContact` para uma lista de dicts.

    O endpoint devolve um array de candidatos (201). Aceita tambem shapes
    envelopados ({"data": [...]}) e um dict unico com `email`.
    """
    records: List[dict] = []
    if not data:
        return records
    payload = data.get("data", data) if isinstance(data, dict) else data
    if isinstance(payload, dict):
        payload = [payload]
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict) and item.get("email"):
                records.append(item)
    return records


def _candidate_valid(record: dict) -> bool:
    """True apenas se o candidato for deliveravel COM confianca media/alta."""
    deliverability = str(
        record.get("result") or record.get("deliverability") or ""
    ).strip().lower()
    if deliverability not in _VALID_DELIVERABILITY:
        return False
    confidence = str(record.get("confidence") or "").strip().lower()
    # Sem confianca explicita, confia na deliverabilidade; se vier, exige media/alta.
    if confidence and confidence not in _VALID_CONFIDENCE:
        return False
    return True


def _candidate_status(record: dict) -> Optional[str]:
    if _candidate_valid(record):
        return "valid"
    deliverability = str(
        record.get("result") or record.get("deliverability") or ""
    ).strip().lower()
    return deliverability or None


def _parse_verify_status(data: Any, text: Optional[str]) -> Optional[str]:
    """Extrai o status de verificacao (JSON {"status"/"result"} ou texto puro)."""
    if isinstance(data, dict):
        for key in ("status", "result", "emailStatus", "email_status"):
            value = data.get(key)
            if value:
                return str(value).strip().lower()
        return None
    raw = (text or "").strip()
    if not raw:
        return None
    return raw.splitlines()[0].strip().lower()


class EmailListVerifyService:
    """Cliente EmailListVerify (findContact + verifyEmail) com cache e telemetria."""

    POSITIVE_TTL = 30 * 24 * 3600
    NEGATIVE_TTL = 24 * 3600
    VALID_STATUSES = _VALID_DELIVERABILITY

    def __init__(self) -> None:
        self.base_url = (
            getattr(settings, "EMAILLISTVERIFY_BASE_URL", "")
            or "https://api.emaillistverify.com"
        ).rstrip("/")
        self.verify_url = (
            getattr(settings, "EMAILLISTVERIFY_VERIFY_URL", "")
            or "https://apps.emaillistverify.com/api/verifyEmail"
        ).strip()
        self.api_key = getattr(settings, "EMAILLISTVERIFY_API_KEY", "") or ""
        self.timeout = float(
            getattr(settings, "EMAILLISTVERIFY_TIMEOUT_SECONDS", 20.0) or 20.0
        )
        self.per_credit_usd = float(
            getattr(settings, "EMAILLISTVERIFY_PER_CREDIT_USD", 0.00699) or 0.00699
        )
        self.verify_credits = int(
            getattr(settings, "EMAILLISTVERIFY_VERIFY_CREDITS", 1) or 1
        )
        self.find_credits_named = int(
            getattr(settings, "EMAILLISTVERIFY_FIND_CREDITS_NAMED", 5) or 5
        )
        self.find_credits_domain = int(
            getattr(settings, "EMAILLISTVERIFY_FIND_CREDITS_DOMAIN", 10) or 10
        )
        self._client: Optional[httpx.AsyncClient] = None
        self._cache: dict[str, tuple[float, EmailLookupResult]] = {}

    # ------------------------------------------------------------ lifecycle

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

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

    def _headers(self) -> dict:
        # `x-api-key` e `secret` sao intercambiaveis na API; usamos o header e
        # repetimos `secret` no GET de verificacao por compatibilidade.
        return {"Accept": "application/json", "x-api-key": self.api_key}

    # ------------------------------------------------------------ http

    async def find_contact(
        self, first_name: str, last_name: str, domain: str
    ) -> tuple[List[dict], Optional[int]]:
        body: dict = {"domain": domain}
        if first_name:
            body["firstName"] = first_name
        if last_name:
            body["lastName"] = last_name
        try:
            resp = await self._get_client().post(
                f"{self.base_url}/api/findContact",
                headers=self._headers(),
                json=body,
            )
        except Exception as e:
            logger.warning(f"[ELV] findContact falhou: {e}")
            return [], None
        try:
            data = resp.json()
        except Exception:
            data = None
        return _extract_contacts(data), resp.status_code

    async def verify_email(self, email: str) -> tuple[Optional[str], Optional[int]]:
        try:
            resp = await self._get_client().get(
                self.verify_url,
                params={"secret": self.api_key, "email": email},
                headers=self._headers(),
            )
        except Exception as e:
            logger.warning(f"[ELV] verifyEmail falhou: {e}")
            return None, None
        try:
            data = resp.json()
        except Exception:
            data = None
        return _parse_verify_status(data, resp.text), resp.status_code

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

    # ------------------------------------------------------------ orchestration

    def _success(
        self,
        email: str,
        billed: int,
        http_status: Optional[int],
        started: float,
        candidates: List[dict],
    ) -> EmailLookupResult:
        return EmailLookupResult(
            success=True,
            email=email,
            status="valid",
            provider="emaillistverify",
            outcome="success",
            billed_calls=billed,
            spend_usd=round(billed * self.per_credit_usd, 4),
            http_status=http_status,
            latency_ms=int((time.monotonic() - started) * 1000),
            candidates=candidates,
        )

    def _finish(
        self, result: EmailLookupResult, cache_key: str, city: Optional[str], email: Optional[str]
    ) -> None:
        self._record(result, city, email)
        self._cache_put(cache_key, result)

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
        linha em `outbound_enrichment_calls` (telemetria), com os creditos
        efetivamente gastos (verifyEmail=1, findContact=5 nome / 10 dominio).
        """
        started = time.monotonic()

        if not self.configured:
            result = EmailLookupResult(
                success=False,
                outcome="not_configured",
                error="emaillistverify not configured",
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
        billed = 0
        last_status: Optional[str] = None

        # 1) E-mail ja' conhecido do lead: verificacao direta (1 credito).
        if clean_email:
            candidates.append({"email": clean_email, "source": "lead"})
            status, st = await self.verify_email(clean_email)
            http_status = st or http_status
            if st is None:
                provider_error = "verify network error"
            elif st >= 400:
                provider_error = f"verify http {st}"
            elif 200 <= st < 300:
                billed += self.verify_credits
            last_status = status or last_status
            if status in self.VALID_STATUSES:
                result = self._success(clean_email, billed, http_status, started, candidates)
                self._finish(result, cache_key, city, clean_email)
                return result

        # 2) Pessoa (nome + dominio) ou dominio: findContact ja' verifica.
        if clean_domain:
            records, st = await self.find_contact(first_name, last_name, clean_domain)
            http_status = st or http_status
            if st is None:
                provider_error = provider_error or "find network error"
            elif st >= 400:
                provider_error = provider_error or f"find http {st}"
            named = bool(first_name or last_name)
            find_credits = self.find_credits_named if named else self.find_credits_domain
            source = "name_search" if named else "domain_search"
            for rec in records:
                candidates.append({**rec, "source": source})
            for rec in records:
                email = normalize_email(rec.get("email"))
                if not email:
                    continue
                last_status = _candidate_status(rec) or last_status
                if _candidate_valid(rec):
                    billed += find_credits
                    result = self._success(email, billed, http_status, started, candidates)
                    self._finish(result, cache_key, city, email)
                    return result

        # 3) Nada valido: classifica o outcome.
        if not candidates:
            if provider_error:
                outcome = "http_error"
            elif not (clean_email or clean_domain):
                outcome = "no_domain"
            else:
                outcome = "provider_no_results"
            error = provider_error or "no candidate email found"
        else:
            outcome = "invalid_email"
            error = "no valid email found"
        result = EmailLookupResult(
            success=False,
            outcome=outcome,
            status=last_status,
            error=error,
            billed_calls=billed,
            spend_usd=round(billed * self.per_credit_usd, 4),
            http_status=http_status,
            latency_ms=int((time.monotonic() - started) * 1000),
            candidates=candidates,
        )
        self._finish(result, cache_key, city, clean_email)
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
        except Exception:
            pass


emaillistverify_service = EmailListVerifyService()

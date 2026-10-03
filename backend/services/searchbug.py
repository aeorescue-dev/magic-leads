"""Phone Lookup Service — Multi-provider with robust fallback chain.

Providers (tried in order):
1. Searchbug (if API key works)
2. TruePeopleSearch (free, no key needed - HTML scraping) - temporarily disabled
3. Whitepages via RapidAPI (if key available)
4. AbstractAPI Phone Validation (if key available)
5. Numverify (if key available)
6. Mock fallback (returns structured empty response)

Env vars:
  SEARCHBUG_API_KEY — Searchbug API key (optional)
  TRUEPEOPLESEARCH_ENABLED — Enable TruePeopleSearch scraping (default: true)
  WHITEPAGES_API_KEY — RapidAPI Whitepages key (optional)
  ABSTRACT_API_KEY — AbstractAPI key (optional)
  NUMVERIFY_API_KEY — Numverify API key (optional)
"""

from __future__ import annotations

import asyncio
import os
import re
import time
from dataclasses import dataclass
from typing import Optional

import httpx

from ..config import settings
from ..utils.logger import logger
from .lead_rules import address_is_resolvable
from .metrics import searchbug_metrics


def normalize_us_phone(phone: str) -> str:
    """Normalize US phone number to E.164 format (+1XXXXXXXXXX)."""
    if not phone:
        return phone

    digits = re.sub(r"\D", "", str(phone))

    if len(digits) == 10:
        return f"+1{digits}"
    elif len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    elif len(digits) == 11 and not digits.startswith("1"):
        logger.warning(f"Phone number has 11 digits but doesn't start with 1: {digits}")
        return f"+{digits}"
    elif digits.startswith("+"):
        return phone
    else:
        if len(digits) == 10:
            return f"+1{digits}"
        logger.warning(f"Unrecognized phone format, returning with + prefix: {digits}")
        return f"+{digits}"


def format_us_phone_display(phone_e164: str) -> str:
    """Format E.164 US phone for display: (XXX) XXX-XXXX."""
    if not phone_e164:
        return phone_e164

    if phone_e164.startswith("+1") and len(phone_e164) == 12:
        digits = phone_e164[2:]
        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    elif phone_e164.startswith("1") and len(phone_e164) == 11:
        digits = phone_e164[1:]
        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"

    digits = re.sub(r"\D", "", phone_e164)
    if len(digits) == 10:
        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"

    return phone_e164


@dataclass
class PhoneLookupResult:
    """Structured result from phone lookup."""
    success: bool
    phone: Optional[str] = None
    phone_type: Optional[str] = None  # "landline", "mobile", "voip"
    carrier: Optional[str] = None
    is_connected: Optional[bool] = None
    error: Optional[str] = None
    raw: Optional[dict] = None
    provider: Optional[str] = None

    @property
    def is_usable(self) -> bool:
        return self.success and self.phone is not None


_TRACKING_JUNK = re.compile(r"[,;|/\\]+")

# Placeholders que aparecem em datasets publicos no lugar de um nome.
_PLACEHOLDERS = {
    "N A", "NA", "N A N", "NONE", "NULL", "NIL", "UNKNOWN", "UNKOWN",
    "DESCONHECIDO", "SEM DADOS", "SEM NOME", "NO NAME", "NOT APPLICABLE",
    "PRIVATE", "REDACTED", "WITHHELD", "UNKNOWN OWNER", "PRIVATE OWNER",
}


def _clean_owner_name(owner_name: str | None) -> tuple[str | None, str | None]:
    """Normaliza o owner_name e decide se serve para uma consulta paga.

    O enriquecimento devolve valores crus de datasets publicos. Observacoes
    reais: "BIG BEAR," ( virgula final), "  JOEL DE LA CRUZ  ".

    Regras deliberadamente conservadoras. Nao rejeitamos nomes de
    empresa/LLC: o proprietario registado de um imovel e muitas vezes uma
    society e o contacto e valido. Rejeitamos so o que nao e um nome.

    Devolve (nome_limpo, None) ou (None, motivo).
    """
    if owner_name is None:
        return None, "owner_name_ausente"

    cleaned = _TRACKING_JUNK.sub(" ", str(owner_name))
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .-,")

    if not cleaned:
        return None, "owner_name_vazio"

    # Sem letras nao ha nome: "21033", "---", "N/A".
    if not re.search(r"[A-Za-z]", cleaned):
        return None, "owner_name_sem_letras"

    # Placeholders como "N/A", "DESCONHECIDO", "PRIVATE": nao ha nome atras.
    if cleaned.upper() in _PLACEHOLDERS:
        return None, "owner_name_placeholder"

    if len(cleaned) < 3:
        return None, "owner_name_curto_demais"

    return cleaned, None


# Sufixos que denunciam uma empresa/sociedade em vez de uma pessoa.
# O proprietario registado de um imovel em NYC e muitas vezes uma society, e
# esse nome e VALIDO como consulta. O problema nunca foi o nome corporativo em
# si: foi parti-lo em FNAME/LNAME como se fosse uma pessoa ("65 MS LLC" ->
# FNAME="65", LNAME="MS LLC"), o que degrada o match e ainda custa dinheiro.
_CORPORATE_SUFFIXES = frozenset({
    "LLC", "INC", "INCORPORATED", "CORP", "CORPORATION", "CO", "COMPANY",
    "LTD", "LIMITED", "LP", "LLP", "PLLC", "PC", "PA", "TRUST", "HOLDING",
    "HOLDINGS", "REALTY", "PROPERTY", "PROPERTIES", "ASSOC", "ASSOCIATES",
    "ASSOCIATION", "PARTNERS", "PARTNERSHIP", "ENTERPRISE", "ENTERPRISES",
    "BANK", "FINANCIAL", "MGMT", "MANAGEMENT", "SERVICES", "SERVICE",
    "SOLUTIONS", "DEVELOPMENT", "INVESTMENTS", "CAPITAL", "CONSTRUCTION",
    "MAINTENANCE", "ESTATE", "ESTATES", "FUND", "FUNDING", "GROUP",
})

# Sufixos de pessoa que pertencem ao ULTIMO nome, nao ao primeiro.
_PERSON_SUFFIXES = frozenset({
    "JR", "SR", "II", "III", "IV", "V", "MD", "DDS", "PHD", "ESQ",
})

_ZIP_RE = re.compile(r"\d{5}(-\d{4})?$")


def is_corporate_name(name: str | None) -> bool:
    """True se `name` e uma empresa/sociedade e nao o nome de uma pessoa."""
    if not name:
        return False
    upper = name.upper()
    for token in re.findall(r"[A-Z0-9]+", upper):
        if token in _CORPORATE_SUFFIXES:
            return True
    # Sufixo colado ao resto: "65 MSLLC", "ACMEINC", "PARKSLTD".
    compact = re.sub(r"[^A-Z]", "", upper)
    for suffix in _CORPORATE_SUFFIXES:
        if len(suffix) > 2 and compact.endswith(suffix):
            return True
    return False


def split_person_name(name: str) -> tuple[str, str]:
    """Parte um NOME DE PESSOA em (primeiro, ultimo).

    Nomes corporativos NUNCA chegam aqui: `_lookup_searchbug` omite FNAME/LNAME
    quando `is_corporate_name()` e True. O corte e por ultimo token, nao por
    palavras-chave, para nao partir "VAN DER BERG" nem "MARIA DE OLIVEIRA".
    """
    tokens = [t for t in re.split(r"\s+", (name or "").strip()) if t]
    if not tokens:
        return "", ""

    suffixes: list[str] = []
    while len(tokens) > 2 and tokens[-1].upper().strip(".") in _PERSON_SUFFIXES:
        suffixes.insert(0, tokens.pop())

    if len(tokens) == 1:
        return tokens[0], " ".join(suffixes)
    return tokens[0], " ".join(tokens[1:] + suffixes)


def normalize_provider_address(address: str | None, city: str | None, state: str | None) -> str:
    """Remove de ADDRESS os segmentos que ja vao nos campos CITY/STATE/ZIP.

    Payloads a montante podem chegar como "123 MAIN ST, BROOKLYN, NY". O
    provider receberia entao a cidade dentro de ADDRESS e outra vez em CITY, o
    que piora o match de uma chamada PAGA. So se cortam segmentos finais que
    duplicam EXATAMENTE a city/state/zip fornecidos -- nunca outros, para nao
    mutilar um endereco legitimo.
    """
    addr = (address or "").strip()
    if not addr:
        return ""

    parts = [p.strip() for p in addr.split(",") if p.strip()]
    c = (city or "").strip().upper()
    s = (state or "").strip().upper()

    def _is_noise(token: str) -> bool:
        return bool(
            (c and token == c)
            or (s and token == s)
            or _ZIP_RE.fullmatch(token)
        )

    # Um segmento final pode colar varias peças: "NY 11201", "BROOKLYN NY 11201".
    # Por isso o corte e por TOKEN dentro do ultimo segmento, e so depois se
    # remove o segmento que ficou vazio. Repete ate estabilizar porque remover
    # "NY 11201" pode revelar um "BROOKLYN" que tambem e ruido.
    changed = True
    while changed and len(parts) > 1:
        changed = False
        tokens = parts[-1].split()
        kept = [t for t in tokens if not _is_noise(t.upper())]
        if len(kept) != len(tokens):
            changed = True
            if kept:
                parts[-1] = " ".join(kept)
            else:
                parts.pop()
                continue
        if len(parts) > 1 and _is_noise(parts[-1].upper()):
            parts.pop()
            changed = True

    return ", ".join(parts)


# Um telefone nao muda de dia para dia: 30 dias e seguro e evita re-pagar.
_PHONE_CACHE_TTL_OK = 30 * 24 * 3600
# Um "nao achou" pode mudar quando o enriquecimento gratuito melhora ou quando
# o Searchbug carrega novos registos. TTL curto para nao fechar a porta para
# sempre a um lead que hoje nao resolve.
_PHONE_CACHE_TTL_FAIL = 24 * 3600
_PHONE_CACHE_MAX = 5000


# --------------------------------------------------------------- Fase 2
# Classificacao de resultado da chamada PAGA. Funcao pura e testavel: e o
# unico sitio onde se decide o que um outcome significa, para o painel e
# para os testes partilharem exactamente a mesma regra.
#
# A distincao que interessa ao dono do negocio e billed vs nao-billed, e nao
# success vs erro: uma chamada que sai com `no_results` foi consultada e
# COBRADA. Sao essas que appearcem como "cobrancas fantasma" no /admin.

_TIMEOUT_MARKERS = (
    "timeout",
    "timed out",
    "etimedout",
    "read timeout",
    "connect timeout",
)


def classify_searchbug_outcome(success: bool, error: Optional[str] = None) -> str:
    """Normaliza o resultado de uma consulta Searchbug num outcome estavel."""
    if success:
        return "success"

    err = (error or "").strip().lower()
    if not err:
        return "error"
    if any(marker in err for marker in _TIMEOUT_MARKERS):
        return "timeout"
    if err.startswith("http "):
        return "http_error"
    if "not configured" in err or "co_code" in err:
        return "not_configured"
    if "noresults" in err or "no results" in err or "no phone found" in err:
        return "no_results"
    if "unexpected response format" in err or "no data" in err:
        return "bad_response"
    return "error"


def _http_status_from_error(error: Optional[str]) -> Optional[int]:
    """Extrai o codigo de um erro 'HTTP 503: ...' para telemetria."""
    if not error:
        return None
    head = error.strip()[:12]
    if not head.lower().startswith("http "):
        return None
    digits = head[5:].strip().split(":")[0].strip()
    return int(digits) if digits.isdigit() else None


class PhoneLookupService:
    """Multi-provider phone lookup with fallback chain."""

    def __init__(self):
        # Provider configs (env vars)
        self.searchbug_key = getattr(settings, "SEARCHBUG_API_KEY", None) or os.getenv("SEARCHBUG_API_KEY")

        self.timeout = httpx.Timeout(20.0, connect=10.0)
        self._mock_mode = False  # Always try real providers first
        # telefone -> (timestamp_monotonic, telefone ou None para "sem resultado")
        self._phone_cache: dict[str, tuple[float, Optional[str]]] = {}

        enabled = []
        if self.searchbug_key:
            enabled.append("Searchbug")
        logger.info(f"PhoneLookup: LIVE MODE enabled. Providers: {', '.join(enabled)}")

    async def lookup_phone(self, address: str, city: str, state: str, owner_name: str | None = None, zip_code: str | None = None) -> "PhoneLookupResult":
        """Look up phone number for an address via fallback chain.

        Regra de custo: esta e a etapa FINAL e PAGA, chamada apenas depois do
        enriquecimento gratuito. Sem um owner_name utilizavel, a consulta seria
        cega (so por endereco) e devolveria quase sempre "No results" a pagar.
        Por isso recusa-se ANTES de qualquer chamada ao provider.
        """
        if not address_is_resolvable(address):
            # GUARD_SKIPPED: nós não consultámos o Searchbug. Registado com
            # prefixo proprio para nunca se confundir com o provider respondeu
            # "No results", que implicaria uma chamada PAGA.
            logger.info(
                f"[PHONE][guard_skipped] address_incompleta para {address!r} — "
                f"provider NAO foi consultado (custo zero)"
            )
            searchbug_metrics.record(
                outcome="guard_skipped", billed=False, city=city, error="address_incompleta"
            )
            return PhoneLookupResult(
                success=False,
                error="guard_skipped:address_incompleta",
                provider="none",
            )

        clean_name, name_error = _clean_owner_name(owner_name)
        if name_error:
            logger.info(
                f"[PHONE][guard_skipped] {name_error} para address={address!r} — "
                f"provider NAO foi consultado (custo zero)"
            )
            searchbug_metrics.record(
                outcome="guard_skipped", billed=False, city=city, error=name_error
            )
            return PhoneLookupResult(
                success=False,
                error=f"guard_skipped:{name_error}",
                provider="none",
            )

        cache_key = self._cache_key(address, city, state, zip_code, clean_name)
        cached = self._phone_cache_get(cache_key)
        if cached is not None:
            phone, was_hit, was_negative = cached
            if not was_negative:
                searchbug_metrics.record(
                    outcome="cache_hit", billed=False, city=city, error=None
                )
                return PhoneLookupResult(
                    success=True,
                    phone=phone,
                    provider="cache",
                )
            # "sem resultado" dentro do TTL: nao voltar a pagar por isto hoje
            searchbug_metrics.record(
                outcome="cache_negative", billed=False, city=city, error=None
            )
            return PhoneLookupResult(
                success=False,
                error="cache_sem_resultado",
                provider="cache",
            )

        # Provider chain (ordered by reliability/cost)
        providers = [
            ("Searchbug", self._lookup_searchbug),
        ]

        for name, func in providers:
            try:
                result = await func(
                    address,
                    city,
                    state,
                    owner_name=clean_name,
                    zip_code=zip_code,
                )
                if result.success and result.phone:
                    logger.info(f"Phone lookup successful via {name} for {address}, {city}, {state}")
                    self._phone_cache_put(cache_key, result.phone)
                    return result
                else:
                    logger.warning(
                        f"[PHONE][provider_no_results] {name} consultou e nao "
                        f"devolveu telefone para {address!r}, {city} ({result.error}) — "
                        f"chamada PAGA"
                    )
                    self._phone_cache_put(cache_key, None)
            except Exception as e:
                logger.warning(
                    f"[PHONE][provider_error] {name} deu excepcao para "
                    f"{address!r}, {city}: {e} — resultado guardado como negativo"
                )
                self._phone_cache_put(cache_key, None)

        # All providers failed
        return PhoneLookupResult(
            success=False,
            error="All phone lookup providers failed",
            provider="none"
        )

    def _cache_key(
        self,
        address: str,
        city: str,
        state: str,
        zip_code: str | None,
        clean_name: str | None,
    ) -> str:
        """Chave de cache do telefone.

        Inclui o ZIP: o mesmo address/city/state com ZIP diferente e outro
        imovel. Sem ele, um "nao achou" em Park Ave contaminava o 11201.

        E um METODO, e nao uma expressao inline, para que os testes nunca
        voltem a duplicar o formato da chave a mao -- foi exatamente isso que
        partiu quando o ZIP foi acrescentado.
        """
        return "|".join(
            [
                (address or "").strip().upper(),
                (city or "").strip().upper(),
                (state or "").strip().upper(),
                (zip_code or "").strip().upper(),
                (clean_name or "").upper(),
            ]
        )

    def _phone_cache_get(self, key: str) -> tuple[Optional[str], bool, bool] | None:
        """Devolve (telefone, foi_acertado, foi_negativo) ou None em cache miss."""
        entry = self._phone_cache.get(key)
        if entry is None:
            return None
        stored_at, phone = entry
        ttl = _PHONE_CACHE_TTL_OK if phone else _PHONE_CACHE_TTL_FAIL
        if time.monotonic() - stored_at > ttl:
            self._phone_cache.pop(key, None)
            return None
        return phone, True, phone is None

    def _phone_cache_put(self, key: str, phone: Optional[str]) -> None:
        if len(self._phone_cache) >= _PHONE_CACHE_MAX:
            # dicionario-ordered: remove a entrada mais antiga
            self._phone_cache.pop(next(iter(self._phone_cache)), None)
        self._phone_cache[key] = (time.monotonic(), phone)

    async def _lookup_searchbug(self, address: str, city: str, state: str, owner_name: str | None = None, zip_code: str | None = None) -> "PhoneLookupResult":
        """Lookup via Searchbug Contact Info API (api_contact).

        Requer SEARCHBUG_ACCOUNT_CODE (CO_CODE) e SEARCHBUG_API_KEY (PASS).
        Endpoint: POST https://data.searchbug.com/api/search.aspx
        """
        account_code = getattr(settings, "SEARCHBUG_ACCOUNT_CODE", None) or os.getenv("SEARCHBUG_ACCOUNT_CODE")
        api_key = self.searchbug_key

        # Fase 2: medicao de custo. `_record` e chamado em TODOS os returns
        # abaixo e nunca levanta: e a unica forma de o preco por consulta
        # ser auditavel. `billed` distingue o que custou dinheiro do que foi
        # cortado antes da rede.
        started = time.monotonic()

        def _record(result: "PhoneLookupResult", *, billed: bool, http_status: Optional[int] = None) -> "PhoneLookupResult":
            try:
                searchbug_metrics.record(
                    outcome=classify_searchbug_outcome(result.success, result.error),
                    billed=1 if billed else 0,
                    latency_ms=int((time.monotonic() - started) * 1000),
                    http_status=http_status,
                    city=city,
                    error=result.error,
                )
            except Exception:  # pragma: no cover - telemetria nunca quebra o fluxo
                logger.debug("Falha ao registar telemetria Searchbug", exc_info=True)
            return result

        if not account_code or not api_key:
            # Nao ha rede: custo zero, e saber que faltam credenciais e o
            # principal sinal de "a Searchbug nao esta configurada".
            return _record(
                PhoneLookupResult(
                    success=False,
                    error="Searchbug CO_CODE (account number) or API key not configured",
                    provider="Searchbug"
                ),
                billed=False,
            )

        # FNAME/LNAME so quando o owner_name e mesmo uma PESSOA. Um nome
        # corporativo nao tem primeiro/ultimo nome: envia-lo partido ("65" /
        # "MS LLC") estraga o match e custa uma chamada paga. Sem estes campos
        # a consulta continua a funcionar pela morada, que e a chave real.
        fname = lname = ""
        if owner_name and not is_corporate_name(owner_name):
            fname, lname = split_person_name(owner_name)

        clean_address = normalize_provider_address(address, city, state)

        # Form data para POST
        form_data = {
            "CO_CODE": account_code,
            "PASS": api_key,
            "TYPE": "api_contact",
            "FORMAT": "JSON",
            "ADDRESS": clean_address,
            "CITY": city,
            "STATE": state,
        }
        if fname:
            form_data["FNAME"] = fname
        if lname:
            form_data["LNAME"] = lname
        if zip_code:
            form_data["ZIP"] = zip_code

        try:
            # verify=True: verificacao de TLS activa. Com verify=False a
            # credencial da conta via em claro para quem estiver no meio.
            async with httpx.AsyncClient(timeout=20.0, verify=True) as client:
                response = await client.post(
                    "https://data.searchbug.com/api/search.aspx",
                    data=form_data,
                    timeout=20.0,
                    follow_redirects=True
                )

                if response.status_code != 200:
                    logger.error(f"Searchbug HTTP {response.status_code} for {address}, {city}, {state}: {response.text[:500]}")
                    return _record(
                        PhoneLookupResult(success=False, error=f"HTTP {response.status_code}: {response.text[:200]}", provider="Searchbug"),
                        billed=True,
                        http_status=response.status_code,
                    )

                data = response.json()

                # Resposta de erro da API
                status = data.get("Status") or data.get("STATUS")
                if status and status.upper() in ("ERROR", "NORESULTS"):
                    error = data.get("ERROR") or data.get("Error") or "No results"
                    return _record(
                        PhoneLookupResult(success=False, error=str(error), provider="Searchbug", raw=data),
                        billed=True,
                        http_status=200,
                    )

                # Extrai telefone do formato novo: Data.RECORD[].PHONES.PHONE[]
                data_obj = data.get("Data") or data.get("DATA")
                if not data_obj:
                    return _record(
                        PhoneLookupResult(success=False, error="Unexpected response format (no Data)", provider="Searchbug", raw=data),
                        billed=True,
                        http_status=200,
                    )

                records = data_obj.get("RECORD") or data_obj.get("Record") or []
                if isinstance(records, dict):
                    records = [records]

                for rec in records:
                    phones_obj = rec.get("PHONES") or rec.get("Phones")
                    if not phones_obj:
                        continue
                    phone_list = phones_obj.get("PHONE") or phones_obj.get("Phone") or []
                    if isinstance(phone_list, str):
                        phone_list = [phone_list]
                    for phone in phone_list:
                        if phone and str(phone).strip():
                            return _record(
                                PhoneLookupResult(
                                    success=True,
                                    phone=normalize_us_phone(str(phone).strip()),
                                    phone_type=str(rec.get("PHONE_TYPE") or rec.get("PhoneType") or "").strip().lower() or None,
                                    carrier=str(rec.get("CARRIER") or rec.get("Carrier") or "").strip() or None,
                                    is_connected=bool(rec.get("IS_CONNECTED") or rec.get("IsConnected")) if rec.get("IS_CONNECTED") or rec.get("IsConnected") else None,
                                    provider="Searchbug",
                                    raw=data
                                ),
                                billed=True,
                                http_status=200,
                            )

                return _record(
                    PhoneLookupResult(success=False, error="No phone found in results", provider="Searchbug", raw=data),
                    billed=True,
                    http_status=200,
                )

        except Exception as e:
            logger.warning(f"Searchbug Contact Info API error: {e}")
            return _record(
                PhoneLookupResult(success=False, error=str(e), provider="Searchbug"),
                billed=True,
            )

    async def lookup_phone_batch(self, addresses: list[tuple[str, str, str, str | None, str | None]]) -> list["PhoneLookupResult"]:
        """Look up multiple phones concurrently (respects rate limits).

        Each tuple: (address, city, state, owner_name, zip_code)
        """
        semaphore = asyncio.Semaphore(2)

        async def _lookup_with_sem(addr: str, city: str, state: str, owner_name: str | None = None, zip_code: str | None = None) -> "PhoneLookupResult":
            async with semaphore:
                return await self.lookup_phone(addr, city, state, owner_name=owner_name, zip_code=zip_code)

        tasks = [_lookup_with_sem(addr, city, state, owner_name, zip_code) for addr, city, state, owner_name, zip_code in addresses]
        return await asyncio.gather(*tasks)


# Global singleton instance
phone_lookup_service = PhoneLookupService()


# Convenience function for backward compatibility
async def searchbug_lookup_phone(address: str, city: str, state: str, owner_name: str | None = None, zip_code: str | None = None) -> "PhoneLookupResult":
    """Convenience function for simple lookups (backward compat)."""
    return await phone_lookup_service.lookup_phone(address, city, state, owner_name=owner_name, zip_code=zip_code)


# Aliases for backward compat
PhoneLookupResult = PhoneLookupResult
SearchbugPhoneResult = PhoneLookupResult
SearchbugService = PhoneLookupService
searchbug_service = phone_lookup_service

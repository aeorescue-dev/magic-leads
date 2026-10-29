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
from .lead_rules import address_is_resolvable, is_institutional_name
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
    # P0-C1: validacao por nome e telemetria por lead/classe/camada.
    # `verified` so e' True quando o nome devolvido coincide com o proprietario
    # (name_match >= 0.6). L3 sem nome devolve telefone com verified=False.
    name_match: Optional[float] = None
    verified: bool = False
    returned_first: Optional[str] = None
    returned_last: Optional[str] = None
    layer: Optional[str] = None

    @property
    def is_usable(self) -> bool:
        return self.success and self.phone is not None


_TRACKING_JUNK = re.compile(r"[,;|/\\]+")

# Cidades cujo registo predial usa LAST FIRST [MIDDLE]. Fora destas, mantem-se
# a ordem atual (FIRST LAST) para nao inverter nomes que ja estao corretos.
_REGISTRY_ORDER_CITIES = frozenset({"NYC", "BOSTON", "DALLAS"})

_NAME_STOP = frozenset({
    "MR", "MRS", "MS", "DR", "SR", "JR", "II", "III", "IV", "V",
    "MD", "DDS", "PHD", "ESQ",
})


def normalize_zip(zip_code: str | None) -> str | None:
    """Normaliza um ZIP US para 5 digitos.

    Boston grava `2114` (o zero a esquerda perde-se no CKAN). A Searchbug
    rejeita explicitamente ZIPs de 4 digitos ("Please enter 5-digit ZIP Code"),
    portanto a normalizacao tem de acontecer ANTES da chamada paga.
    """
    z = re.sub(r"\s+", "", str(zip_code or ""))
    if not z:
        return None
    if re.fullmatch(r"\d{4}", z):
        return z.zfill(5)
    if re.fullmatch(r"\d{5}", z):
        return z
    if re.fullmatch(r"\d{5}-\d{4}", z):
        return z[:5]
    return None


def _name_tokens(value: str | None) -> set[str]:
    return {
        t for t in re.findall(r"[A-Z]+", (value or "").upper())
        if t not in _NAME_STOP and len(t) > 1
    }


def compute_name_match(
    owner_name: str | None,
    returned_first: str | None,
    returned_last: str | None,
) -> float | None:
    """Sobreposicao de tokens entre o dono e o nome devolvido (ordem-insensivel).

    Devolve None quando nao ha nome do dono (L3): nao ha como validar.
    """
    owner = _name_tokens(owner_name)
    if not owner:
        return None
    returned = _name_tokens(f"{returned_first or ''} {returned_last or ''}")
    if not returned:
        return 0.0
    return round(len(owner & returned) / len(owner), 3)


# Placeholders que aparecem em datasets publicos no lugar de um nome.
_PLACEHOLDERS = {
    "N A", "NA", "N A N", "NONE", "NULL", "NIL", "UNKNOWN", "UNKOWN",
    "DESCONHECIDO", "SEM DADOS", "SEM NOME", "NO NAME", "NOT APPLICABLE",
    "PRIVATE", "REDACTED", "WITHHELD", "UNKNOWN OWNER", "PRIVATE OWNER",
    "UNAVAILABLE OWNER", "UNAVAILABLE", "TAXPAYER OF", "OWNER OF",
}

# Substrings que denunciam placeholder em nomes compostos ("CHICAGO CITY OF",
# "* CITY OF", "OWNER OF RECORD"). Exato nao chega: o dataset escreve variantes.
_PLACEHOLDER_SUBSTRINGS = (
    "UNAVAILABLE",
    "TAXPAYER",
    "OWNER OF",
    "RAILROAD",
    "CITY OF",
    "UNKNOWN OWNER",
    "PRIVATE OWNER",
    "OWNER WITHHELD",
)


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

    # Variantes compostas: "CHICAGO CITY OF", "* CITY OF", "TAXPAYER OF",
    # "UNAVAILABLE OWNER". Sem isto, cada uma custava uma chamada paga.
    upper = cleaned.upper()
    if any(marker in upper for marker in _PLACEHOLDER_SUBSTRINGS):
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


def split_person_name(name: str, city: str | None = None) -> tuple[str, str]:
    """Parte um NOME DE PESSOA em (primeiro, ultimo).

    Ordem: os registos prediais de NYC/Boston/Dallas usam LAST FIRST [MIDDLE].
    Inverter so quando ha sinal:
      * 3+ tokens com inicial final ("MARCHIO PAUL A") -> FIRST = 2.º token;
      * 2 tokens numa cidade de registo ("PEACOCK TAWANNA") -> inverter.
    Fora disso mantem-se FIRST LAST (Chicago e nomes ja' corretos).

    Nomes corporativos NUNCA chegam aqui: `_lookup_searchbug_nape` omite
    FNAME/LNAME quando `is_corporate_name()` e True. O corte e por ultimo token,
    nao por palavras-chave, para nao partir "VAN DER BERG" nem "MARIA DE OLIVEIRA".
    """
    tokens = [t for t in re.split(r"\s+", (name or "").strip()) if t]
    if not tokens:
        return "", ""

    suffixes: list[str] = []
    while len(tokens) > 2 and tokens[-1].upper().strip(".") in _PERSON_SUFFIXES:
        suffixes.insert(0, tokens.pop())

    if len(tokens) == 1:
        return tokens[0], " ".join(suffixes)

    is_registry = (city or "").strip().upper() in _REGISTRY_ORDER_CITIES

    # Sinal forte de LAST FIRST M: inicial no fim.
    if len(tokens) >= 3 and len(tokens[-1].strip(".")) == 1:
        return tokens[1], " ".join([tokens[0]] + tokens[2:] + suffixes)

    if len(tokens) == 2 and is_registry:
        return tokens[1], " ".join([tokens[0]] + suffixes)

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
    # P0-C1: transporte e validacao nao sao "no_results" nem "error" pagos.
    if err.startswith("transport_error"):
        return "transport_error"
    if err.startswith("name_mismatch"):
        return "name_mismatch"
    if "5-digit zip" in err or "enter 5-digit" in err:
        return "invalid_request"
    if err.startswith("http 429") or "rate limit" in err:
        return "rate_limited"
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

        self.timeout = httpx.Timeout(
            getattr(settings, "SEARCHBUG_TIMEOUT_SECONDS", 10.0),
            connect=getattr(settings, "SEARCHBUG_CONNECT_TIMEOUT_SECONDS", 5.0),
        )
        self._mock_mode = False  # Always try real providers first
        # telefone -> (timestamp_monotonic, telefone ou None para "sem resultado")
        self._phone_cache: dict[str, tuple[float, Optional[str]]] = {}
        # Client partilhado. Sem isto cada chamada pagava DNS + TCP + TLS
        # (3 RTT) contra o mesmo host, o que dominava a latencia observada.
        self._client: Optional[httpx.AsyncClient] = None
        self._client_lock = asyncio.Lock()
        # P0-C1: circuit breaker de transporte (process-local, suficiente para
        # um unico worker uvicorn; se houver multiplos, cada um tem o seu).
        self._transport_failures = 0
        self._circuit_open_until = 0.0

        enabled = []
        if self.searchbug_key:
            enabled.append("Searchbug")
        logger.info(f"PhoneLookup: LIVE MODE enabled. Providers: {', '.join(enabled)}")

    async def _get_client(self) -> httpx.AsyncClient:
        """Cliente httpx partilhado, criado uma vez e reutilizado.

        verify=True: a credencial da conta trafega em claro no body; desligar a
        verificacao TLS expoe-la a qualquer MITM.
        """
        if self._client is None:
            async with self._client_lock:
                if self._client is None:
                    self._client = httpx.AsyncClient(
                        timeout=self.timeout,
                        verify=True,
                        follow_redirects=True,
                        limits=httpx.Limits(
                            max_connections=10,
                            max_keepalive_connections=5,
                            keepalive_expiry=30.0,
                        ),
                    )
        return self._client

    async def aclose(self) -> None:
        """Fecha o client partilhado (chamado no shutdown da app)."""
        client = self._client
        self._client = None
        if client is not None:
            try:
                await client.aclose()
            except Exception as e:
                logger.warning(f"Falha ao fechar client HTTP do phone lookup: {e}")

    async def lookup_phone(self, address: str, city: str, state: str,
                           owner_name: str | None = None, zip_code: str | None = None,
                           owner_class: str | None = None,
                           lead_id: int | None = None) -> "PhoneLookupResult":
        """Waterfall L2/L3 phone lookup via Searchbug api_nape.

        L2 (Name + Address): Para leads PRIVATE com owner_name verificado.
        - Usa FNAME/LNAME + ADDRESS/CITY/STATE/ZIP
        - So chamado quando owner_class == "private" E clean_name existe

        L3 (Address-only): Para leads UNKNOWN com endereco resolvivel.
        - Usa apenas ADDRESS/CITY/STATE/ZIP (sem FNAME/LNAME)
        - Desligado por defeito (PHONE_L3_UNNAMED_ENABLED=0): custo sem
          possibilidade de cobranca. Quando ligado, entrega "sob consulta".

        INSTITUTIONAL leads: NUNCA consultados (guard_skipped institucional).

        Regra de custo: esta e a etapa FINAL e PAGA, chamada apenas depois do
        enriquecimento gratuito.

        P0-C1: ZIP normalizado para 5 digitos; transporte nao e' faturado;
        retry unico + circuit breaker; validacao por `name_match`.
        """
        # Resolve owner_class se nao fornecido
        if owner_class is None:
            from .lead_rules import get_owner_class
            owner_class = get_owner_class(owner_name)

        # P0-C1: Boston grava 4 digitos; a Searchbug rejeita-os. Normalizar
        # antes da cache key para "2114" e "02114" partilharem a mesma entrada.
        zip_code = normalize_zip(zip_code)

        # GUARD: endereco nao resolvivel = nao consultar (L2 e L3)
        if not address_is_resolvable(address):
            logger.info(
                f"[PHONE][guard_skipped] address_incompleta para {address!r} — "
                f"provider NAO foi consultado (custo zero)"
            )
            searchbug_metrics.record(
                outcome="guard_skipped", billed=False, city=city,
                error="address_incompleta", lead_id=lead_id, owner_class=owner_class,
            )
            return PhoneLookupResult(
                success=False,
                error="guard_skipped:address_incompleta",
                provider="none",
            )

        clean_name, name_error = _clean_owner_name(owner_name)

        # P0-C1: sem nome NAO e' o mesmo que nome invalido. Um lead sem nome
        # pode usar L3 (address-only) se a flag estiver ligada; placeholders
        # ("UNAVAILABLE OWNER") continuam guardados sempre.
        unnamed_l3 = (
            name_error == "owner_name_ausente"
            and bool(getattr(settings, "PHONE_L3_UNNAMED_ENABLED", False))
        )
        if name_error and not unnamed_l3:
            logger.info(
                f"[PHONE][guard_skipped] {name_error} para address={address!r} — "
                f"provider NAO foi consultado (custo zero)"
            )
            searchbug_metrics.record(
                outcome="guard_skipped", billed=False, city=city, error=name_error,
                lead_id=lead_id, owner_class=owner_class,
            )
            return PhoneLookupResult(
                success=False,
                error=f"guard_skipped:{name_error}",
                provider="none",
            )
        if unnamed_l3:
            clean_name = None

        # GUARD_SKIPPED institucional: entidades publicas nao tem telefone de pessoa
        if is_institutional_name(clean_name) or owner_class == "institutional":
            logger.info(
                f"[PHONE][guard_skipped] institucional para address={address!r} "
                f"owner={clean_name!r} — provider NAO foi consultado (custo zero)"
            )
            searchbug_metrics.record(
                outcome="guard_skipped", billed=False, city=city, error="institucional",
                lead_id=lead_id, owner_class=owner_class,
            )
            return PhoneLookupResult(
                success=False,
                error="guard_skipped:institucional",
                provider="none",
            )

        # Decide camada (L2 ou L3) baseada no owner_class E tipo de nome
        # L2 (Name+Address): apenas para private com nome de PESSOA (nao corporativo)
        # L3 (Address-only): para unknown, OU private com nome corporativo
        is_person_name = clean_name is not None and not is_corporate_name(clean_name)
        use_name = owner_class == "private" and is_person_name
        layer = "L2" if use_name else "L3"

        # L3 nao usa o nome: nao pode entrar na chave. Duas grafias do mesmo
        # endereco geravam duas entradas e duas chamadas pagas.
        cache_key = self._cache_key(
            address, city, state, zip_code,
            clean_name if layer == "L2" else None,
            layer=layer,
        )
        cached = self._phone_cache_get(cache_key)
        if cached is not None:
            phone, was_hit, was_negative, cached_verified = cached
            if not was_negative:
                searchbug_metrics.record(
                    outcome="cache_hit", billed=False, city=city, error=None,
                    lead_id=lead_id, owner_class=owner_class, layer=layer,
                    transport_error=0,
                )
                return PhoneLookupResult(
                    success=True,
                    phone=phone,
                    provider="cache",
                    verified=cached_verified,
                    layer=layer,
                )
            searchbug_metrics.record(
                outcome="cache_negative", billed=False, city=city, error=None,
                lead_id=lead_id, owner_class=owner_class, layer=layer,
                transport_error=0,
            )
            return PhoneLookupResult(
                success=False,
                error="cache_sem_resultado",
                provider="cache",
                layer=layer,
            )

        # P0-C1: circuit breaker. A cache ja' foi consultada; so' bloqueia
        # chamadas novas quando o provider esta' instavel.
        if self._circuit_is_open():
            searchbug_metrics.record(
                outcome="transport_error", billed=False, city=city,
                error="transport_error:circuit_open",
                lead_id=lead_id, owner_class=owner_class, layer=layer,
                transport_error=1,
            )
            return PhoneLookupResult(
                success=False,
                error="transport_error:circuit_open",
                provider="none",
                layer=layer,
            )

        # L2: Name + Address (apenas para private com nome limpo)
        if layer == "L2":
            logger.info(f"[PHONE][L2] Name+Address para {address!r}, {city} owner={clean_name!r}")
            result = await self._call_with_retry(
                self._lookup_searchbug_nape,
                address, city, state,
                owner_name=clean_name, zip_code=zip_code,
                lead_id=lead_id, owner_class=owner_class, layer="L2",
            )
            result.layer = "L2"
            if result.success and result.phone:
                logger.info(f"Phone lookup L2 successful for {address}, {city}, {state}")
                self._phone_cache_put(cache_key, result.phone, result.verified)
                return result

            outcome = classify_searchbug_outcome(result.success, result.error)
            logger.warning(
                f"[PHONE][L2][{outcome}] sem telefone para {address!r}, {city} "
                f"({result.error})"
            )
            # Cache negativo so' quando o resultado e' definitivo. Transporte,
            # timeout e invalid_request nao envenenam a cache.
            if outcome in ("no_results", "name_mismatch"):
                self._phone_cache_put(cache_key, None)
            # L2 falhou -> L3 apenas em erros transitorios. Um name_mismatch
            # nao melhora com address-only; um no_results tambem nao.
            if outcome in ("timeout", "http_error") and address_is_resolvable(address):
                logger.info(f"[PHONE][L2->L3] L2 falhou ({outcome}), tentando L3 para {address!r}, {city}")
                return await self._lookup_l3(
                    address, city, state, zip_code, cache_key,
                    lead_id=lead_id, owner_class=owner_class,
                )
            return result

        # L3: Address-only (sem nome, quando a flag permite)
        return await self._lookup_l3(
            address, city, state, zip_code, cache_key,
            lead_id=lead_id, owner_class=owner_class,
        )

    async def _lookup_l3(self, address: str, city: str, state: str,
                         zip_code: str | None, cache_key: str,
                         lead_id: int | None = None,
                         owner_class: str | None = None) -> "PhoneLookupResult":
        """L3: Address-only lookup via api_nape (sem FNAME/LNAME).

        P0-C1: o resultado e' sempre `verified=False` (nao ha nome para
        comparar). Entrega-se como "sob consulta", sem selo de alta probabilidade.
        """
        logger.info(f"[PHONE][L3] Address-only para {address!r}, {city}")
        result = await self._call_with_retry(
            self._lookup_searchbug_nape,
            address, city, state,
            owner_name=None, zip_code=zip_code,
            lead_id=lead_id, owner_class=owner_class, layer="L3",
        )
        result.layer = "L3"
        result.verified = False
        if result.success and result.phone:
            logger.info(f"Phone lookup L3 successful for {address}, {city}, {state}")
            self._phone_cache_put(cache_key, result.phone, False)
            return result

        outcome = classify_searchbug_outcome(result.success, result.error)
        logger.warning(
            f"[PHONE][L3][{outcome}] sem telefone para {address!r}, {city} "
            f"({result.error})"
        )
        if outcome == "no_results":
            self._phone_cache_put(cache_key, None)
        return PhoneLookupResult(
            success=False,
            error=result.error or "L3 no results",
            provider="Searchbug",
            layer="L3",
        )

    # ---------------------------------------------------- P0-C1: transporte
    def _circuit_is_open(self) -> bool:
        return time.monotonic() < self._circuit_open_until

    def _note_transport_failure(self) -> None:
        self._transport_failures += 1
        limit = int(getattr(settings, "PHONE_CIRCUIT_FAILURES", 3) or 3)
        if self._transport_failures >= limit:
            cooldown = float(getattr(settings, "PHONE_CIRCUIT_COOLDOWN_S", 60) or 60)
            self._circuit_open_until = time.monotonic() + cooldown
            logger.warning(
                "[PHONE][circuit] %s falhas de transporte consecutivas — pausa %.0fs",
                self._transport_failures, cooldown,
            )

    def _reset_transport_failures(self) -> None:
        self._transport_failures = 0

    async def _call_with_retry(self, fn, *args, **kwargs) -> "PhoneLookupResult":
        """Executa uma chamada paga com 1 retry em transport_error.

        Transport errors nao sao faturados (ver `_lookup_searchbug_nape`), por
        isso o retry nao duplica custo. Um `no_results` nunca e' repetido.
        """
        result = await fn(*args, **kwargs)
        outcome = classify_searchbug_outcome(result.success, result.error)
        if outcome != "transport_error":
            self._reset_transport_failures()
            return result

        self._note_transport_failure()
        if self._circuit_is_open():
            return result

        delay = float(getattr(settings, "PHONE_TRANSPORT_RETRY_DELAY_S", 1.5) or 1.5)
        logger.info("[PHONE][retry] transport_error — nova tentativa em %.1fs", delay)
        await asyncio.sleep(delay)
        result = await fn(*args, **kwargs)
        if classify_searchbug_outcome(result.success, result.error) == "transport_error":
            self._note_transport_failure()
        else:
            self._reset_transport_failures()
        return result

    def _cache_key(
        self,
        address: str,
        city: str,
        state: str,
        zip_code: str | None,
        clean_name: str | None,
        layer: str = "L2",
    ) -> str:
        """Chave de cache do telefone.

        Inclui o ZIP: o mesmo address/city/state com ZIP diferente e outro
        imovel. Sem ele, um "nao achou" em Park Ave contaminava o 11201.

        Inclui a layer (L2/L3): L2 e L3 sao consultas diferentes para o mesmo
        endereco. Sem isso, um negativo L2 bloquearia uma potencial L3.

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
                layer.upper(),
            ]
        )

    def _phone_cache_get(self, key: str) -> tuple[Optional[str], bool, bool, bool] | None:
        """Devolve (telefone, hit, negativo, verificado) ou None em cache miss."""
        entry = self._phone_cache.get(key)
        if entry is None:
            return None
        # Tolerar entradas antigas de 2 elementos (cache em memoria de um
        # processo que fez hot-reload antes do P0-C1).
        if len(entry) == 2:
            stored_at, phone = entry
            verified = False
        else:
            stored_at, phone, verified = entry
        ttl = _PHONE_CACHE_TTL_OK if phone else _PHONE_CACHE_TTL_FAIL
        if time.monotonic() - stored_at > ttl:
            self._phone_cache.pop(key, None)
            return None
        return phone, True, phone is None, bool(verified)

    def _phone_cache_put(
        self, key: str, phone: Optional[str], verified: bool = False
    ) -> None:
        if len(self._phone_cache) >= _PHONE_CACHE_MAX:
            # dicionario-ordered: remove a entrada mais antiga
            self._phone_cache.pop(next(iter(self._phone_cache)), None)
        self._phone_cache[key] = (time.monotonic(), phone, bool(verified))

    async def _lookup_searchbug(self, address: str, city: str, state: str, owner_name: str | None = None, zip_code: str | None = None) -> "PhoneLookupResult":
        """Lookup via Searchbug Contact Info API (api_contact) — LEGACY.

        Requer SEARCHBUG_ACCOUNT_CODE (CO_CODE) e SEARCHBUG_API_KEY (PASS).
        Endpoint: POST https://data.searchbug.com/api/search.aspx
        Retorna Data.RECORD[].PHONES.PHONE[]
        """
        return await self._lookup_searchbug_nape(
            address, city, state, owner_name=owner_name, zip_code=zip_code, use_api_contact=True
        )

    async def _lookup_searchbug_nape(self, address: str, city: str, state: str,
                                     owner_name: str | None = None, zip_code: str | None = None,
                                     use_api_contact: bool = False,
                                     lead_id: int | None = None,
                                     owner_class: str | None = None,
                                     layer: str | None = None) -> "PhoneLookupResult":
        """Lookup via Searchbug People Search API (api_nape).

        Requer SEARCHBUG_ACCOUNT_CODE (CO_CODE) e SEARCHBUG_API_KEY (PASS).
        Endpoint: POST https://data.searchbug.com/api/search.aspx
        Tipo: api_nape (mais barato que api_contact).
        Resposta: Data.RECORD[].FNAME, LNAME, PHONE (simples, nao PHONES.PHONE[]).

        P0-C1:
          * ZIP normalizado para 5 digitos (Boston: 2114 -> 02114);
          * resposta vazia/nao-JSON = `transport_error`, NAO faturada;
          * `name_match < 0.6` = `name_mismatch`, telefone NAO entregue;
          * L3 (sem nome) devolve telefone com `verified=False` ("sob consulta").
        """
        account_code = getattr(settings, "SEARCHBUG_ACCOUNT_CODE", None) or os.getenv("SEARCHBUG_ACCOUNT_CODE")
        api_key = self.searchbug_key
        layer = layer or ("L2" if owner_name else "L3")
        zip_code = normalize_zip(zip_code)

        # Fase 2: medicao de custo. `_record` e chamado em TODOS os returns
        # abaixo e nunca levanta: e a unica forma de o preco por consulta
        # ser auditavel. `billed` distingue o que custou dinheiro do que foi
        # cortado antes da rede ou falhou no transporte.
        started = time.monotonic()

        def _record(result: "PhoneLookupResult", *, billed: bool, http_status: Optional[int] = None) -> "PhoneLookupResult":
            try:
                outcome = classify_searchbug_outcome(result.success, result.error)
                searchbug_metrics.record(
                    outcome=outcome,
                    billed=1 if billed else 0,
                    latency_ms=int((time.monotonic() - started) * 1000),
                    http_status=http_status,
                    city=city,
                    error=result.error,
                    lead_id=lead_id,
                    owner_class=owner_class,
                    layer=layer,
                    name_match=result.name_match,
                    transport_error=1 if outcome == "transport_error" else 0,
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
                    provider="Searchbug",
                    layer=layer,
                ),
                billed=False,
            )

        # FNAME/LNAME so quando o owner_name e mesmo uma PESSOA. Um nome
        # corporativo ou institucional nao tem primeiro/ultimo nome: envia-lo
        # partido ("65" / "MS LLC", "NYC" / "HOUSING AUTHORITY") estraga o match
        # e custa uma chamada paga. Sem estes campos a consulta continua a
        # funcionar pela morada, que e a chave real.
        fname = lname = ""
        if owner_name and not is_corporate_name(owner_name) and not is_institutional_name(owner_name):
            fname, lname = split_person_name(owner_name, city=city)

        clean_address = normalize_provider_address(address, city, state)

        # Form data para POST
        form_data = {
            "CO_CODE": account_code,
            "PASS": api_key,
            "TYPE": "api_contact" if use_api_contact else "api_nape",
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
            client = await self._get_client()
            response = await client.post(
                "https://data.searchbug.com/api/search.aspx",
                data=form_data,
            )

            if response.status_code != 200:
                logger.error(
                    f"Searchbug HTTP {response.status_code} for {address}, {city}, {state}: "
                    f"{response.text[:500]}"
                )
                # P0-C1: 4xx (auth/validacao/rate) e 5xx sao transporte, nao
                # busca faturavel. A fatura e a autoridade final.
                return _record(
                    PhoneLookupResult(
                        success=False,
                        error=f"HTTP {response.status_code}: {response.text[:200]}",
                        provider="Searchbug",
                        layer=layer,
                    ),
                    billed=False,
                    http_status=response.status_code,
                )

            body = response.text or ""
            if not body.strip() or body.lstrip()[:1] not in ("{", "["):
                return _record(
                    PhoneLookupResult(
                        success=False,
                        error="transport_error:empty_or_non_json",
                        provider="Searchbug",
                        layer=layer,
                    ),
                    billed=False,
                    http_status=200,
                )

            try:
                data = response.json()
            except ValueError:
                return _record(
                    PhoneLookupResult(
                        success=False,
                        error="transport_error:invalid_json",
                        provider="Searchbug",
                        layer=layer,
                    ),
                    billed=False,
                    http_status=200,
                )

            if not isinstance(data, dict):
                return _record(
                    PhoneLookupResult(
                        success=False,
                        error="transport_error:invalid_payload",
                        provider="Searchbug",
                        layer=layer,
                    ),
                    billed=False,
                    http_status=200,
                )

            # Resposta de erro da API
            status = (data.get("Status") or data.get("STATUS") or "").upper()
            if status in ("ERROR", "NORESULTS"):
                error = str(data.get("ERROR") or data.get("Error") or "No results")
                err_lower = error.lower()
                # ZIP invalido e' erro de pedido, nao uma busca faturavel.
                if "5-digit zip" in err_lower or "enter 5-digit" in err_lower:
                    return _record(
                        PhoneLookupResult(
                            success=False, error=error, provider="Searchbug",
                            raw=data, layer=layer,
                        ),
                        billed=False,
                        http_status=200,
                    )
                # no_results nao e cobrado segundo documentacao Searchbug.
                return _record(
                    PhoneLookupResult(
                        success=False, error=error, provider="Searchbug",
                        raw=data, layer=layer,
                    ),
                    billed=(status != "NORESULTS"),
                    http_status=200,
                )

            # Extrai telefone do formato api_nape: Data.RECORD[].FNAME, LNAME, PHONE
            data_obj = data.get("Data") or data.get("DATA")
            if not data_obj:
                return _record(
                    PhoneLookupResult(
                        success=False,
                        error="Unexpected response format (no Data)",
                        provider="Searchbug",
                        raw=data,
                        layer=layer,
                    ),
                    billed=True,
                    http_status=200,
                )

            records = data_obj.get("RECORD") or data_obj.get("Record") or []
            if isinstance(records, dict):
                records = [records]

            min_match = float(getattr(settings, "PHONE_NAME_MATCH_MIN", 0.6) or 0.6)

            for rec in records:
                phone = rec.get("PHONE") or rec.get("Phone")
                if not (phone and str(phone).strip()):
                    continue

                first = rec.get("FNAME") or rec.get("FirstName")
                last = rec.get("LNAME") or rec.get("LastName")
                match = compute_name_match(owner_name, first, last) if owner_name else None

                # L2: o telefone so' e' entregue se o nome bater. Um registo
                # sem nome devolvido tambem nao valida (match None).
                if owner_name and (match is None or match < min_match):
                    return _record(
                        PhoneLookupResult(
                            success=False,
                            phone=normalize_us_phone(str(phone).strip()),
                            error="name_mismatch",
                            provider="Searchbug",
                            raw=data,
                            name_match=match,
                            verified=False,
                            returned_first=first,
                            returned_last=last,
                            layer=layer,
                        ),
                        billed=True,
                        http_status=200,
                    )

                verified = bool(match is not None and match >= min_match)
                return _record(
                    PhoneLookupResult(
                        success=True,
                        phone=normalize_us_phone(str(phone).strip()),
                        phone_type=str(rec.get("PHONE_TYPE") or rec.get("PhoneType") or "").strip().lower() or None,
                        carrier=str(rec.get("CARRIER") or rec.get("Carrier") or "").strip() or None,
                        is_connected=bool(rec.get("IS_CONNECTED") or rec.get("IsConnected")) if rec.get("IS_CONNECTED") or rec.get("IsConnected") else None,
                        provider="Searchbug",
                        raw=data,
                        name_match=match,
                        verified=verified,
                        returned_first=first,
                        returned_last=last,
                        layer=layer,
                    ),
                    billed=True,
                    http_status=200,
                )

            # Sem telefone nos resultados
            return _record(
                PhoneLookupResult(
                    success=False, error="No phone found in results",
                    provider="Searchbug", raw=data, layer=layer,
                ),
                billed=False,  # no_results nao e cobrado
                http_status=200,
            )

        except Exception as e:
            logger.warning(f"Searchbug People Search API (api_nape) error: {e}")
            # P0-C1: falha de transporte nao e' faturada; o retry decide.
            return _record(
                PhoneLookupResult(
                    success=False,
                    error=f"transport_error:{type(e).__name__}",
                    provider="Searchbug",
                    layer=layer,
                ),
                billed=False,
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

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
from dataclasses import dataclass
from typing import Optional

import httpx

from ..config import settings
from ..utils.logger import logger


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


def _address_is_resolvable(address: str) -> bool:
    """Um endereco so com o numero ("9630") nunca vai resolver para um dono.

    parse_address exige numero E rua, logo estes leads nao tm enriquecimento
    possivel. Recusar aqui evita pagar por uma consulta garantidamente inuttil.
    """
    if not address:
        return False
    parts = str(address).split(",")[0].strip()
    return len(parts.split()) >= 2


class PhoneLookupService:
    """Multi-provider phone lookup with fallback chain."""

    def __init__(self):
        # Provider configs (env vars)
        self.searchbug_key = getattr(settings, "SEARCHBUG_API_KEY", None) or os.getenv("SEARCHBUG_API_KEY")

        self.timeout = httpx.Timeout(20.0, connect=10.0)
        self._mock_mode = False  # Always try real providers first

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
        if not _address_is_resolvable(address):
            return PhoneLookupResult(
                success=False,
                error="address_incompleta",
                provider="none",
            )

        clean_name, name_error = _clean_owner_name(owner_name)
        if name_error:
            return PhoneLookupResult(
                success=False,
                error=name_error,
                provider="none",
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
                    return result
                else:
                    logger.warning(f"Provider {name} failed for {address}: {result.error}")
            except Exception as e:
                logger.warning(f"Provider {name} exception for {address}: {e}")

        # All providers failed
        return PhoneLookupResult(
            success=False,
            error="All phone lookup providers failed",
            provider="none"
        )

    async def _lookup_searchbug(self, address: str, city: str, state: str, owner_name: str | None = None, zip_code: str | None = None) -> "PhoneLookupResult":
        """Lookup via Searchbug Contact Info API (api_contact).

        Requer SEARCHBUG_ACCOUNT_CODE (CO_CODE) e SEARCHBUG_API_KEY (PASS).
        Endpoint: POST https://data.searchbug.com/api/search.aspx
        """
        account_code = getattr(settings, "SEARCHBUG_ACCOUNT_CODE", None) or os.getenv("SEARCHBUG_ACCOUNT_CODE")
        api_key = self.searchbug_key

        if not account_code or not api_key:
            return PhoneLookupResult(
                success=False,
                error="Searchbug CO_CODE (account number) or API key not configured",
                provider="Searchbug"
            )

        # Extrai primeiro/último nome do owner_name se disponível
        fname = lname = ""
        if owner_name:
            parts = owner_name.strip().split()
            if parts:
                fname = parts[0]
                if len(parts) > 1:
                    lname = " ".join(parts[1:])

        # Form data para POST
        form_data = {
            "CO_CODE": account_code,
            "PASS": api_key,
            "TYPE": "api_contact",
            "FORMAT": "JSON",
            "ADDRESS": address,
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
            async with httpx.AsyncClient(timeout=20.0, verify=False) as client:
                response = await client.post(
                    "https://data.searchbug.com/api/search.aspx",
                    data=form_data,
                    timeout=20.0,
                    follow_redirects=True
                )

                if response.status_code != 200:
                    logger.error(f"Searchbug HTTP {response.status_code} for {address}, {city}, {state}: {response.text[:500]}")
                    return PhoneLookupResult(success=False, error=f"HTTP {response.status_code}: {response.text[:200]}", provider="Searchbug")

                data = response.json()

                # Resposta de erro da API
                status = data.get("Status") or data.get("STATUS")
                if status and status.upper() in ("ERROR", "NORESULTS"):
                    error = data.get("ERROR") or data.get("Error") or "No results"
                    return PhoneLookupResult(success=False, error=str(error), provider="Searchbug", raw=data)

                # Extrai telefone do formato novo: Data.RECORD[].PHONES.PHONE[]
                data_obj = data.get("Data") or data.get("DATA")
                if not data_obj:
                    return PhoneLookupResult(success=False, error="Unexpected response format (no Data)", provider="Searchbug", raw=data)

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
                            return PhoneLookupResult(
                                success=True,
                                phone=normalize_us_phone(str(phone).strip()),
                                phone_type=str(rec.get("PHONE_TYPE") or rec.get("PhoneType") or "").strip().lower() or None,
                                carrier=str(rec.get("CARRIER") or rec.get("Carrier") or "").strip() or None,
                                is_connected=bool(rec.get("IS_CONNECTED") or rec.get("IsConnected")) if rec.get("IS_CONNECTED") or rec.get("IsConnected") else None,
                                provider="Searchbug",
                                raw=data
                            )

                return PhoneLookupResult(success=False, error="No phone found in results", provider="Searchbug", raw=data)

        except Exception as e:
            logger.warning(f"Searchbug Contact Info API error: {e}")
            return PhoneLookupResult(success=False, error=str(e), provider="Searchbug")

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

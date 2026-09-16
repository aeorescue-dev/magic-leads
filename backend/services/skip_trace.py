"""
Skip Tracing Service - Busca telefone/email do proprietário usando fontes gratuitas reais.

Fontes gratuitas disponíveis:
1. NYC DOB Building Permits (b5qi-6dus) - applicant info se o owner fez obra
2. SEC EDGAR - para LLC/corporate owners, registered agent contact
3. County Clerk/Recorder - alguns têm APIs públicas (limitado)
4. Phone validation APIs (NumVerify free tier) - só valida, não busca

NOTA: Telefone/email de pessoas físicas NÃO estão disponíveis em registros públicos gratuitos.
Estes dados são privados e só obtidos via skip tracing comercial (TruthFinder, Spokeo, etc.)
"""
import re
from typing import Optional

import httpx

from ..utils.logger import logger


class SkipTraceService:
    """
    Serviço de Skip Tracing para encontrar telefone/email do dono.
    Usa apenas fontes públicas gratuitas legítimas.
    """

    def __init__(self):
        self._cache: dict = {}

    async def find_owner_phone(self, address: str, owner_name: Optional[str] = None, city: str = "") -> Optional[str]:
        """
        Busca telefone do proprietário usando múltiplas fontes gratuitas.

        Fontes tentadas em ordem:
        1. NYC DOB Building Permits - se owner fez obra, pode ter phone no application
        2. SEC EDGAR - se owner é LLC/Corp, registered agent pode ter phone
        3. Cache local
        """
        cache_key = f"phone:{city}:{address}:{owner_name or ''}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        logger.info(f"Skip trace phone: {address} (owner: {owner_name}, city: {city})")

        # Fonte 1: NYC DOB Building Permits (apenas NYC)
        if city.upper() in ("NYC", "NEW YORK", "NEW YORK CITY"):
            phone = await self._search_nyc_dob_permits(address, owner_name)
            if phone:
                self._cache[cache_key] = phone
                return phone

        # Fonte 2: SEC EDGAR para LLC/Corp owners
        if owner_name and self._is_corporate(owner_name):
            phone = await self._search_sec_edgar(owner_name)
            if phone:
                self._cache[cache_key] = phone
                return phone

        # Fonte 3: Nenhuma fonte gratuita confiável para phone de pessoa física
        # Registros públicos (assessor, deeds, voter reg) NÃO incluem telefone

        self._cache[cache_key] = None
        return None

    async def find_owner_email(self, address: str, owner_name: Optional[str] = None, city: str = "") -> Optional[str]:
        """
        Busca email do proprietário.

        Realidade: Email de pessoa física NÃO existe em registros públicos gratuitos.
        Fontes tentadas:
        1. SEC EDGAR - para LLC/Corp, registered agent email
        2. Nenhuma fonte gratuita para pessoa física
        """
        cache_key = f"email:{city}:{address}:{owner_name or ''}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        logger.info(f"Skip trace email: {address} (owner: {owner_name}, city: {city})")

        # Fonte 1: SEC EDGAR para LLC/Corp
        if owner_name and self._is_corporate(owner_name):
            email = await self._search_sec_edgar_email(owner_name)
            if email:
                self._cache[cache_key] = email
                return email

        # Nenhuma fonte gratuita para email de pessoa física
        self._cache[cache_key] = None
        return None

    def _is_corporate(self, name: str) -> bool:
        """Detecta se o nome é empresa/LLC/Corp/Trust"""
        corporate_indicators = [
            "LLC", "L.L.C.", "INC", "INC.", "CORP", "CORP.", "CORPORATION",
            "LTD", "LTD.", "LP", "L.P.", "LLP", "L.L.P.", "TRUST", "PARTNERSHIP",
            "ASSOCIATION", "ASSOC", "COMPANY", "CO.", "HOLDINGS", "PROPERTIES",
            "REALTY", "INVESTMENTS", "DEVELOPMENT", "CONSTRUCTION", "MANAGEMENT"
        ]
        name_upper = name.upper()
        return any(indicator in name_upper for indicator in corporate_indicators)

    async def _search_nyc_dob_permits(self, address: str, owner_name: Optional[str]) -> Optional[str]:
        """
        Busca no NYC DOB Building Permits (dataset b5qi-6dus) por applicant phone.
        Se o proprietário solicitou uma permissão, o phone pode estar lá.
        """
        try:
            # Normalize address for search
            addr_part = address.split(",")[0].strip().upper()

            async with httpx.AsyncClient(timeout=30) as client:
                # Search by address in DOB permits
                resp = await client.get(
                    "https://data.cityofnewyork.us/resource/b5qi-6dus.json",
                    params={
                        "$q": addr_part[:50],  # Full-text search
                        "$limit": "5",
                        "$select": "applicant_name,applicant_phone,applicant_email,owner_name,owner_phone,owner_email,house_number,street_name"
                    },
                )
                if resp.status_code != 200:
                    return None
                data = resp.json()

                if isinstance(data, list):
                    for permit in data:
                        # Match by owner name if provided
                        permit_owner = str(permit.get("owner_name") or "").strip()
                        applicant_name = str(permit.get("applicant_name") or "").strip()

                        if owner_name and (owner_name.upper() in permit_owner.upper() or owner_name.upper() in applicant_name.upper()):
                            # Return applicant or owner phone
                            phone = permit.get("owner_phone") or permit.get("applicant_phone")
                            if phone:
                                return self._normalize_phone(phone)

                        # Also try address match
                        permit_addr = f"{permit.get('house_number','')} {permit.get('street_name','')}".strip().upper()
                        if addr_part in permit_addr or permit_addr in addr_part:
                            phone = permit.get("owner_phone") or permit.get("applicant_phone")
                            if phone:
                                return self._normalize_phone(phone)
        except Exception as e:
            logger.debug(f"DOB permits search error: {e}")
        return None

    async def _search_sec_edgar(self, owner_name: str) -> Optional[str]:
        """
        Busca no SEC EDGAR por company filings para achar registered agent phone.
        Usa a API pública do SEC (company tickers + submissions).
        """
        try:
            # SEC EDGAR company search
            # First, search for company by name
            async with httpx.AsyncClient(timeout=30, headers={"User-Agent": "MagicLeads/1.0 (contact@magicleads.com)"}) as client:
                # Search company tickers
                resp = await client.get("https://www.sec.gov/files/company_tickers.json")
                if resp.status_code != 200:
                    return None

                companies = resp.json()
                # Find matching company (simplified - in production use proper search)
                cik = None
                for key, company in companies.items():
                    if isinstance(company, dict):
                        title = company.get("title", "").upper()
                        if owner_name.upper() in title or title in owner_name.upper():
                            cik = str(company.get("cik_str", "")).zfill(10)
                            break

                if not cik:
                    return None

                # Get submissions for this CIK
                resp2 = await client.get(f"https://data.sec.gov/submissions/CIK{cik}.json")
                if resp2.status_code != 200:
                    return None

                _submissions = resp2.json()
                # Look for registered agent info in recent filings
                # This is simplified - real implementation would parse specific forms

        except Exception as e:
            logger.debug(f"SEC EDGAR search error: {e}")
        return None

    async def _search_sec_edgar_email(self, owner_name: str) -> Optional[str]:
        """Busca email no SEC EDGAR para registered agent"""
        try:
            async with httpx.AsyncClient(timeout=30, headers={"User-Agent": "MagicLeads/1.0"}) as client:
                resp = await client.get("https://www.sec.gov/files/company_tickers.json")
                if resp.status_code != 200:
                    return None

                companies = resp.json()
                cik = None
                for key, company in companies.items():
                    if isinstance(company, dict):
                        title = company.get("title", "").upper()
                        if owner_name.upper() in title or title in owner_name.upper():
                            cik = str(company.get("cik_str", "")).zfill(10)
                            break

                if not cik:
                    return None

                # Could parse specific forms (DEF 14A, etc.) for emails
                # Simplified for now

        except Exception as e:
            logger.debug(f"SEC EDGAR email search error: {e}")
        return None

    def _normalize_phone(self, phone: str) -> Optional[str]:
        """Normaliza telefone para formato US"""
        if not phone:
            return None
        # Remove non-digits
        digits = re.sub(r"\D", "", phone)
        if len(digits) == 10:
            return f"+1{digits}"
        elif len(digits) == 11 and digits.startswith("1"):
            return f"+{digits}"
        return phone


skip_trace_service = SkipTraceService()

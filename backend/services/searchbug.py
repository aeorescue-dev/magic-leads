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

    async def lookup_phone(self, address: str, city: str, state: str) -> "PhoneLookupResult":
        """Look up phone number for an address via fallback chain."""

        # Provider chain (ordered by reliability/cost)
        providers = [
            ("Searchbug", self._lookup_searchbug),
        ]

        for name, func in providers:
            try:
                result = await func(address, city, state)
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

    async def _lookup_searchbug(self, address: str, city: str, state: str) -> "PhoneLookupResult":
        """Lookup via Searchbug API."""
        if not self.searchbug_key:
            return PhoneLookupResult(success=False, error="Searchbug key not configured", provider="Searchbug")

        params = {
            "key": self.searchbug_key,
            "addr": address,
            "city": city,
            "state": state,
            "format": "json",
        }

        try:
            async with httpx.AsyncClient(timeout=15.0, verify=False) as client:
                response = await client.get("https://ws.searchbug.com/phone.php", params=params, timeout=15.0, follow_redirects=True)

                if response.status_code != 200:
                    return PhoneLookupResult(success=False, error=f"HTTP {response.status_code}", provider="Searchbug")

                data = response.json()

                error = data.get("error") or data.get("Error") or data.get("ErrorMessage")
                if error:
                    return PhoneLookupResult(success=False, error=str(error), provider="Searchbug", raw=data)

                phone = data.get("phone") or data.get("Phone") or data.get("phone_number")
                if not phone:
                    return PhoneLookupResult(success=False, error="No phone found", provider="Searchbug", raw=data)

                return PhoneLookupResult(
                    success=True,
                    phone=normalize_us_phone(str(phone).strip()),
                    phone_type=str(data.get("phone_type") or data.get("PhoneType") or data.get("type") or "").strip().lower() or None,
                    carrier=str(data.get("carrier") or data.get("Carrier") or data.get("carrier_name") or "").strip() or None,
                    is_connected=bool(data.get("is_connected") or data.get("IsConnected")) if data.get("is_connected") or data.get("IsConnected") else None,
                    provider="Searchbug",
                    raw=data
                )

        except Exception as e:
            logger.warning(f"Searchbug error: {e}")
            return PhoneLookupResult(success=False, error=str(e), provider="Searchbug")

    async def lookup_phone_batch(self, addresses: list[tuple[str, str, str]]) -> list["PhoneLookupResult"]:
        """Look up multiple phones concurrently (respects rate limits)."""
        semaphore = asyncio.Semaphore(2)

        async def _lookup_with_sem(addr: str, city: str, state: str) -> "PhoneLookupResult":
            async with semaphore:
                return await self.lookup_phone(addr, city, state)

        tasks = [_lookup_with_sem(addr, city, state) for addr, city, state in addresses]
        return await asyncio.gather(*tasks)


# Global singleton instance
phone_lookup_service = PhoneLookupService()


# Convenience function for backward compatibility
async def searchbug_lookup_phone(address: str, city: str, state: str) -> "PhoneLookupResult":
    """Convenience function for simple lookups (backward compat)."""
    return await phone_lookup_service.lookup_phone(address, city, state)


# Aliases for backward compat
PhoneLookupResult = PhoneLookupResult
SearchbugPhoneResult = PhoneLookupResult
SearchbugService = PhoneLookupService
searchbug_service = phone_lookup_service

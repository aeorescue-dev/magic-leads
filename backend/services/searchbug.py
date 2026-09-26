"""Searchbug API Service — Modular, mockable, ready for production keys.

This module isolates all Searchbug API interactions. When API keys are not
configured, it runs in MOCK mode returning structured empty responses so the
rest of the system works without changes. When keys are added to env vars,
it seamlessly switches to live API calls.

Env vars required for live mode:
  SEARCHBUG_API_KEY — your Searchbug API key
  SEARCHBUG_BASE_URL — optional, defaults to "https://ws.searchbug.com"

Usage:
  from .services.searchbug import searchbug_service
  result = await searchbug_service.lookup_phone(address, city, state)
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
    """Normalize US phone number to E.164 format (+1XXXXXXXXXX).

    Handles various input formats:
    - (555) 123-4567
    - 555-123-4567
    - 555.123.4567
    - 5551234567
    - +15551234567
    - 15551234567

    Returns E.164 format: +1XXXXXXXXXX (11 digits after +)
    Returns original string if normalization fails.
    """
    if not phone:
        return phone

    # Extract only digits
    digits = re.sub(r"\D", "", str(phone))

    # Handle various US number formats
    # 10 digits (no country code): assume US, add +1
    # 11 digits starting with 1: US with country code
    # 11 digits not starting with 1: invalid, return as-is
    # Other lengths: return as-is

    if len(digits) == 10:
        # Standard US 10-digit: add country code
        return f"+1{digits}"
    elif len(digits) == 11 and digits.startswith("1"):
        # 11 digits with leading 1: already has country code
        return f"+{digits}"
    elif len(digits) == 11 and not digits.startswith("1"):
        # 11 digits but doesn't start with 1 - likely invalid, return original
        logger.warning(f"Phone number has 11 digits but doesn't start with 1: {digits}")
        return f"+{digits}"  # Still try with +
    elif digits.startswith("+"):
        # Already has + prefix
        return phone
    else:
        # Unknown format, try to add +1 if 10 digits, otherwise return as-is with +
        if len(digits) == 10:
            return f"+1{digits}"
        logger.warning(f"Unrecognized phone format, returning with + prefix: {digits}")
        return f"+{digits}"


def format_us_phone_display(phone_e164: str) -> str:
    """Format E.164 US phone for display: (XXX) XXX-XXXX.

    Args:
        phone_e164: Phone in E.164 format (+1XXXXXXXXXX)

    Returns:
        Formatted string: (XXX) XXX-XXXX
        Returns original if not valid E.164 US format.
    """
    if not phone_e164:
        return phone_e164

    # Extract digits after +1
    if phone_e164.startswith("+1") and len(phone_e164) == 12:
        digits = phone_e164[2:]
        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    elif phone_e164.startswith("1") and len(phone_e164) == 11:
        digits = phone_e164[1:]
        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"

    # Fallback: try to format any 10-digit number
    digits = re.sub(r"\D", "", phone_e164)
    if len(digits) == 10:
        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"

    return phone_e164


@dataclass
class SearchbugPhoneResult:
    """Structured result from Searchbug phone lookup."""
    success: bool
    phone: Optional[str] = None
    phone_type: Optional[str] = None  # "landline", "mobile", "voip"
    carrier: Optional[str] = None
    is_connected: Optional[bool] = None
    error: Optional[str] = None
    raw: Optional[dict] = None

    @property
    def is_usable(self) -> bool:
        return self.success and self.phone is not None


class SearchbugService:
    """Searchbug API client with mock fallback."""

    def __init__(self):
        self.api_key = getattr(settings, "SEARCHBUG_API_KEY", None) or os.getenv("SEARCHBUG_API_KEY")
        self.base_url = getattr(settings, "SEARCHBUG_BASE_URL", None) or os.getenv("SEARCHBUG_BASE_URL", "https://ws.searchbug.com")
        self.timeout = httpx.Timeout(15.0, connect=5.0)
        self._mock_mode = not bool(self.api_key)

        if self._mock_mode:
            logger.warning("Searchbug: MOCK MODE — SEARCHBUG_API_KEY not configured. Returning empty results.")
        else:
            logger.info("Searchbug: LIVE MODE enabled.")

    def _build_params(self, address: str, city: str, state: str) -> dict:
        """Build query parameters for Searchbug Phone Verification API."""
        return {
            "key": self.api_key,
            "addr": address,
            "city": city,
            "state": state,
            "format": "json",
        }

    async def lookup_phone(self, address: str, city: str, state: str) -> SearchbugPhoneResult:
        """Look up phone number for an address via Searchbug API.

        Args:
            address: Street address (e.g., "123 Main St")
            city: City name
            state: State abbreviation (e.g., "NY", "CA")

        Returns:
            SearchbugPhoneResult with phone info or error details.
        """
        if self._mock_mode:
            return SearchbugPhoneResult(
                success=False,
                error="MOCK MODE: SEARCHBUG_API_KEY not configured",
                raw={"mock": True}
            )

        url = f"{self.base_url}/phone.php"
        params = self._build_params(address, city, state)

        try:
            async with httpx.AsyncClient(timeout=self.timeout, verify=False) as client:
                response = await client.get(url, params=params)
                response.raise_for_status()
                data = response.json()

            # Parse Searchbug response format
            # Expected format varies by API version; handle common fields
            phone = data.get("phone") or data.get("Phone") or data.get("phone_number")
            phone_type = data.get("phone_type") or data.get("PhoneType") or data.get("type")
            carrier = data.get("carrier") or data.get("Carrier") or data.get("carrier_name")
            is_connected = data.get("is_connected") or data.get("IsConnected")
            error = data.get("error") or data.get("Error") or data.get("ErrorMessage")

            if error:
                logger.warning(f"Searchbug API error: {error}")
                return SearchbugPhoneResult(
                    success=False,
                    error=str(error),
                    raw=data
                )

            if not phone:
                logger.info(f"Searchbug: No phone found for {address}, {city}, {state}")
                return SearchbugPhoneResult(
                    success=False,
                    error="No phone number found",
                    raw=data
                )

            return SearchbugPhoneResult(
                success=True,
                phone=normalize_us_phone(str(phone).strip()),
                phone_type=str(phone_type).strip().lower() if phone_type else None,
                carrier=str(carrier).strip() if carrier else None,
                is_connected=bool(is_connected) if is_connected is not None else None,
                raw=data
            )

        except httpx.HTTPStatusError as e:
            logger.error(f"Searchbug HTTP error: {e.response.status_code} - {e.response.text}")
            return SearchbugPhoneResult(
                success=False,
                error=f"HTTP {e.response.status_code}",
                raw={"status": e.response.status_code}
            )
        except httpx.RequestError as e:
            logger.error(f"Searchbug request error: {e}")
            return SearchbugPhoneResult(
                success=False,
                error=f"Request failed: {e}",
                raw={"error": str(e)}
            )
        except Exception as e:
            logger.exception(f"Searchbug unexpected error: {e}")
            return SearchbugPhoneResult(
                success=False,
                error=f"Unexpected error: {e}",
                raw={"exception": str(e)}
            )

    async def lookup_phone_batch(self, addresses: list[tuple[str, str, str]]) -> list[SearchbugPhoneResult]:
        """Look up multiple phones concurrently (respects rate limits)."""
        semaphore = asyncio.Semaphore(5)  # Max 5 concurrent requests

        async def _lookup_with_sem(addr: str, city: str, state: str) -> SearchbugPhoneResult:
            async with semaphore:
                return await self.lookup_phone(addr, city, state)

        tasks = [_lookup_with_sem(addr, city, state) for addr, city, state in addresses]
        return await asyncio.gather(*tasks)


# Global singleton instance
searchbug_service = SearchbugService()


# Convenience function for backward compatibility
async def searchbug_lookup_phone(address: str, city: str, state: str) -> SearchbugPhoneResult:
    """Convenience function for simple lookups."""
    return await searchbug_service.lookup_phone(address, city, state)

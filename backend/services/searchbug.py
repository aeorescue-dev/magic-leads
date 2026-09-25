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

import os
import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

import httpx

from ..config import settings
from ..utils.logger import logger

logger = logging.getLogger(__name__)


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
            async with httpx.AsyncClient(timeout=self.timeout) as client:
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
                phone=str(phone).strip(),
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
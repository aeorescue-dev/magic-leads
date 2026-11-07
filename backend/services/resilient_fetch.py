"""HTTP resiliente para conectores de dados públicos.

Contrato unico: retries com backoff para 429/5xx/timeout, sem mascarar 4xx
permanentes, e registo em `ingestion_failures`. O chamador decide se grava
`ingestion_runs` com status success/partial/failed.
"""
from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

import httpx

from . import self_healing


@dataclass
class FetchResult:
    ok: bool
    status: str  # success | partial | failed
    data: Any = None
    http_status: Optional[int] = None
    error_class: str = ""
    error_detail: str = ""
    retryable: bool = False
    attempts: int = 0
    headers: Mapping[str, str] = field(default_factory=dict)


class ResilientFetcher:
    """GET/POST JSON e texto com retry exponencial e jitter."""

    RETRYABLE_STATUS = {429, 500, 502, 503, 504}

    def __init__(
        self,
        source: str,
        *,
        retries: int = 5,
        base_backoff: float = 1.0,
        max_backoff: float = 60.0,
        timeout: float = 60.0,
    ) -> None:
        self.source = source
        self.retries = max(1, int(retries))
        self.base_backoff = max(0.1, float(base_backoff))
        self.max_backoff = max(self.base_backoff, float(max_backoff))
        self.timeout = max(5.0, float(timeout))

    def _backoff(self, attempt: int, retry_after: Optional[str] = None) -> float:
        if retry_after:
            try:
                return min(self.max_backoff, max(0.0, float(retry_after)))
            except (TypeError, ValueError):
                pass
        return min(
            self.max_backoff,
            self.base_backoff * (2 ** min(attempt - 1, 8))
            + random.uniform(0, 0.5),
        )

    async def _request(
        self,
        method: str,
        url: str,
        *,
        params: Optional[Mapping[str, Any]] = None,
        json_body: Optional[Mapping[str, Any]] = None,
        text: bool = False,
    ) -> FetchResult:
        last_error = ""
        last_status: Optional[int] = None
        for attempt in range(1, self.retries + 1):
            try:
                async with httpx.AsyncClient(
                    timeout=self.timeout, follow_redirects=True
                ) as client:
                    response = await client.request(
                        method, url, params=params, json=json_body
                    )
                last_status = response.status_code
                if response.status_code in self.RETRYABLE_STATUS:
                    last_error = f"HTTP {response.status_code}"
                    if attempt < self.retries:
                        await asyncio.sleep(
                            self._backoff(attempt, response.headers.get("Retry-After"))
                        )
                        continue
                    self_healing.record_ingestion_failure(
                        self.source,
                        url=url,
                        http_status=response.status_code,
                        error_class="retryable_http",
                        retryable=True,
                    )
                    return FetchResult(
                        ok=False,
                        status="failed",
                        http_status=response.status_code,
                        error_class="retryable_http",
                        error_detail=last_error,
                        retryable=True,
                        attempts=attempt,
                    )
                if response.status_code >= 400:
                    detail = response.text[:1000]
                    self_healing.record_ingestion_failure(
                        self.source,
                        url=url,
                        http_status=response.status_code,
                        error_class="permanent_http",
                        retryable=False,
                    )
                    return FetchResult(
                        ok=False,
                        status="failed",
                        http_status=response.status_code,
                        error_class="permanent_http",
                        error_detail=detail,
                        retryable=False,
                        attempts=attempt,
                    )
                data = response.text if text else response.json()
                return FetchResult(
                    ok=True,
                    status="success",
                    data=data,
                    http_status=response.status_code,
                    attempts=attempt,
                    headers=dict(response.headers),
                )
            except (httpx.TimeoutException, httpx.HTTPError) as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                if attempt < self.retries:
                    await asyncio.sleep(self._backoff(attempt))
                    continue
                self_healing.record_ingestion_failure(
                    self.source,
                    url=url,
                    http_status=last_status,
                    error_class=type(exc).__name__,
                    retryable=True,
                )
                return FetchResult(
                    ok=False,
                    status="failed",
                    http_status=last_status,
                    error_class=type(exc).__name__,
                    error_detail=last_error,
                    retryable=True,
                    attempts=attempt,
                )
        return FetchResult(
            ok=False,
            status="failed",
            http_status=last_status,
            error_class="unknown",
            error_detail=last_error,
            retryable=True,
            attempts=self.retries,
        )

    async def get_json(
        self, url: str, *, params: Optional[Mapping[str, Any]] = None
    ) -> FetchResult:
        return await self._request("GET", url, params=params)

    async def get_text(
        self, url: str, *, params: Optional[Mapping[str, Any]] = None
    ) -> FetchResult:
        return await self._request("GET", url, params=params, text=True)

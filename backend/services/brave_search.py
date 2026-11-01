"""Domain discovery via Brave Search (fallback autonomo ao OSM/Overpass).

O contentor do Railway nao consegue contactar o Overpass e a heuristica de
slugs so' encontra sites obvios. O Brave Web Search da' os primeiros resultados
para "nome + cidade + contractor"; cada candidato e' **verificado** com o mesmo
gate do resto do sistema (DNS/HTTP + nome distintivo + cidade), para nunca
atribuir um diretorio a uma empresa.

Custo: uma query por entidade, com cache de 30 dias e orcamento diario em
`system_kv`. Sem chave, o modulo e' inerte (devolve None).
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

from ..config import settings
from ..utils.logger import logger
from .company_discovery import (
    BLOCKED_DOMAINS,
    corroborate,
    default_fetch,
    extract_text,
    identity_ok,
    is_blocked_domain,
    is_corroborated,
    registrable_domain,
)
from .contractor_entities import normalize_company_name
from .db import get_connection

BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"
CACHE_TTL_DAYS = 30
MAX_CANDIDATES = 4
CITY_QUERY = {
    "NYC": "New York City",
    "NEW YORK": "New York City",
    "CHICAGO": "Chicago",
    "BOSTON": "Boston",
    "DALLAS": "Dallas",
}
DIRECTORY_HOSTS = BLOCKED_DOMAINS | {
    "thumbtack.com", "angi.com", "buildzoom.com", "porch.com", "houzz.com",
}


def api_key() -> str:
    return (getattr(settings, "BRAVE_SEARCH_API_KEY", "") or "").strip()


def daily_limit() -> int:
    try:
        return max(0, min(int(getattr(settings, "BRAVE_DAILY_QUERIES", 450)), 5000))
    except (TypeError, ValueError):
        return 450


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def consume_budget() -> bool:
    """Reserva uma query do dia. False quando o orcamento acabou."""
    limit = daily_limit()
    if limit <= 0:
        return False
    key = f"brave_queries:{_today()}"
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT value FROM system_kv WHERE key=?", (key,)
        ).fetchone()
        used = int(row["value"]) if row and str(row["value"]).isdigit() else 0
        if used >= limit:
            conn.rollback()
            return False
        conn.execute(
            "INSERT INTO system_kv (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=CURRENT_TIMESTAMP",
            (key, str(used + 1)),
        )
        conn.commit()
        return True
    except Exception:  # noqa: BLE001
        return False
    finally:
        conn.close()


def budget_left() -> int:
    limit = daily_limit()
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT value FROM system_kv WHERE key=?", (f"brave_queries:{_today()}",)
        ).fetchone()
        used = int(row["value"]) if row and str(row["value"]).isdigit() else 0
        return max(0, limit - used)
    finally:
        conn.close()


def _cache_key(legal_name: str, city: str) -> tuple[str, str]:
    return normalize_company_name(legal_name), (city or "").strip().upper()


def cache_get(legal_name: str, city: str) -> Optional[dict]:
    key = _cache_key(legal_name, city)
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT domain, confidence, source, checked_at FROM domain_search_cache "
            "WHERE normalized_name=? AND city=?",
            key,
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    try:
        checked = datetime.strptime(
            str(row["checked_at"]), "%Y-%m-%d %H:%M:%S"
        ).replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None
    if (datetime.now(timezone.utc) - checked).days > CACHE_TTL_DAYS:
        return None
    if not row["domain"]:
        return {"domain": None, "confidence": 0.0, "source": "brave_none", "snippet": ""}
    return {
        "domain": row["domain"],
        "confidence": float(row["confidence"] or 0.0),
        "source": row["source"] or "brave",
        "snippet": "",
    }


def cache_set(legal_name: str, city: str, domain: Optional[str], confidence: float) -> None:
    key = _cache_key(legal_name, city)
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO domain_search_cache "
            "(normalized_name, city, domain, confidence, source, checked_at) "
            "VALUES (?, ?, ?, ?, 'brave', CURRENT_TIMESTAMP) "
            "ON CONFLICT(normalized_name, city) DO UPDATE SET "
            "domain=excluded.domain, confidence=excluded.confidence, "
            "checked_at=CURRENT_TIMESTAMP",
            (key[0], key[1], domain, float(confidence)),
        )
        conn.commit()
    finally:
        conn.close()


def candidate_domains(results: list[dict], limit: int = MAX_CANDIDATES) -> list[str]:
    """Dominios plausiveis dos resultados, sem diretorios nem redes sociais."""
    out: list[str] = []
    for item in results or []:
        url = item.get("url") or ""
        host = registrable_domain(urlparse(url).netloc)
        if not host or is_blocked_domain(host) or host in DIRECTORY_HOSTS:
            continue
        if host not in out:
            out.append(host)
        if len(out) >= limit:
            break
    return out


def verify_candidate(
    legal_name: str, city: str, domain: str, fetch=default_fetch
) -> Optional[dict]:
    """Confirma que `domain` e' mesmo o site da empresa (nome distintivo + cidade)."""
    for scheme in ("https", "http"):
        page = fetch(f"{scheme}://{domain}/", 6.0)
        if not page or page.get("status", 0) >= 400:
            continue
        title, text = extract_text(page.get("html") or b"")
        evidence = corroborate(
            {"owner_name": legal_name, "city": city}, title, text
        )
        if is_corroborated(evidence) and identity_ok(
            {"owner_name": legal_name}, domain, title
        ):
            return {
                "domain": domain,
                "confidence": 0.7,
                "source": "brave",
                "snippet": text[:1200],
                "evidence": evidence,
            }
        return None
    return None


async def find_domain(legal_name: str, city: str) -> Optional[dict]:
    """Dominio corroborado via Brave (cache -> query -> verificacao)."""
    if not legal_name:
        return None
    cached = cache_get(legal_name, city)
    if cached is not None:
        return cached if cached.get("domain") else None

    if not api_key():
        return None
    if not consume_budget():
        logger.warning("[BRAVE] orcamento diario esgotado (%s queries)", daily_limit())
        return None

    import httpx

    city_name = CITY_QUERY.get((city or "").strip().upper(), city or "")
    query = f'"{legal_name}" {city_name} contractor'.strip()
    try:
        started = time.monotonic()
        async with httpx.AsyncClient(timeout=12.0) as client:
            resp = await client.get(
                BRAVE_URL,
                params={"q": query, "count": 10, "country": "us", "search_lang": "en"},
                headers={
                    "Accept": "application/json",
                    "X-Subscription-Token": api_key(),
                },
            )
        if resp.status_code != 200:
            logger.warning("[BRAVE] HTTP %s para %r", resp.status_code, legal_name)
            return None
        results = ((resp.json() or {}).get("web") or {}).get("results") or []
        candidates = candidate_domains(results)
        for domain in candidates:
            found = verify_candidate(legal_name, city, domain)
            if found:
                cache_set(legal_name, city, domain, found["confidence"])
                logger.info(
                    "[BRAVE] %r -> %s (%.1fs)", legal_name, domain,
                    time.monotonic() - started,
                )
                return found
        cache_set(legal_name, city, None, 0.0)
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("[BRAVE] falhou para %r: %s", legal_name, exc)
        return None

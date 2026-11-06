"""Enriquecimento gratuito de telefones a partir de websites públicos.

Não usa APIs pagas. O crawl é limitado a homepage/contact/about, com um
User-Agent identificável. O telefone encontrado é gravado em
`contractor_entities.phone` e a proveniência em `contractor_entity_sources`.
"""
from __future__ import annotations

import asyncio
import re
from typing import Iterable, Optional

import httpx

from ..utils.logger import logger

_PHONE_RE = re.compile(
    r"(?:\+?1[\s\-\.]?)?\(?([2-9]\d{2})\)?[\s\-\.]?(\d{3})[\s\-\.]?(\d{4})\b"
)
_TEL_RE = re.compile(r"tel:\s*([+0-9().\-\s]{7,})", re.IGNORECASE)
_CANDIDATE_PATHS = ("", "/contact", "/contact-us", "/about", "/about-us")
_UA = "MagicLeadsBot/1.0 (+https://magicleads.app)"


def extract_phone_numbers(text: object) -> list[str]:
    """Extrai telefones US plausíveis de HTML/texto, sem duplicados."""
    raw = str(text or "")
    found: list[str] = []
    seen: set[str] = set()
    for match in _TEL_RE.finditer(raw):
        digits = re.sub(r"\D", "", match.group(1))
        if len(digits) == 11 and digits.startswith("1"):
            digits = digits[1:]
        if len(digits) == 10 and digits[0] in "23456789" and digits not in seen:
            seen.add(digits)
            found.append(f"+1{digits}")
    for match in _PHONE_RE.finditer(raw):
        digits = "".join(match.groups())
        if len(digits) == 10 and digits not in seen:
            seen.add(digits)
            found.append(f"+1{digits}")
    return found


def _clean_snippet(text: str, limit: int = 600) -> str:
    text = re.sub(r"<script.*?</script>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = " ".join(text.split())
    return text[:limit]


async def crawl_domain_phone(
    domain: str, timeout: float = 8.0
) -> tuple[Optional[str], str]:
    """Devolve (telefone, snippet) do primeiro URL com telefone."""
    host = str(domain or "").strip().lower()
    host = re.sub(r"^https?://", "", host).strip("/")
    if not host:
        return None, ""
    headers = {"User-Agent": _UA}
    async with httpx.AsyncClient(
        headers=headers, timeout=timeout, follow_redirects=True
    ) as client:
        for path in _CANDIDATE_PATHS:
            url = f"https://{host}{path}"
            try:
                response = await client.get(url)
            except Exception:
                continue
            if response.status_code != 200:
                continue
            text = response.text or ""
            phones = extract_phone_numbers(text)
            if phones:
                return phones[0], _clean_snippet(text)
    return None, ""


async def enrich_contractor_phones(
    limit: int = 200,
    states: Iterable[str] = ("IL", "TX", "MA"),
    concurrency: int = 6,
) -> dict:
    """Crawla websites de entidades sem telefone e grava os que encontrar."""
    from .db import get_connection

    state_list = tuple(str(s).upper() for s in states if str(s).strip())
    if not state_list:
        return {"checked": 0, "found": 0, "updated": 0}
    placeholders = ",".join("?" for _ in state_list)
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, legal_name, domain FROM contractor_entities "
            f"WHERE state IN ({placeholders}) "
            "AND COALESCE(TRIM(phone),'')='' "
            "AND COALESCE(TRIM(domain),'')<>'' "
            "ORDER BY id DESC LIMIT ?",
            (*state_list, max(1, min(2000, int(limit)))),
        ).fetchall()
    finally:
        conn.close()

    semaphore = asyncio.Semaphore(max(1, int(concurrency)))

    async def one(row) -> tuple[int, str, Optional[str], str]:
        async with semaphore:
            phone, snippet = await crawl_domain_phone(row["domain"])
            return int(row["id"]), str(row["domain"]), phone, snippet

    results = await asyncio.gather(*(one(row) for row in rows))
    updated = 0
    conn = get_connection()
    try:
        for entity_id, domain, phone, snippet in results:
            if not phone:
                continue
            conn.execute(
                "UPDATE contractor_entities SET phone=?, site_snippet=COALESCE(NULLIF(site_snippet,''), ?), "
                "updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (phone, snippet, entity_id),
            )
            conn.execute(
                "INSERT OR IGNORE INTO contractor_entity_sources "
                "(entity_id, source, external_id, role) VALUES (?, 'website_crawl', ?, 'contractor')",
                (entity_id, domain),
            )
            updated += 1
        conn.commit()
    finally:
        conn.close()
    logger.info(
        "[PHONE-ENRICH] checked=%s found=%s updated=%s states=%s",
        len(results),
        sum(1 for _, _, phone, _ in results if phone),
        updated,
        state_list,
    )
    return {
        "checked": len(results),
        "found": sum(1 for _, _, phone, _ in results if phone),
        "updated": updated,
        "states": state_list,
    }

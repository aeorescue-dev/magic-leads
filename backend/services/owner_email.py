"""OSINT do dono/CEO no proprio site da empresa (custo $0).

Percorre paginas de equipa/sobre, extrai nomes junto a cargos de decisao,
gera os padroes usuais (first@, first.last@, f.last@, ...) e verifica cada
candidato com RCPT SMTP real no worker VPS.

Regra de ouro: catch-all nunca e' aceite (a prova nao existe). Sem prova, a
entidade segue para quarentena como hoje — nada muda no gate de envio.
"""
from __future__ import annotations

import random
import re
import string
from typing import Callable, Optional

from ..utils.logger import logger
from .company_discovery import (
    default_fetch,
    default_prober,
    extract_text,
)

PATHS = ("/about", "/about-us", "/team", "/our-team", "/leadership", "/contact", "/")
TITLE = (
    r"(?:Owner|Co-?Owner|President|Founder|Co-?Founder|CEO|"
    r"Chief Executive Officer|Managing Partner|Principal|Proprietor|"
    r"General Manager)"
)
NAME = r"([A-Z][a-z]{1,18}(?:\s+[A-Z][a-z'\-]{1,22}){1,2})"
# "John Smith, Owner" / "John Smith - President" / "Owner: John Smith"
_TITLE_RE = re.compile(rf"\b{TITLE}\b", re.I)
# Nome imediatamente ANTES do cargo, terminando no separador ("Acme John
# Smith, Owner" -> "John Smith"): no maximo 2 palavras para nao arrastar o
# nome do site que vem antes.
_NAME_TAIL = re.compile(
    r"([A-Z][a-z'\-]{1,20}(?:\s+(?:[A-Z][a-z'\-]{1,20}|[A-Z]))?)\s*[,\-|:]\s*$"
)
_NAME_HEAD = re.compile(
    r"^\s*[:\-|]?\s*([A-Z][a-z'\-]{1,20}"
    r"(?:\s+(?:[A-Z][a-z'\-]{1,20}|[A-Z])){1,2})"
)
_STOP = {
    "our", "the", "your", "meet", "about", "contact", "team", "owner",
    "president", "founder", "chief", "executive", "officer", "general",
    "manager", "managing", "partner", "principal", "proprietor", "company",
    "services", "service", "construction", "contracting", "roofing",
    "plumbing", "electric", "electrical", "heating", "cooling", "us", "we",
}
_COMPANYISH = re.compile(
    r"\b(LLC|INC|CORP|CO|COMPANY|CONSTRUCTION|CONTRACTING|SERVICES|GROUP)\b", re.I
)


def _phrase(value: str) -> str:
    return re.sub(r"[^a-z]", "", value.lower())


def extract_owner_names(html) -> list[tuple[str, str]]:
    """Nomes (first, last) junto a um cargo de decisao, sem duplicados."""
    raw = html if isinstance(html, bytes) else str(html or "").encode("utf-8", "ignore")
    title, text = extract_text(raw)
    blob = text or title
    found: list[tuple[str, str]] = []

    def _take(name: str) -> None:
        words = " ".join(name.split()).split()
        while words and words[0].lower() in _STOP:
            words.pop(0)
        while words and words[-1].lower() in _STOP:
            words.pop()
        if len(words) < 2:
            return
        first, last = words[0], words[-1]
        if _COMPANYISH.search(first) or _COMPANYISH.search(last):
            return
        if len(first) < 2 or len(last) < 2:
            return
        pair = (_phrase(first), _phrase(last))
        if pair not in found:
            found.append(pair)

    for match in _TITLE_RE.finditer(blob):
        before = blob[max(0, match.start() - 80):match.start()]
        tail = _NAME_TAIL.search(before)
        if tail:
            _take(tail.group(1))
        after = blob[match.end():match.end() + 80]
        head = _NAME_HEAD.search(after)
        if head:
            _take(head.group(1))
    return found


def owner_patterns(domain: str, first: str, last: str) -> list[str]:
    """Padroes mais comuns em empresas pequenas dos EUA (ordem = prioridade)."""
    bases = [
        f"{first}@{domain}",
        f"{first}.{last}@{domain}",
        f"{first[0]}.{last}@{domain}",
        f"{first[0]}{last}@{domain}",
        f"{first}{last[0]}@{domain}",
        f"{last}@{domain}",
        f"{first}_{last}@{domain}",
    ]
    seen: set[str] = set()
    out: list[str] = []
    for item in bases:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _is_catch_all(prober, domain: str) -> bool:
    local = "zz" + "".join(random.choices(string.ascii_lowercase + string.digits, k=12))
    probe = prober.probe(domain, [f"{local}@{domain}"])
    return probe.get("error") is None and (
        (probe.get("codes") or {}).get(f"{local}@{domain}") == "accepted"
    )


def find_owner_email(
    domain: str,
    company_name: str,
    fetch: Callable[..., Optional[dict]] = default_fetch,
    prober=None,
) -> Optional[str]:
    """Devolve um e-mail nominal comprovado por RCPT, ou None."""
    if not domain:
        return None
    prober = prober or default_prober()
    if _is_catch_all(prober, domain):
        return None
    names: list[tuple[str, str]] = []
    for path in PATHS:
        page = fetch(f"https://{domain}{path}", 5.0)
        if not page or page.get("status", 0) >= 400:
            continue
        try:
            names = extract_owner_names(page.get("html") or b"")
        except Exception:  # noqa: BLE001
            names = []
        if names:
            break
    if not names:
        return None
    first, last = names[0]
    candidates = owner_patterns(domain, first, last)
    result = prober.probe(domain, candidates)
    if result.get("error") is not None:
        return None
    for candidate in candidates:
        if (result.get("codes") or {}).get(candidate) == "accepted":
            logger.info("[OWNER-EMAIL] %s -> %s", company_name or domain, candidate)
            return candidate
    return None

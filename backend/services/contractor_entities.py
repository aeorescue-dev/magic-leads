"""Núcleo do grafo de empreiteiros (Fase 2).

Normaliza nomes empresariais, calcula a chave de entidade e prepara registos
para `contractor_entities`. Não faz I/O: é testável e reutilizável pelos
extratores de NYC/Chicago/Dallas/Boston e pelo resolver de websites.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Optional

LEGAL_SUFFIXES = (
    "L L C", "LLC", "L.L.C.", "L.L.C", "PLLC", "P.L.L.C.",
    "INC", "INCORPORATED", "CORP", "CORPORATION", "CO", "COMPANY",
    "LP", "L P", "LLP", "L L P", "LTD", "LIMITED", "PC", "P C", "PA", "P A",
)

_ROLE_ALIASES = {
    "applicant": "applicant",
    "contractor": "contractor",
    "general contractor": "contractor",
    "owner": "owner",
    "expediter": "expediter",
    "filing representative": "expediter",
}


def _strip_accents(value: str) -> str:
    return "".join(
        ch
        for ch in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(ch)
    )


def normalize_company_name(value: Optional[str]) -> str:
    """Maiúsculas, sem acentos/pontuação, sem sufixos legais e espaços únicos."""
    text = _strip_accents(str(value or "")).upper()
    text = text.replace("&", " AND ")
    text = re.sub(r"[^A-Z0-9 ]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    changed = True
    while changed and text:
        changed = False
        for suffix in sorted(LEGAL_SUFFIXES, key=len, reverse=True):
            if text == suffix:
                text = ""
                changed = True
                break
            if text.endswith(" " + suffix):
                text = text[: -(len(suffix) + 1)].strip()
                changed = True
                break
    return text


def entity_key(legal_name: str, state: Optional[str]) -> str:
    """Chave estável por empresa+estado (independente de sufixos legais)."""
    norm = normalize_company_name(legal_name)
    st = (state or "").strip().upper()
    return hashlib.sha256(f"{norm}|{st}".encode()).hexdigest()


def normalize_role(role: Optional[str]) -> Optional[str]:
    if not role:
        return None
    key = re.sub(r"\s+", " ", str(role).strip().lower())
    return _ROLE_ALIASES.get(key, key[:40] or None)


def is_usable_company_name(value: Optional[str]) -> bool:
    """Rejeita placeholders e nomes genéricos que não são empresas."""
    norm = normalize_company_name(value)
    if len(norm) < 3:
        return False
    bad = {
        "UNAVAILABLE OWNER", "UNKNOWN", "OWNER", "N A", "NA", "NONE",
        "TAXPAYER OF", "SAME AS OWNER", "SELF", "PRIVATE",
    }
    return norm not in bad

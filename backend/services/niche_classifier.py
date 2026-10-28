"""Classificador automatico de nicho de uma empresa B2B.

Porque existe
-------------
O pipeline antigo etiquetava o lead com o nicho do LOTE (`--nicho plumbing`
carimbava todos os contactos como plumbing). Resultado real: um cliente HVAC
recebeu copy de General Contractors.

Aqui a decisao e' por EMPRESA e e' auditavel: cada sinal soma pontos, e o
resultado so' e' `confirmed` quando ha evidencia clara. Caso contrario o lead
fica `ambiguous`/`unknown` e o motor de envio recusa-o (nunca se adivinha).

Sinais (pesos)
--------------
  dominio (SLD)          3.0   ex.: deljoheating.com -> hvac
  nome da empresa        2.0   ex.: "Black Diamond Plumbing" -> plumbing
  titulo/H1 do site      2.0   ex.: "Chicago HVAC & Plumbing Company"
  categoria do CSV       1.0   (fraco: muitas vezes e' o label do lote)

Decisao
-------
  top >= 3.0 e margem >= 1.5        -> confirmed
  top >= 3.0 e margem <  1.5        -> ambiguous  (evidencia conflituante)
  top <  3.0                        -> unknown    (sem evidencia)

Nunca levanta excepcao: devolve sempre um dict com `status`.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from .lead_filter import strip_accents

# Pesos dos sinais.
W_DOMAIN = 3.0
W_NAME = 2.0
W_TEXT = 3.0
W_HINT = 1.0

CONFIRM_MIN_SCORE = 3.0
CONFIRM_MIN_MARGIN = 1.5

# Padroes por nicho. Ordem importa dentro do nicho (especifico -> generico).
NICHE_PATTERNS: dict[str, tuple[str, ...]] = {
    "plumbing": (
        r"plumb\w*", r"rooter", r"\bdrain\w*", r"\bsewer\w*", r"water\s*heater",
        r"backflow", r"pipe\w*", r"leak\s*detect\w*",
    ),
    "hvac": (
        r"\bhvac\b", r"\bheat(ing)?\b", r"\bcool(ing)?\b", r"air\s*condition\w*",
        r"furnace", r"boiler", r"ductwork", r"refrigerat\w*", r"\bmechanical\b",
    ),
    "roofing": (
        r"roof\w*", r"shingle", r"gutter", r"waterproof\w*", r"siding",
    ),
    "electrical": (
        r"electric\w*", r"electrician", r"\bwiring\b", r"panel\s*upgrade",
        r"generator", r"\blighting\b", r"voltage",
    ),
    "remodeling": (
        r"remodel\w*", r"renovat\w*", r"\bkitchen", r"\bbath\w*", r"carpentry",
        r"drywall", r"flooring", r"\bpainting\b", r"interior",
    ),
    "restoration": (
        r"restor\w*", r"water\s*damage", r"fire\s*damage", r"mold",
        r"remediat\w*", r"\bflood\w*", r"cleanup", r"clean\s*up",
    ),
    "landscaping": (
        r"landscap\w*", r"lawn", r"grounds\w*", r"tree\s*service",
        r"irrigation", r"\bsnow\s*remov\w*", r"hardscap\w*",
    ),
    "general_contractors": (
        r"general\s*contract\w*", r"construction", r"builders?", r"\bbuild\b",
        r"contracting", r"contractors?",
    ),
}

_COMPILED: dict[str, list[re.Pattern[str]]] = {
    niche: [re.compile(p, re.I) for p in pats]
    for niche, pats in NICHE_PATTERNS.items()
}

# Categorias do painel/CSV -> nicho (para o sinal fraco `hint`).
CATEGORY_HINT: dict[str, str] = {
    "general contractors": "general_contractors",
    "roofing": "roofing",
    "remodeling": "remodeling",
    "remodeling & renovation": "remodeling",
    "plumbing": "plumbing",
    "electrical": "electrical",
    "heating & hvac": "hvac",
    "hvac": "hvac",
    "restoration": "restoration",
    "restoration & cleanup": "restoration",
    "landscaping": "landscaping",
    "landscaping & grounds": "landscaping",
}


def _tokens(text: str) -> str:
    """Normaliza para comparacao: minusculas, sem acentos, separadores unicos."""
    clean = strip_accents(text or "").lower()
    clean = re.sub(r"[^a-z0-9]+", " ", clean)
    return f" {clean.strip()} "


def _domain_sld(domain: str) -> str:
    d = (domain or "").strip().lower()
    d = re.sub(r"^www\.", "", d)
    parts = d.split(".")
    return parts[0] if parts else ""


def _score_text(blob: str) -> dict[str, float]:
    """Soma padroes distintos que aparecem em `blob`."""
    norm = _tokens(blob)
    scores: dict[str, float] = {}
    for niche, pats in _COMPILED.items():
        hits = 0
        for pat in pats:
            # os padroes foram escritos para o texto cru; aplicamos ao normalizado
            if pat.search(norm.strip()) or pat.search(blob or ""):
                hits += 1
        if hits:
            scores[niche] = float(hits)
    return scores


def classify(
    company: str,
    domain: str = "",
    text: str = "",
    hint: str = "",
) -> dict[str, Any]:
    """Classifica o nicho de uma empresa. Nunca levanta excepcao.

    Devolve {niche, status, score, margin, evidence, alternatives}.
    status: confirmed | ambiguous | unknown
    """
    evidence: list[dict[str, Any]] = []
    scores: dict[str, float] = {}

    def add(niche: str, weight: float, signal: str, detail: str) -> None:
        scores[niche] = scores.get(niche, 0.0) + weight
        evidence.append({"signal": signal, "niche": niche, "weight": weight,
                         "detail": detail[:120]})

    sld = _domain_sld(domain)
    if sld:
        for niche, hits in _score_text(sld).items():
            add(niche, W_DOMAIN * min(hits, 2), "domain", sld)

    if company:
        for niche, hits in _score_text(company).items():
            add(niche, W_NAME * min(hits, 2), "name", company)

    if text:
        for niche, hits in _score_text(text).items():
            add(niche, W_TEXT * min(hits, 2), "site_text", text[:80])

    hint_key = (hint or "").strip().lower()
    hinted = CATEGORY_HINT.get(hint_key)
    if hinted:
        add(hinted, W_HINT, "csv_hint", hint)

    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    if not ranked:
        return {"niche": None, "status": "unknown", "score": 0.0, "margin": 0.0,
                "evidence": [], "alternatives": []}

    top_niche, top_score = ranked[0]
    second_score = ranked[1][1] if len(ranked) > 1 else 0.0
    margin = top_score - second_score

    if top_score >= CONFIRM_MIN_SCORE and margin >= CONFIRM_MIN_MARGIN:
        status = "confirmed"
    elif top_score >= CONFIRM_MIN_SCORE:
        status = "ambiguous"
    else:
        status = "unknown"

    return {
        "niche": top_niche if status == "confirmed" else None,
        "status": status,
        "score": round(top_score, 2),
        "margin": round(margin, 2),
        "evidence": evidence,
        "alternatives": [
            {"niche": n, "score": round(s, 2)} for n, s in ranked[1:4]
        ],
    }


def is_sendable(niche_key: Optional[str], niche_status: Optional[str]) -> bool:
    """Gate unico usado pelo motor de envio."""
    from .outbound_templates import NICHES

    return bool(niche_key) and niche_status == "confirmed" and niche_key in NICHES

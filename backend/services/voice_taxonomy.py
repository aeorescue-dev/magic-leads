"""Taxonomia de voz: categorias, trades e sinónimos de mercado.

Módulo puro, sem BD e sem efeitos secundários. A fonte de verdade das 16
categorias continua em `alert_categories.py`; aqui vive o vocabulário que o
motor de voz usa para ligar uma empresa ao serviço que ela realmente presta.

Regras:
- Nenhum token genérico ("construction", "contracting", "services") cria um
  trade. É exatamente esse comportamento que enchia a base de
  `general_contractor`.
- Sinais fortes (licença, nicho explícito) valem mais do que o nome.
- Uma empresa pode ter vários trades; a chamada continua a ser única por
  `company_id` por causa da exclusão global de 7 dias.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable, Optional

# Categoria canónica -> trades de voz. `None` = ainda sem trade (Permit_Rejected).
CATEGORY_TO_TRADES: dict[str, tuple[str, ...]] = {
    "Roof": ("roofing",),
    "Structure": ("remodeling", "general_contractor"),
    "Plumbing": ("plumbing",),
    "Grass": ("landscaping",),
    "Paint": ("painting",),
    "Permit_Rejected": (),
    "Heating": ("hvac",),
    "Electrical": ("electrical",),
    "Elevator": ("elevator",),
    "Gas": ("hvac",),
    "Rodent": ("pest_control",),
    "Mold": ("remediation",),
    "Lead": ("painting",),
    "Unsanitary": ("cleaning",),
    "Door_Window": ("windows",),
    "Debris": ("debris_removal",),
}

TRADE_TO_CATEGORIES: dict[str, tuple[str, ...]] = {}
for _category, _trades in CATEGORY_TO_TRADES.items():
    for _trade in _trades:
        TRADE_TO_CATEGORIES.setdefault(_trade, ())
        TRADE_TO_CATEGORIES[_trade] += (_category,)

# Categorias com página/inventário próprio. `general_contractor` e `signage`
# ficam de fora: não têm showcase exato.
EXACT_TRADES: tuple[str, ...] = (
    "roofing",
    "remodeling",
    "plumbing",
    "landscaping",
    "painting",
    "hvac",
    "electrical",
    "elevator",
    "remediation",
    "cleaning",
    "windows",
    "debris_removal",
    "pest_control",
)

# Bundle honesto para empresas multi-trade (GC/handyman). Só entram trades com
# inventário exato; a soma é sempre de contagens reais.
HOME_SERVICES_BUNDLE: tuple[str, ...] = EXACT_TRADES

# Aliases observados no mercado e nos datasets públicos.
TRADE_ALIASES: dict[str, str] = {
    # plumbing
    "plumber": "plumbing",
    "plumbers": "plumbing",
    "plumbing": "plumbing",
    "plumbing and heating": "plumbing",
    "plumbing & heating": "plumbing",
    "sewer": "plumbing",
    "sewer and drain": "plumbing",
    "drain": "plumbing",
    "rooter": "plumbing",
    # electrical
    "electrician": "electrical",
    "electricians": "electrical",
    "electrical": "electrical",
    "electrical contractor": "electrical",
    "electrical contracting": "electrical",
    "electric": "electrical",
    "lighting": "electrical",
    # hvac / heating
    "hvac": "hvac",
    "hvac r": "hvac",
    "heating": "hvac",
    "heating and cooling": "hvac",
    "heating & cooling": "hvac",
    "heating and air": "hvac",
    "air conditioning": "hvac",
    "air condition": "hvac",
    "mechanical": "hvac",
    "boiler": "hvac",
    "oil burner": "hvac",
    # roofing
    "roofer": "roofing",
    "roofers": "roofing",
    "roofing": "roofing",
    "roofing and waterproofing": "roofing",
    "waterproofing": "roofing",
    "shingle": "roofing",
    # painting
    "painter": "painting",
    "painters": "painting",
    "painting": "painting",
    "painting and plastering": "painting",
    "plastering": "painting",
    "plaster": "painting",
    # windows / doors
    "window": "windows",
    "windows": "windows",
    "window and door": "windows",
    "window & door": "windows",
    "doors and windows": "windows",
    "glazing": "windows",
    "glass": "windows",
    "storefront": "windows",
    # landscaping
    "landscaping": "landscaping",
    "landscaping and grounds": "landscaping",
    "lawn": "landscaping",
    "garden": "landscaping",
    "tree service": "landscaping",
    "grounds": "landscaping",
    # cleaning
    "cleaning": "cleaning",
    "janitorial": "cleaning",
    "janitor": "cleaning",
    "maid": "cleaning",
    "commercial cleaning": "cleaning",
    # pest
    "pest": "pest_control",
    "pest control": "pest_control",
    "exterminating": "pest_control",
    "exterminator": "pest_control",
    "rodent": "pest_control",
    # debris
    "debris": "debris_removal",
    "debris removal": "debris_removal",
    "junk removal": "debris_removal",
    "rubbish": "debris_removal",
    "carting": "debris_removal",
    "waste removal": "debris_removal",
    # elevator
    "elevator": "elevator",
    "elevators": "elevator",
    "lift": "elevator",
    # remediation
    "restoration": "remediation",
    "restoration and cleanup": "remediation",
    "water damage": "remediation",
    "mold": "remediation",
    "mold remediation": "remediation",
    "remediation": "remediation",
    # structure
    "remodeling": "remodeling",
    "renovation": "remodeling",
    "general contractor": "general_contractor",
    "general contractors": "general_contractor",
    "home improvement": "general_contractor",
    "signage": "signage",
    "sign hanger": "signage",
}

# `license_type` do DOB -> trade. Só entram tipos que identificam o ofício.
LICENSE_TYPE_TO_TRADE: dict[str, str] = {
    "MASTER PLUMBER": "plumbing",
    "ELECTRICAL FIRM": "electrical",
    "ELECTRICAL CONTRACTOR": "electrical",
    "ELEVATOR AGENCY / INSPECTOR": "elevator",
    "OIL BURNER INSTALLER": "hvac",
    "SIGN HANGER": "signage",
}

# Tokens de nome. O peso é a confiança base; dois tokens do mesmo trade podem
# subir a confiança, mas nunca acima de 0.95.
NAME_RULES: dict[str, tuple[tuple[str, float], ...]] = {
    "plumbing": (
        ("plumb", 0.90),
        ("sewer", 0.86),
        ("drain", 0.82),
        ("rooter", 0.82),
    ),
    "electrical": (
        ("electric", 0.90),
        ("electrical", 0.90),
        ("lighting", 0.78),
    ),
    "hvac": (
        ("heating", 0.90),
        ("hvac", 0.92),
        ("air condition", 0.90),
        ("mechanical", 0.82),
        ("boiler", 0.86),
        ("oil burner", 0.88),
    ),
    "roofing": (
        ("roof", 0.90),
        ("shingle", 0.84),
        ("waterproof", 0.78),
    ),
    "painting": (
        ("paint", 0.90),
        ("plaster", 0.84),
    ),
    "windows": (
        ("window", 0.86),
        ("door", 0.78),
        ("glass", 0.82),
        ("glaz", 0.86),
        ("storefront", 0.84),
    ),
    "landscaping": (
        ("landscap", 0.90),
        ("lawn", 0.86),
        ("garden", 0.82),
        ("tree service", 0.86),
        ("grounds", 0.78),
    ),
    "cleaning": (
        ("clean", 0.86),
        ("janitor", 0.90),
        ("maid", 0.86),
    ),
    "pest_control": (
        ("pest", 0.90),
        ("exterminat", 0.92),
        ("rodent", 0.84),
    ),
    "debris_removal": (
        ("debris", 0.90),
        ("junk", 0.86),
        ("rubbish", 0.88),
        ("carting", 0.84),
        ("waste removal", 0.86),
    ),
    "elevator": (
        ("elevator", 0.92),
        ("lift", 0.72),  # stairlifts e afins não são elevadores de serviço
    ),
    "remediation": (
        ("restoration", 0.82),
        ("mold", 0.86),
        ("water damage", 0.86),
        ("remediat", 0.90),
    ),
    "remodeling": (
        ("remodel", 0.86),
        ("renovation", 0.86),
        ("renovat", 0.84),
    ),
    "signage": (
        ("sign", 0.86),
        ("signage", 0.92),
        ("sign company", 0.88),
        ("sign hanger", 0.90),
    ),
    "general_contractor": (
        ("general contractor", 0.80),
        ("general contractors", 0.80),
    ),
}

# Termos que desqualificam o sinal de nome. Ex.: "ABC Plumbing Supply" não é
# um canalizador; "Boro Waste Oil" não é remoção de entulho.
NEGATIVE_TOKENS: tuple[str, ...] = (
    "supply",
    "supplies",
    "distributor",
    "showroom",
    "rental",
    "rentals",
    "school",
    "academy",
    "training",
    "waste oil",
    "oil recycling",
)

_LEGAL_SUFFIXES = (
    "llc",
    "l l c",
    "inc",
    "incorporated",
    "corp",
    "corporation",
    "co",
    "company",
    "ltd",
    "limited",
    "lp",
    "llp",
    "pllc",
    "pc",
    "dba",
)


@dataclass(frozen=True)
class TradeSignal:
    trade: str
    confidence: float
    source: str
    reason: str = ""


def normalize_text(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def _strip_legal_suffixes(text: str) -> str:
    tokens = text.split()
    changed = True
    while changed and tokens:
        changed = False
        for suffix in _LEGAL_SUFFIXES:
            parts = suffix.split()
            if tokens[-len(parts) :] == parts:
                tokens = tokens[: -len(parts)]
                changed = True
                break
    return " ".join(tokens)


def license_trade(license_type: object) -> Optional[TradeSignal]:
    raw = " ".join(str(license_type or "").upper().split())
    if not raw:
        return None
    trade = LICENSE_TYPE_TO_TRADE.get(raw)
    if not trade:
        return None
    return TradeSignal(trade, 0.95, "license_type", raw)


def alias_trade(value: object) -> Optional[str]:
    text = normalize_text(value)
    if not text:
        return None
    return TRADE_ALIASES.get(text)


def _has_negative(name: str) -> bool:
    return any(token in name for token in NEGATIVE_TOKENS)


_AMBIGUOUS_TOKEN_PATTERNS = {
    # "sign" dentro de "design" e "door" dentro de "outdoor" são falsos
    # positivos clássicos; "clean" dentro de "cleanleaf" idem.
    "sign": r"(?<![a-z0-9])(sign|signs|signage|sign company|sign hanger)(?![a-z0-9])",
    "door": r"(?<![a-z0-9])(door|doors|doorway|doorways)(?![a-z0-9])",
    "clean": r"(?<![a-z0-9])(clean|cleans|cleaning|cleaner|cleaners|cleanup)(?![a-z0-9])",
}


def token_matches(text: object, token: object) -> bool:
    """Match por início de palavra, com exceções para tokens ambíguos."""
    haystack = normalize_text(text)
    needle = normalize_text(token)
    if not haystack or not needle:
        return False
    pattern = _AMBIGUOUS_TOKEN_PATTERNS.get(needle)
    if pattern:
        return re.search(pattern, haystack) is not None
    return re.search(r"(?<![a-z0-9])" + re.escape(needle), haystack) is not None


def name_signals(company_name: object) -> list[TradeSignal]:
    raw = normalize_text(company_name)
    name = _strip_legal_suffixes(raw)
    if not name or _has_negative(name):
        return []
    out: list[TradeSignal] = []
    for trade, rules in NAME_RULES.items():
        matches = [
            (token, weight)
            for token, weight in rules
            if token_matches(name, token)
        ]
        if not matches:
            continue
        best = max(weight for _, weight in matches)
        # Dois tokens do mesmo trade reforçam a confiança.
        if len(matches) > 1:
            best = min(0.95, best + 0.03)
        out.append(
            TradeSignal(
                trade,
                round(best, 3),
                "name",
                ",".join(token for token, _ in matches),
            )
        )
    return out


def site_signals(site_text: object) -> list[TradeSignal]:
    """Sinais de ofício a partir do texto público do site da empresa.

    É um sinal mais fraco do que o nome/licença: o site pode falar de vários
    serviços. Só entra com confiança suficiente para desempatar, nunca para
    substituir um `license_type` forte.
    """
    raw = normalize_text(site_text)
    if not raw or _has_negative(raw):
        return []
    out: list[TradeSignal] = []
    for trade, rules in NAME_RULES.items():
        matches = [
            (token, weight)
            for token, weight in rules
            if token_matches(raw, token)
        ]
        if not matches:
            continue
        best = min(0.84, max(weight for _, weight in matches) - 0.06)
        if len(matches) > 1:
            best = min(0.86, best + 0.02)
        out.append(
            TradeSignal(
                trade,
                round(best, 3),
                "site_text",
                ",".join(token for token, _ in matches),
            )
        )
    return out


def classify_company(
    company_name: object = "",
    *,
    license_type: object = "",
    niche_key: object = "",
    primary_trade: object = "",
    site_text: object = "",
) -> list[TradeSignal]:
    """Devolve sinais de trade ordenados por confiança (maior primeiro).

    Não escreve na BD. A decisão de campanha usa `confidence >= 0.80`.
    """
    signals: dict[str, TradeSignal] = {}

    def add(signal: Optional[TradeSignal]) -> None:
        if signal and signal.trade:
            current = signals.get(signal.trade)
            if current is None or signal.confidence > current.confidence:
                signals[signal.trade] = signal

    add(license_trade(license_type))

    niche = normalize_text(niche_key)
    if niche:
        code = alias_trade(niche) or (niche if niche in EXACT_TRADES else None)
        if code:
            add(TradeSignal(code, 0.92, "niche_key", niche))

    for signal in name_signals(company_name):
        add(signal)

    for signal in site_signals(site_text):
        add(signal)

    primary = normalize_text(primary_trade)
    if primary:
        code = alias_trade(primary) or primary
        if code in TRADE_TO_CATEGORIES:
            # O campo primário é um bom sinal quando já é específico. Para
            # `general_contractor`/`remodeling` só conta se o nome confirmar,
            # porque esses dois são o saco histórico da base.
            if code not in ("general_contractor", "remodeling"):
                add(TradeSignal(code, 0.90, "primary_trade", primary))

    return sorted(signals.values(), key=lambda s: (-s.confidence, s.trade))


def category_for_trade(trade: object) -> str:
    """Trade de voz -> primeira categoria canónica (para atribuição)."""
    code = alias_trade(trade) or normalize_text(trade)
    categories = TRADE_TO_CATEGORIES.get(code or "")
    return categories[0] if categories else ""


def category_trade(category: object) -> Optional[str]:
    """Mapeia uma categoria/label do dropdown para o trade primário de voz."""
    text = " ".join(str(category or "").strip().split())
    if not text:
        return None
    for canonical, trades in CATEGORY_TO_TRADES.items():
        if text.lower() == canonical.lower() and trades:
            return trades[0]
    alias = alias_trade(text)
    if alias:
        return alias
    # Labels do dropdown em inglês.
    dropdown = {
        "roofing and structure": "roofing",
        "roofing & structure": "roofing",
        "structure": "remodeling",
        "plumbing": "plumbing",
        "yard and debris": "landscaping",
        "yard & debris": "landscaping",
        "grass and debris": "landscaping",
        "grass & debris": "landscaping",
        "painting": "painting",
        "jobs and permits": None,
        "jobs & permits": None,
        "construction and permits": None,
        "construction & permits": None,
        "heating and hot water": "hvac",
        "heating & hot water": "hvac",
        "electrical": "electrical",
        "elevators": "elevator",
        "gas and leaks": "hvac",
        "gas & leaks": "hvac",
        "rodents and pests": "pest_control",
        "rodents & pests": "pest_control",
        "mold and moisture": "remediation",
        "mold & moisture": "remediation",
        "lead and paint": "painting",
        "lead & paint": "painting",
        "unsanitary and sewer": "cleaning",
        "unsanitary & sewer": "cleaning",
        "unsanitary and sewage": "cleaning",
        "unsanitary & sewage": "cleaning",
        "doors and windows": "windows",
        "doors & windows": "windows",
        "debris and trash": "debris_removal",
        "debris & trash": "debris_removal",
    }
    return dropdown.get(normalize_text(text))


def signals_for_company(
    company_name: object,
    *,
    license_type: object = "",
    niche_key: object = "",
    primary_trade: object = "",
    site_text: object = "",
    min_confidence: float = 0.0,
) -> list[TradeSignal]:
    signals = classify_company(
        company_name,
        license_type=license_type,
        niche_key=niche_key,
        primary_trade=primary_trade,
        site_text=site_text,
    )
    return [s for s in signals if s.confidence >= min_confidence]


def merge_signals(
    signals: Iterable[TradeSignal],
) -> dict[str, TradeSignal]:
    out: dict[str, TradeSignal] = {}
    for signal in signals:
        current = out.get(signal.trade)
        if current is None or signal.confidence > current.confidence:
            out[signal.trade] = signal
    return out

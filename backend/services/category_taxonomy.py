"""Fonte unica de verdade para as categorias de oficio.

Este modulo substitui as tres implementacoes divergentes que existiam antes:
`scraper._infer_category_ex`, `alert_categories.canonical_category` e o
`CATEGORIES/catOfLead` do dashboard. A classificacao e deliberadamente
conservadora:

* palavras sao comparadas com fronteiras (`\\b`), nunca por substring cega;
* frases municipais/compliance (cart maintenance, missed garbage, benchmarking,
  animal control, line locate, etc.) vao para `Unclassified` ANTES de qualquer
  regra de oficio;
* uma descricao ambigua ou sem sinal de oficio NAO cai em Roof/Structure; cai em
  `Unclassified`, que fica fora do feed publico;
* fontes legais (permit/DOB/HPD) nao tem fallback automatico para
  `Permit_Rejected`; so entram nessa categoria quando o texto nomeia um problema
  de permit de forma explicita.

O resultado e deterministico e testavel: `classify()` devolve tambem a regra
que decidiu (`rule`) e o texto que casou (`reason`), para auditoria.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Iterable, Optional

from ..models.schemas import IssueCategory

UNCLASSIFIED = "Unclassified"

# As 16 categorias comerciais. `Unclassified` NAO entra aqui: nao e' um oficio
# e nunca deve aparecer no feed, nos alertas ou nos interesses do utilizador.
TRADE_CATEGORIES: tuple[str, ...] = (
    "Debris",
    "Door_Window",
    "Electrical",
    "Elevator",
    "Gas",
    "Grass",
    "Heating",
    "Lead",
    "Mold",
    "Paint",
    "Permit_Rejected",
    "Plumbing",
    "Rodent",
    "Roof",
    "Structure",
    "Unsanitary",
)

ALL_CATEGORIES: tuple[str, ...] = TRADE_CATEGORIES + (UNCLASSIFIED,)

# Aliases legados (PT) e rotulos B2B observados. As chaves sao normalizadas
# (minusculas, espacos colapsados).
_ALIASES_RAW: dict[str, str] = {
    # PT legado
    "telhado": "Roof",
    "estrutura": "Structure",
    "encanamento": "Plumbing",
    "mato": "Grass",
    "pintura": "Paint",
    "obras": "Permit_Rejected",
    "heating": "Heating",
    "electrical": "Electrical",
    "elevator": "Elevator",
    "gas": "Gas",
    "rodent": "Rodent",
    "mold": "Mold",
    "lead": "Lead",
    "unsanitary": "Unsanitary",
    "door_window": "Door_Window",
    "debris": "Debris",
    # B2B / nichos observados
    "general contractor": "Structure",
    "general contractors": "Structure",
    "remodeling": "Structure",
    "remodeling & renovation": "Structure",
    "remodeling and renovation": "Structure",
    "renovation": "Structure",
    "heating & hvac": "Heating",
    "heating and hvac": "Heating",
    "hvac": "Heating",
    "roofing": "Roof",
    "roofing & structure": "Roof",
    "restoration": "Mold",
    "restoration & cleanup": "Mold",
    "restoration and cleanup": "Mold",
    "landscaping": "Grass",
    "landscaping & grounds": "Grass",
    "landscaping and grounds": "Grass",
    "grounds": "Grass",
    "painting": "Paint",
    "doors & windows": "Door_Window",
    "doors and windows": "Door_Window",
    "door & window": "Door_Window",
    "permit rejected": "Permit_Rejected",
    "unsanitary conditions": "Unsanitary",
    # Estado seguro
    "unclassified": UNCLASSIFIED,
    "other": UNCLASSIFIED,
    "unknown": UNCLASSIFIED,
    "none": UNCLASSIFIED,
}

_CANONICAL_BY_LOWER = {value.lower(): value for value in TRADE_CATEGORIES}
_CANONICAL_BY_LOWER[UNCLASSIFIED.lower()] = UNCLASSIFIED
_ALIASES = dict(_ALIASES_RAW)


def _norm_alias_key(value: object) -> str:
    text = " ".join(str(value or "").strip().lower().split())
    return text


_ALIASES = {_norm_alias_key(k): v for k, v in _ALIASES.items()}


def normalize_category(raw: Optional[str]) -> str:
    """Devolve a chave canonica (16 oficios ou Unclassified) ou "".

    Aceita chaves canonicas, aliases PT e rotulos B2B. Nunca inventa uma
    categoria: texto desconhecido devolve "".
    """
    key = _norm_alias_key(raw)
    if not key:
        return ""
    if key in _CANONICAL_BY_LOWER:
        return _CANONICAL_BY_LOWER[key]
    return _ALIASES.get(key, "")


def is_trade_category(raw: Optional[str]) -> bool:
    return normalize_category(raw) in TRADE_CATEGORIES


def normalize_trade_categories(values: Iterable[object]) -> list[str]:
    """Normaliza interesses para as 16 categorias, sem Unclassified."""
    out: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        resolved = normalize_category(str(value) if value is not None else "")
        if not resolved or resolved == UNCLASSIFIED:
            continue
        if resolved in TRADE_CATEGORIES and resolved not in seen:
            seen.add(resolved)
            out.append(resolved)
    return out


@dataclass(frozen=True)
class Classification:
    category: IssueCategory
    matched: bool
    rule: str
    reason: str

    @property
    def value(self) -> str:
        return self.category.value


# ---------------------------------------------------------------------------
# Normalizacao do texto
# ---------------------------------------------------------------------------

def _normalize_text(value: object) -> str:
    text = html.unescape(str(value or ""))
    text = text.replace("\u00a0", " ").replace("\u2013", "-").replace("\u2014", "-")
    # Hifens/underscores viram espaco: "Animal-Abuse" -> "animal abuse",
    # "lead-based" -> "lead based", "fire-damaged" -> "fire damaged".
    # Barras ficam: "water/wastewater", "brush/bulk", "w/o" precisam delas.
    text = re.sub(r"[-_]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip().lower()
    # "DISP10/20Heat" -> "disp 10/20 heat"; "SCH10/2Chronic" -> "sch 10/2 chronic".
    text = re.sub(r"(?<=[0-9])(?=[a-z])", " ", text)
    text = re.sub(r"(?<=[a-z])(?=[0-9])", " ", text)
    return text


def _rx(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


# ---------------------------------------------------------------------------
# Regras negativas: nao sao oficio (municipal, compliance, animal, etc.)
# Correm ANTES de qualquer regra positiva. Uma descricao que caia aqui fica
# Unclassified e, portanto, fora do feed publico.
# ---------------------------------------------------------------------------
_NEGATIVE: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("not_trade.cart_maintenance", _rx(r"\bcart maintenance\b")),
    ("not_trade.missed_collection", _rx(
        r"\bmissed\s+(?:garbage|trash|recycl\w*|collection|pickup|pick-up|pick up|waste)\b"
    )),
    ("not_trade.litter_basket", _rx(r"\blitter\s+(?:basket|can)s?\b")),
    ("not_trade.street_cleaning", _rx(r"\bstreet cleaning\b")),
    ("not_trade.sanitation_code", _rx(r"\bsanitation code\b|\bsanitation worker\b")),
    ("not_trade.parking_code", _rx(
        r"\bfinance parking\b|\bparking code enforcement\b"
    )),
    ("not_trade.parking", _rx(
        r"\bparking enforcement\b|\billegal parking\b|\babandoned vehicles?\b|"
        r"\btowing\b|\bhydrant\b|\bparking permit\b"
    )),
    ("not_trade.street", _rx(
        r"\btraffic signal\b|\bsign repair\b|\bnew sign\b|\bcrosswalk\b|"
        r"\bstreet light\b|\bpothole\b|\bsidewalk repair\b|\bcurb repair\b"
    )),
    ("not_trade.needle", _rx(r"\bneedle pickup\b|\bneedles?\b")),
    ("not_trade.contractor_complaint", _rx(
        r"\bcontractors? complaints?\b|\butility contractor complaints?\b"
    )),
    ("not_trade.fair_housing", _rx(r"\bfair housing\b")),
    ("not_trade.animal", _rx(
        r"\banimal (?:abuse|in a park|loose|lack of care|aggressive behavior|"
        r"confined|nuisance|bite|owner surrender|illegal vending|community cat|"
        r"in trap)\b|\bstray animal\b|\binjured animal\b|\bdead animal\b|"
        r"\bdomestic animal\b|\bwild animal\b|\bvicious animal\b|"
        r"\bnuisance animal\b|\banimal control\b"
    )),
    ("not_trade.energy_compliance", _rx(
        r"\bbenchmarking\b|\benergy efficiency\b|\benergy use\b|\beer\b"
    )),
    ("not_trade.notice", _rx(
        r"\brent stabilization\b|\bpost a proper notice\b|\bjanitor\b|"
        r"\bencumbrance"
    )),
    ("not_trade.water_test", _rx(r"\bwater lead test\b|\bwater lead test visit\b")),
    ("not_trade.utility", _rx(
        r"\bline locate\b|\bwater questions\b|\bwater payments\b|"
        r"\bbilling inquiry\b|\bwater/wastewater line\b"
    )),
    ("not_trade.tree", _rx(
        r"\bovergrown tree\b|\btree/?branches?\b|\btree branches?\b|"
        r"\bprune\b|\bpruning\b"
    )),
    ("not_trade.brush_collection", _rx(
        r"\bmissed brush\b|\bbrush/?bulk\b|\bbrush bulk\b"
    )),
    ("not_trade.other", _rx(
        r"\bindoor air quality\b|\boutdoor dining\b|\bunleashed\b|"
        r"\bhomeless encampment\b|\bindustrial waste complaints?\b|"
        r"\brequest for information\b|\bsticker request\b|\bspecial events?\b"
    )),
    ("not_trade.inspection_request", _rx(r"\bbuilding inspection request\b")),
    ("not_trade.generic_maintenance", _rx(
        r"^maintenance complaint\b|\bmaintenance complaint - residential\b"
    )),
    ("not_trade.protection", _rx(r"\bprotection of adjoining property\b")),
    ("not_trade.code_concern", _rx(r"\bcode concern\b")),
    ("not_trade.dumping_sign", _rx(r"\bdumping sign\b")),
    ("not_trade.clean_sweep", _rx(r"\bclean sweep\b|\blitter removal\b")),
    ("not_trade.gas_station", _rx(r"\bgas station\b")),
    ("not_trade.ambiguous_utilities", _rx(
        r"\bunsatisfactory utilities\b|\bno utilities\s*\("
    )),
    ("not_trade.food_establishment", _rx(
        r"\bunsanitary conditions?\s+(?:(?:-|at)\s+)?(?:establishment|food|employees?)\b"
    )),
    ("not_trade.test", _rx(r"\bdebug test\b|\btest issue\b")),
    ("not_trade.other_exact", _rx(r"^other$")),
)


# ---------------------------------------------------------------------------
# Regras positivas. A ordem importa: primeiro o que e' inequivoco e perigoso,
# depois os oficios, e so no fim as categorias genericas.
# Estrutura severa vem antes de Mold/Roof para "STRUCTURE RENDERED NON
# COMPLIANT ... FIRE ... WATER DAMAGE ... ROOF" nao virar Mold/Roof.
# ---------------------------------------------------------------------------
_SEVERE_STRUCTURE = _rx(
    r"\b(?:structure|structural)\b[^.]{0,80}\b(?:non[- ]?compliant|unsafe|"
    r"collapse|collapsed|fire damage|fire-damaged|smoke damage)\b|"
    r"\b(?:load[- ]bearing|foundation failure|structural collapse|"
    r"unsafe structure|unsafe building)\b"
)

_POSITIVE: tuple[tuple[str, IssueCategory, re.Pattern[str]], ...] = (
    # Lead: "Lead", "Lead Dust", "Lead-Based Paint", "Lead Hazard",
    # "Lead Inspection", "Lead Abatement". NUNCA "leading"/"lead singer".
    ("lead.exact", IssueCategory.LEAD, _rx(
        r"^(?:lead|construction lead dust|lead inspection request)$"
    )),
    ("lead.suffix", IssueCategory.LEAD, _rx(r"\blead\s*$")),
    ("lead.context", IssueCategory.LEAD, _rx(
        r"\blead(?:[-\s]?based)?\s+(?:paint|hazard|inspection|dust|abatement|"
        r"poisoning|exposure|test|testing)\b|"
        r"\b(?:paint|dust|hazard)\s+(?:with\s+)?lead\b"
    )),
    # Heating / HVAC
    ("heating.strong", IssueCategory.HEATING, _rx(
        r"\b(?:no heat|heat/hot water|hot water(?:er|ers)?|boilers?|radiators?|"
        r"furnaces?|hvac|heating systems?|steam heat|water heaters?)\b"
    )),
    ("heating.word", IssueCategory.HEATING, _rx(r"\bheat\b")),
    # Gas
    ("gas.strong", IssueCategory.GAS, _rx(
        r"\b(?:gas leaks?|gas odors?|gas smells?|gas lines?|gas service|"
        r"gas supply|gas meters?|gas pipes?|cooking gas)\b"
    )),
    ("gas.word", IssueCategory.GAS, _rx(r"\bgas\b")),
    # Elevator (antes de Electrical: descricoes de elevador citam eletricidade)
    ("elevator", IssueCategory.ELEVATOR, _rx(
        r"\b(?:elevators?|escalators?|chair lifts?|platform lifts?)\b"
    )),
    # Electrical
    ("electrical.strong", IssueCategory.ELECTRICAL, _rx(
        r"\b(?:electrical? (?:wiring|panels?|outlets?|circuits?|service|work|"
        r"violations?|hazards?)|wiring|outlets?|circuit breakers?|"
        r"breaker panels?|live wires?|exposed wires?|short circuits?|"
        r"solar panels?)\b"
    )),
    ("electrical.word", IssueCategory.ELECTRICAL, _rx(r"\b(?:electric|electrical)\b")),
    # Rodent / pest
    ("rodent", IssueCategory.RODENT, _rx(
        r"\b(?:rodent|rat|rats|mouse|mice|vermin|roach|roaches|cockroach|"
        r"cockroaches|pest|pests|infestation|bed bug|bed bugs|pigeon|pigeons)\b"
    )),
    # Unsanitary / sewage
    ("unsanitary", IssueCategory.UNSANITARY, _rx(
        r"\b(?:unsanitary|insanitary|filth|hoarding|squalid|raw sewage|"
        r"sewage backup|sewage discharge|unsatisfactory living conditions)\b"
    )),
    # Mold / dampness / restoration
    ("mold", IssueCategory.MOLD, _rx(
        r"\b(?:molds?|mildew|fungus|fungi|mold remediation|chronic dampness|"
        r"water damage)\b"
    )),
    # Door / window (word boundary: indoor/outdoor NAO casam)
    ("door_window", IssueCategory.DOOR_WINDOW, _rx(
        r"\b(?:doors?|windows?|sashes?|jambs?|door frames?|window frames?|"
        r"broken windows?|stuck windows?)\b"
    )),
    # Debris / trash / dumping
    ("debris", IssueCategory.DEBRIS, _rx(
        r"\b(?:debris|garbage|trash|rubbish|litter|dumping|junk|dumpsters?|"
        r"bulk removal|overflowing garbage|construction debris)\b"
    )),
    # Roof (word boundary: proof/waterproof/fireproof NAO casam)
    ("roof", IssueCategory.ROOF, _rx(
        r"\b(?:roofs?|roofing|roof leaks?|roof replacements?|roof repairs?|"
        r"shingles?|gutters?|rooftops?)\b"
    )),
    # Plumbing
    ("plumbing.strong", IssueCategory.PLUMBING, _rx(
        r"\b(?:plumbing|plumbers?|water leaks?|leaking pipes?|pipe leaks?|"
        r"burst pipes?|sewers?|sewer lines?|drains?|drainage|backflow|"
        r"water mains?|no water|water service|boiler leaks?|"
        r"water on (?:street|sidewalk|road)|water in basement|"
        r"low water pressure|water maintenance|water closets?|"
        r"flushing apparatus|cold water(?: supply)?|"
        r"no utilities[^.;]{0,40}\bwater\b|"
        r"leaky|faucets?|toilets?|bathtubs?|washbasins?)\b"
    )),
    ("plumbing.word", IssueCategory.PLUMBING, _rx(
        r"\b(?:plumb|leaks?|leaking|pipes?)\b"
    )),
    # Paint / plaster / graffiti
    ("paint", IssueCategory.PAINT, _rx(
        r"\b(?:paints?|painting|painted|plasters?|plastering|graffiti|"
        r"peeling paint|facade painting)\b"
    )),
    # Structure: sinais estruturais especificos e obra geral identificavel.
    ("structure.strong", IssueCategory.STRUCTURE, _rx(
        r"\b(?:structural|structures?|foundations?|load[- ]bearing|collapses?|"
        r"collapsed|unsafe buildings?|sagging|buckling|deteriorat(?:ed|ing|ion)|"
        r"parapets?|chimneys?|masonry|tuckpoint|stoops?|porches?|decks?|"
        r"retaining walls?|party walls?|garages?|framing|"
        r"frames? (?:garages?|buildings?|residences?|houses?)|"
        r"new construction|renovations?|remodel(?:ing)?|build[- ]outs?|"
        r"general contractors?|demolition|wreck|excavation|fire damage|"
        r"fire-damaged|smoke damage)\b"
    )),
    ("structure.word", IssueCategory.STRUCTURE, _rx(
        r"\b(?:wall|walls|crack|cracked|cracks)\b"
    )),
    # Permit issue explicito. Fica depois dos oficios concretos (um "roof
    # without permit" continua Roof) e antes de Grass/Structure generico.
    ("permit.rejected", IssueCategory.PERMIT_REJECTED, _rx(
        r"\b(?:permit (?:rejected|denied|revoked|expired)|stop work order|"
        r"work (?:without|w/o|w/out) (?:a )?permit|no building permit|"
        r"building permits? violation|permit violation|illegal construction|"
        r"unpermitted work)\b"
    )),
    # Grass / vegetation. "overgrown" sozinho NAO basta; exige vegetacao.
    ("grass", IssueCategory.GRASS, _rx(
        r"\b(?:grass|weeds?|vegetation|vacant lots?|tall grass|"
        r"overgrown (?:grass|weeds?|vegetation|lots?|yards?|lawns?)|"
        r"excessive vegetation|blight|brush (?:removal|clearance|clearing)|"
        r"overgrown brush)\b"
    )),
)


def _first(patterns, text: str):
    for rule, rx in patterns:
        m = rx.search(text)
        if m:
            return rule, m.group(0)
    return None, None


def classify(
    description: object,
    source_type: Optional[str] = None,
    *,
    city: Optional[str] = None,
    case_title: Optional[str] = None,
    descriptor: Optional[str] = None,
) -> Classification:
    """Classifica uma descricao num dos 16 oficios ou em Unclassified.

    `matched=True` significa "nomeia um oficio real" e e' o unico caso que o
    feed publico aceita. `matched=False` => Unclassified.
    """
    text = _normalize_text(description or case_title or descriptor or "")
    if not text:
        return Classification(
            IssueCategory.UNCLASSIFIED, False, "empty", "sem descricao"
        )

    # Rotulos B2B: "B2B contact import (Restoration & Cleanup)".
    src = str(source_type or "").strip().lower()
    if src == "import_b2b" or text.startswith("b2b contact import"):
        m = re.search(r"\(([^)]+)\)", text)
        label = (m.group(1) if m else text).strip()
        alias = normalize_category(label)
        if alias in TRADE_CATEGORIES:
            return Classification(
                IssueCategory(alias), True, "b2b.alias", f"alias: {label}"
            )
        return Classification(
            IssueCategory.UNCLASSIFIED,
            False,
            "b2b.unknown",
            f"rotulo B2B sem oficio: {label}",
        )

    # 1) Exclusoes municipais/compliance. Correm antes de tudo.
    rule, hit = _first(_NEGATIVE, text)
    if rule:
        return Classification(
            IssueCategory.UNCLASSIFIED, False, rule, f"excluido: {hit}"
        )

    # 2) Estrutura severa (fire/collapse/unsafe) antes de Mold/Roof.
    if _SEVERE_STRUCTURE.search(text):
        return Classification(
            IssueCategory.STRUCTURE,
            True,
            "structure.severe",
            f"match: {_SEVERE_STRUCTURE.search(text).group(0)}",
        )

    # 3) Oficios, por ordem de especificidade.
    for rule, category, rx in _POSITIVE:
        m = rx.search(text)
        if m:
            return Classification(
                category, True, rule, f"match: {m.group(0)}"
            )

    # 4) Sem sinal de oficio: estado seguro. Nunca Roof/Structure.
    return Classification(
        IssueCategory.UNCLASSIFIED, False, "no_trade_match", "sem sinal de oficio"
    )

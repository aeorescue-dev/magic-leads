"""
Filtro e classificador de qualidade de leads para o motor de descoberta.

Descarta leads institucionais, orgaos de governo, condomínios e registros sem
responsável elegível (ex: "UNAVAILABLE OWNER"), direcionando os recursos de
descoberta apenas para empreiteiros e empresas comerciais reais.
"""

from __future__ import annotations

import re
import unicodedata

# Padrão de nomes institucionais, governamentais, imobiliários patrimoniais e sem proprietário
INSTITUTIONAL_PAT = re.compile(
    r"(UNAVAILABLE|CITY OF|HOUSING AUTHORITY|^NYC\b|DEPARTMENT|DEPT\b|DIVISION|"
    r"BUREAU|TRANSIT|MTA\b|SCHOOL|UNIVERSITY|HOSPITAL|CHURCH|PARISH|DIOCESE|"
    r"CONDOMINIUM|CONDO\b|CO-?OP\b|TENANTS|HOMEOWNERS|ASSOCIATION|^ASSOC\b|"
    r"HDFC|HOUSING DEVELOPMENT FUND|^TRUST\b|ESTATE OF|^BANK\b|CREDIT UNION|"
    r"FOUNDATION|CHARIT|MUNICIPAL|GOVERNMENT|AUTHORITY$|ADMINISTRATION)",
    re.I,
)

# Padrão de palavras-chave que caracterizam empresas e negócios de ofício
COMPANY_PAT = re.compile(
    r"(LLC|L\.L\.C|INC\b|CORP\b|COMPANY|CO\.\b|LTD\b|LP\b|LLP\b|PLLC|"
    r"CONSTRUCTION|CONTRACTING|CONTRACTORS?|BUILDERS?|ROOFING|PLUMBING|"
    r"ELECTRIC|HVAC|MECHANICAL|RENOVATION|REMODELING|DEVELOPMENT|PROPERTIES|"
    r"REALTY|MANAGEMENT|MGMT|ENTERPRISES|SUPPLY|ARCHITECT|ENGINEERING|"
    r"CONSULTING|HOLDINGS|PARTNERS|BROTHERS|SONS|MASONRY|PAINTING|FLOORING|"
    r"EXTERMINAT|LANDSCAP|SCAFFOLD|DEMOLITION|EXCAVAT|WELDING|GLASS|"
    r"ELECTRICAL|EQUIPMENT|STUDIO|RESTAURANT|BREW|SIGNS?|DECAL|GRAPHICS|"
    r"PRINT|AUTO|MARKET|DELI|CAFE|PIZZA|BAKERY|SALON|CLEANERS|PHARMACY|"
    r"MEDICAL|DENTAL|HARDWARE|PAINT\b|TRADING|INDUSTRIES|INTERIORS|"
    r"KITCHEN|BATH|WINDOWS|DOORS|ROOF|FENCE|PAVING|CONCRETE|IRON|STEEL|"
    r"METAL|LUMBER|TILE|CARPENTRY|DRYWALL)",
    re.I,
)

# Tokens genéricos de sufixo corporativo para normalização de nomes
SUFFIX_TOKENS = {
    "llc", "l.l.c", "inc", "incorporated", "corp", "corporation", "co", "company",
    "ltd", "limited", "lp", "llp", "pllc", "pc", "plc", "associates", "assoc",
    "and", "the", "of", "usa", "group", "holdings", "partners", "enterprises",
    "services", "hdfc", "dba", "sr", "jr", "ii", "iii", "trust", "estate",
}


def strip_accents(s: str) -> str:
    """Remove diacríticos e acentos."""
    return "".join(
        c for c in unicodedata.normalize("NFKD", s or "")
        if not unicodedata.combining(c)
    )


def norm_space(s: str) -> str:
    """Normaliza múltiplos espaços para um espaço único."""
    return re.sub(r"\s+", " ", (s or "").strip())


def norm_key(s: str) -> str:
    """Gera chave canónica única para dedup de empresas em diretórios."""
    clean = strip_accents(s or "").upper()
    clean = re.sub(r"[^A-Z0-9&\s]", " ", clean)
    toks = [
        t for t in norm_space(clean).split(" ")
        if t and t.lower() not in SUFFIX_TOKENS
    ]
    return " ".join(toks)


def significant_tokens(name: str) -> list[str]:
    """Tokens com significado para comparar nomes (sem sufixos societários)."""
    clean = strip_accents(name or "").upper()
    clean = re.sub(r"[^A-Z0-9&\s]", " ", clean)
    toks = [t for t in norm_space(clean).split(" ") if t]
    out = [t for t in toks if t.lower() not in SUFFIX_TOKENS and len(t) >= 3]
    return out or toks


def parse_person(name: str) -> tuple[str, str]:
    """Devolve (first, last) a partir do nome de uma pessoa física."""
    n = re.sub(r"\b(MR|MRS|MS|DR|JR|SR|II|III|IV)\b\.?", "", (name or "").upper())
    n = strip_accents(n)
    n = re.sub(r"[^A-Za-z,\s]", " ", n)
    if "," in n:
        last, _, first = n.partition(",")
        f = [t for t in first.split() if len(t) > 1]
        l = [t for t in last.split() if len(t) > 1]
        return (f[0] if f else ""), (l[0] if l else "")
    toks = [t for t in n.split() if len(t) > 1]
    if len(toks) >= 2:
        return toks[0], toks[-1]
    return (toks[0] if toks else ""), ""


def classify_owner_name(name: str) -> str:
    """Classifica um nome de proprietário/empresa.

    Retornos possíveis:
    - 'institutional': agências públicas, condomínios, HDFC, doações, sem nome.
    - 'company': pessoa jurídica comercial (LLC, Inc, Construction, etc.).
    - 'person': pessoa física (nome composto ou com vírgula).
    - 'empty': nome vazio ou nulo.
    """
    n = norm_space(name)
    if not n:
        return "empty"
    if n.upper() == "UNAVAILABLE OWNER" or INSTITUTIONAL_PAT.search(n):
        return "institutional"
    if COMPANY_PAT.search(n):
        return "company"
    toks = [t for t in re.sub(r"[^A-Za-z0-9]", " ", strip_accents(n)).split() if t]
    if "," in n or len(toks) >= 2:
        return "person"
    return "company"


def should_skip_discovery(name: str) -> bool:
    """Retorna True se o lead deve ser descartado da descoberta automática."""
    cls = classify_owner_name(name)
    return cls in ("institutional", "empty")

"""Outbound (cold e-mail) templates - English (US) only.

This module owns the copy sent to US contractors. Two hard rules:

  1. ENGLISH ONLY. The panel and the rest of the codebase are PT, but every
     template, preview and generated e-mail here is written in American
     Business English (en-US). US markets (NYC, Chicago, Dallas, Boston)
     expect the local corporate standard; matching it is what protects
     deliverability, compliance and reply rates. `assert_english_only` and
     the module-level check below fail the import if that ever regresses.

  2. DYNAMIC PER NICHE. A "niche" is a construction segment (roofing,
     remodeling, plumbing, ...). Each niche maps to the trade categories it
     should target and to its own subject/body template. The templates use
     `{placeholders}` that the panel fills with REAL data (the business name,
     a real opportunity address in the city) before the admin approves a
     batch, so the preview is the actual e-mail, not lorem ipsum.

Nothing here sends anything: this is template rendering only.
"""
from __future__ import annotations

import re
from typing import Any, Mapping, Optional

# --------------------------------------------------------------- language

# Accented characters and a few Portuguese/business-EU words that would signal
# the copy drifted out of en-US. Deliberately conservative: it must NEVER
# reject legitimate American English.
_NON_ASCII = re.compile(r"[^\x00-\x7F]")
_PT_MARKERS = re.compile(
    r"\b(ola|obrigado|equipa|oportunidades|chamados|licencas|conformidade|"
    r"proprietarios|empreiteiros|servico|gratis|voce|nosso|nossa)\b",
    re.IGNORECASE,
)


def assert_english_only(text: str) -> None:
    """Raise if `text` is not clean American English (no accents / PT words).

    Used as an import-time guard so a translated template can never ship.
    """
    if _NON_ASCII.search(text) or _PT_MARKERS.search(text):
        raise ValueError(f"Outbound template must be English (US) only: {text!r}")


# --------------------------------------------------------------- niches

# `label` is shown in the panel (English, since it names a US segment).
# `categories` are the IssueCategory values the niche targets; the simulator
# counts and samples only those leads for the niche.
#
# REGRA: nenhum nicho inclui categorias fora do seu oficio. Em particular,
# "General Contractors" NAO e' "todos os 16 oficios": e' construcao
# (Structure/Roof/Paint/Door_Window/Debris/Permit_Rejected). Pragas (Rodent),
# saneamento (Unsanitary) e vegetacao (Grass) pertencem a outros nichos —
# antes, GC herdava `_TRADE_CATEGORIES` inteiro e a previa mostrava
# "Categoria: Rodent" para um cliente de GC.
NICHES: dict[str, dict[str, Any]] = {
    "general_contractors": {
        "label": "General Contractors",
        "categories": [
            "Structure", "Roof", "Paint", "Door_Window", "Debris", "Permit_Rejected",
        ],
        "audience": "general contractors",
        "subject_trade": "GC",
        "hook_trade": "construction",
    },
    "roofing": {
        "label": "Roofing",
        "categories": ["Roof", "Structure"],
        "audience": "roofing companies",
        "subject_trade": "roofing",
        "hook_trade": "roofing",
    },
    "remodeling": {
        "label": "Remodeling & Renovation",
        "categories": ["Paint", "Structure", "Door_Window", "Debris", "Permit_Rejected"],
        "audience": "remodeling companies",
        "subject_trade": "remodeling",
        "hook_trade": "remodeling",
    },
    "plumbing": {
        "label": "Plumbing",
        "categories": ["Plumbing", "Lead"],
        "audience": "plumbing companies",
        "subject_trade": "plumbing",
        "hook_trade": "plumbing",
    },
    "electrical": {
        "label": "Electrical",
        "categories": ["Electrical", "Elevator", "Gas"],
        "audience": "electrical contractors",
        "subject_trade": "electrical",
        "hook_trade": "electrical",
    },
    "hvac": {
        "label": "Heating & HVAC",
        "categories": ["Heating", "Gas"],
        "audience": "HVAC companies",
        "subject_trade": "HVAC",
        "hook_trade": "heating and HVAC",
    },
    "restoration": {
        "label": "Restoration & Cleanup",
        "categories": ["Mold", "Unsanitary", "Rodent", "Lead", "Debris"],
        "audience": "restoration companies",
        "subject_trade": "restoration",
        "hook_trade": "restoration",
    },
    "landscaping": {
        "label": "Landscaping & Grounds",
        "categories": ["Grass"],
        "audience": "landscaping and groundskeeping companies",
        "subject_trade": "landscaping",
        "hook_trade": "groundskeeping",
    },
}

DEFAULT_NICHE = "general_contractors"

# Nome curto para o assunto (limite duro de 38 caracteres, para nao cortar no
# telemovel). O corpo usa sempre `display_city`.
CITY_SHORT: dict[str, str] = {
    "NYC": "NYC",
    "NEW YORK": "NYC",
    "BROOKLYN": "Brooklyn",
    "CHICAGO": "Chicago",
    "DALLAS": "Dallas",
    "BOSTON": "Boston",
}

SUBJECT_MAX = 38


# --------------------------------------------------------------- templates

# COPY POLICY: never reveal where the data comes from. No mention of 311,
# permits, code violations, city records, government agencies or "public
# databases" - that is internal intelligence. MagicLeads is positioned as a
# market-intelligence platform that connects contractors to active projects,
# property owners and commercial opportunities. Tone: commercial, direct,
# built to earn a reply (offer an exclusive sample for the contractor's city).
#
# Placeholders available to every template (all resolved from real data):
#   {contact_name}   recipient contact (falls back to "<Company> team", else
#                    "there") - see build_context for the rules
#   {city}           friendly market name ("New York City", "Chicago", ...)
#   {category}       humanized trade for the niche ("roofing", "plumbing")
#   {count}          number of matching opportunities (floored/rounded for the
#                    copy - see copy_count)
#   {address_tail}   conditional clause for the opportunity line ("..., including
#                    a verified project near <ADDRESS>" when a real address
#                    exists, else "..., including verified projects across
#                    <CITY>") - see build_context
#
# COPY POLICY (hardened, no trigger words): no prices, no competitor brand
# names (Angi/Google/Meta), no result claims, no ALL-CAPS superlatives. One URL
# only (footer), no tracking/UTM. A plain-text opt-out is mandatory. Copy is
# American Business English; keep it ASCII (assert_english_only rejects accents,
# curly quotes and em-dashes, so use ' and - only).
#
# NOTE: {company_name}, {state} and {sender_name} are still produced by
# build_context for backwards compatibility, but the hardened copy below does
# not reference them.
TEMPLATES: dict[str, dict[str, str]] = {
    "general_contractors": {
        "subject": "{subject}",
        "body": (
            "{greeting}\n\n"
            "{hook}\n\n"
            "Each one is matched to a single contractor: the address, the "
            "homeowner's details and the exact service needed - never shared "
            "with other {audience}.\n\n"
            "{cta}\n\n"
            "Best regards,\n"
            "Magic Leads\n\n"
            "https://www.magicleads.app/\n\n"
            'To stop receiving these emails, reply "unsubscribe".'
        ),
    },
    "roofing": {
        "subject": "{subject}",
        "body": (
            "{greeting}\n\n"
            "{hook}\n\n"
            "Each one is matched to a single contractor: the address, the "
            "homeowner's details and the exact service needed - never shared "
            "with other {audience}.\n\n"
            "{cta}\n\n"
            "Best regards,\n"
            "Magic Leads\n\n"
            "https://www.magicleads.app/\n\n"
            'To stop receiving these emails, reply "unsubscribe".'
        ),
    },
    "remodeling": {
        "subject": "{subject}",
        "body": (
            "{greeting}\n\n"
            "{hook}\n\n"
            "Each one is matched to a single contractor: the address, the "
            "homeowner's details and the exact service needed - never shared "
            "with other {audience}.\n\n"
            "{cta}\n\n"
            "Best regards,\n"
            "Magic Leads\n\n"
            "https://www.magicleads.app/\n\n"
            'To stop receiving these emails, reply "unsubscribe".'
        ),
    },
    "plumbing": {
        "subject": "{subject}",
        "body": (
            "{greeting}\n\n"
            "{hook}\n\n"
            "Each one is matched to a single contractor: the address, the "
            "homeowner's details and the exact service needed - never shared "
            "with other {audience}.\n\n"
            "{cta}\n\n"
            "Best regards,\n"
            "Magic Leads\n\n"
            "https://www.magicleads.app/\n\n"
            'To stop receiving these emails, reply "unsubscribe".'
        ),
    },
    "electrical": {
        "subject": "{subject}",
        "body": (
            "{greeting}\n\n"
            "{hook}\n\n"
            "Each one is matched to a single contractor: the address, the "
            "homeowner's details and the exact service needed - never shared "
            "with other {audience}.\n\n"
            "{cta}\n\n"
            "Best regards,\n"
            "Magic Leads\n\n"
            "https://www.magicleads.app/\n\n"
            'To stop receiving these emails, reply "unsubscribe".'
        ),
    },
    "hvac": {
        "subject": "{subject}",
        "body": (
            "{greeting}\n\n"
            "{hook}\n\n"
            "Each one is matched to a single contractor: the address, the "
            "homeowner's details and the exact service needed - never shared "
            "with other {audience}.\n\n"
            "{cta}\n\n"
            "Best regards,\n"
            "Magic Leads\n\n"
            "https://www.magicleads.app/\n\n"
            'To stop receiving these emails, reply "unsubscribe".'
        ),
    },
    "restoration": {
        "subject": "{subject}",
        "body": (
            "{greeting}\n\n"
            "{hook}\n\n"
            "Each one is matched to a single contractor: the address, the "
            "homeowner's details and the exact service needed - never shared "
            "with other {audience}.\n\n"
            "{cta}\n\n"
            "Best regards,\n"
            "Magic Leads\n\n"
            "https://www.magicleads.app/\n\n"
            'To stop receiving these emails, reply "unsubscribe".'
        ),
    },
    "landscaping": {
        "subject": "{subject}",
        "body": (
            "{greeting}\n\n"
            "{hook}\n\n"
            "Each one is matched to a single contractor: the address, the "
            "homeowner's details and the exact service needed - never shared "
            "with other {audience}.\n\n"
            "{cta}\n\n"
            "Best regards,\n"
            "Magic Leads\n\n"
            "https://www.magicleads.app/\n\n"
            'To stop receiving these emails, reply "unsubscribe".'
        ),
    },
}


# Import-time guard: no template may ship in a language other than en-US.
for _niche, _tpl in TEMPLATES.items():
    assert_english_only(_tpl["subject"])
    assert_english_only(_tpl["body"])
del _niche, _tpl


# --------------------------------------------------------------- sequence
#
# SEQUENCIA DE E-MAILS (Prioridade D).
#
# Passo 1 = e-mail de amostra (os templates de nicho acima): cria interesse sem
# preco nem marcas concorrentes.
# Passo 2 = e-mail da OFERTA ($120/semana). So' vai para quem JÁ recebeu o
# passo 1, por isso o preco aqui e' seguro para a entregabilidade (audiencia
# quente) e e' o que converte.
#
# O preco nao aparece no assunto (assunto com "$" e' gatilho de spam) e sim
# no corpo. A CTA leva para a landing com city/niche para o interested ver a
# cobertura da sua regiao antes de se registar.
SEQUENCE_TEMPLATES: dict[str, dict[str, str]] = {
    "step2_offer": {
        "subject": "{count} {category} jobs in {city} - one contractor each",
        "body": (
            "{greeting}\n\n"
            "I wanted to follow up on my last note with the straightforward part.\n\n"
            "Magic Leads gives you 300 verified opportunities a week in {city} - "
            "each one exclusive to a single contractor, with the owner's contact "
            "details and the exact service needed.\n\n"
            "It is $120 for 7 days. No commitment, and you can cancel whenever "
            "you want. If you close one job, the week pays for itself many "
            "times over.\n\n"
            "You can see what this week's list looks like here:\n"
            "{url}\n\n"
            "Best regards,\n"
            "Magic Leads\n\n"
            "https://www.magicleads.app/\n\n"
            'To stop receiving these emails, reply "unsubscribe".'
        ),
    },
}

for _step, _tpl in SEQUENCE_TEMPLATES.items():
    assert_english_only(_tpl["subject"])
    assert_english_only(_tpl["body"])
del _step, _tpl

# Link da landing para o passo da sequencia (o `url` no corpo do e-mail 2).
SEQUENCE_LANDING_BASE = "https://www.magicleads.app/en"


def sequence_url(city: Optional[str], niche: Optional[str], step: int = 2) -> str:
    """URL da landing para o passo da sequencia, com cidade e nicho."""
    parts = []
    if city:
        parts.append(f"city={str(city).strip().upper()}")
    if niche:
        parts.append(f"niche={niche}")
    parts.append(f"step={int(step)}")
    return f"{SEQUENCE_LANDING_BASE}?{'&'.join(parts)}"


def render_sequence_email(step: str, context: Mapping[str, str]) -> dict[str, str]:
    """Renderiza o e-mail de um passo da sequencia (subject+body), en-US."""
    tpl = SEQUENCE_TEMPLATES.get(step)
    if not tpl:
        raise KeyError(f"passo de sequencia desconhecido: {step}")
    subject = render(tpl["subject"], context).strip()
    body = render(tpl["body"], context).strip()
    assert_english_only(subject)
    assert_english_only(body)
    return {"subject": subject, "body": body}


# --------------------------------------------------------------- helpers

# Human-readable market names for the served cities (used inside the copy).
CITY_DISPLAY: dict[str, str] = {
    "NYC": "New York City",
    "CHICAGO": "Chicago",
    "DALLAS": "Dallas",
    "BOSTON": "Boston",
}

CITY_STATE: dict[str, str] = {
    "NYC": "NY",
    "CHICAGO": "IL",
    "DALLAS": "TX",
    "BOSTON": "MA",
}

_PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")


def copy_count(count: Any) -> str:
    """Opportunity count for the copy, showing exact number without artificial floor.

    Rules:
      * returns str(int(count)) if valid, else "0"
    """
    try:
        n = int(count)
        return str(max(0, n))
    except (TypeError, ValueError):
        return "0"


def niche_options() -> list[dict[str, Any]]:
    """Niches for the panel selector: key + English label + target categories."""
    return [
        {"key": key, "label": spec["label"], "categories": spec["categories"]}
        for key, spec in NICHES.items()
    ]


def niche_categories(niche: Optional[str]) -> Optional[list[str]]:
    """Categorias de oficio de um nicho (None => sem filtro).

    Inclui tambem o `label` do nicho: leads B2B importados sao gravados com
    `issue_category` = label (ex.: "General Contractors"), e sem isto ficavam
    invisiveis ao filtro do painel (ou apareciam em todos os nichos).
    """
    spec = NICHES.get(niche or DEFAULT_NICHE) or NICHES[DEFAULT_NICHE]
    categories = spec.get("categories")
    if not categories:
        return None
    out = list(categories)
    label = spec.get("label")
    if label and label not in out:
        out.append(label)
    return out


def get_template(niche: Optional[str]) -> dict[str, str]:
    """Raw template (subject+body) for a niche, falling back to the default."""
    return TEMPLATES.get(niche or DEFAULT_NICHE, TEMPLATES[DEFAULT_NICHE])


# IssueCategory value -> the trade word used inside the copy.
_TRADE_WORDS = {
    "Roof": "roofing",
    "Structure": "structural",
    "Plumbing": "plumbing",
    "Grass": "groundskeeping",
    "Paint": "painting",
    "Permit_Rejected": "permit",
    "Heating": "heating",
    "Electrical": "electrical",
    "Elevator": "elevator",
    "Gas": "gas",
    "Rodent": "pest control",
    "Mold": "mold remediation",
    "Lead": "lead abatement",
    "Unsanitary": "sanitation",
    "Door_Window": "door and window",
    "Debris": "debris removal",
}


def humanize_category(category: Optional[str]) -> str:
    """IssueCategory value -> lowercase trade word for the copy ("Roof" -> "roofing")."""
    if not category:
        return "construction"
    key = str(category).strip()
    if key in _TRADE_WORDS:
        return _TRADE_WORDS[key]
    return key.replace("_", " ").strip().lower()


# Fallback heuristics for recipient personalization. Recipient companies from
# the lead feed are often address SPVs (e.g. "20 E. 190TH ST. LLC") or empty,
# which read badly in the copy. These helpers keep the email natural:
#   - the greeting falls back to "<Company> team" when there is no contact name;
#   - the closing line uses "your team" instead of an address/generic company.
_GENERIC_COMPANIES = {
    "",
    "your company",
    "the company",
    "company",
    "your team",
    "team",
    "n/a",
    "na",
    "none",
    "unknown",
    "not available",
}

_HAS_HOUSE_NUMBER = re.compile(r"^\s*\d")
_STREET_TOKEN = re.compile(
    r"\b(?:ST|STREET|AVE|AVENUE|RD|ROAD|BLVD|BOULEVARD|DR|DRIVE|LN|LANE|PL|"
    r"PLACE|CT|COURT|WAY|TER|TERRACE|PKWY|PARKWAY|HWY|HIGHWAY|SQ|SQUARE)\b",
    re.IGNORECASE,
)
# Street suffix immediately followed by an entity suffix ("190TH ST. LLC").
_STREET_THEN_ENTITY = re.compile(
    r"\b(?:ST|STREET|AVE|AVENUE|RD|ROAD|BLVD|BOULEVARD|DR|DRIVE|LN|LANE|PL|"
    r"PLACE|CT|COURT|WAY|TER|TERRACE|PKWY|PARKWAY|HWY|HIGHWAY|SQ|SQUARE)\b\.?"
    r"\s+(?:LLC|L\.L\.C\.?|INC|CORP|LP|LLP|LTD|TRUST|HOLDINGS?)\b",
    re.IGNORECASE,
)


def is_generic_company(name: Optional[str]) -> bool:
    """True when the name is a placeholder rather than a real business."""
    return (name or "").strip().strip(",.").strip().lower() in _GENERIC_COMPANIES


def is_address_company(name: Optional[str]) -> bool:
    """True when the name looks like a property SPV (street address + entity)."""
    n = (name or "").strip()
    if not n:
        return False
    if _STREET_THEN_ENTITY.search(n):
        return True
    # "20 E. 190TH ST. LLC": a house number only counts with a street token, so
    # real brands like "5 Star Plumbing LLC" survive.
    return bool(_HAS_HOUSE_NUMBER.match(n)) and bool(_STREET_TOKEN.search(n))


def is_usable_company(name: Optional[str]) -> bool:
    """A company name worth showing: not empty, not generic, not an address."""
    n = (name or "").strip()
    return bool(n) and not is_generic_company(n) and not is_address_company(n)


# Apenas SERVICOS COMERCIAIS ATRATIVOS entram na clausula dinamica.
# Categorias internas de origem municipal (Lead, Debris, Permit_Rejected) ficam
# de fora de proposito: sao verdadeiras na base mas nao vendem nada e expoem
# vocabulario interno.
_ATTRACTIVE_SERVICES: dict[str, str] = {
    "Structure": "structural repairs",
    "Roof": "roof replacements",
    "Paint": "interior painting",
    "Door_Window": "window and door replacements",
    "Plumbing": "burst pipes and sewer backups",
    "Electrical": "panel upgrades",
    "Elevator": "elevator repairs",
    "Gas": "gas line work",
    "Heating": "no-heat emergencies",
    "Mold": "mold remediation",
    "Unsanitary": "sanitation cleanups",
    "Rodent": "pest control",
    "Grass": "groundskeeping",
}

# Fracao minima do inventario que as categorias escolhidas tem de representar.
COMPOSITION_MIN_SHARE = 0.4


def _fmt_count(value: int) -> str:
    """12521 -> '12,521' (leitura imediata e sem ambiguidade)."""
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value)


def composition_clause(
    top_categories: Optional[list[tuple[str, int]]],
    total: int,
    exclude: str = "",
) -> str:
    """Clausula " - including X and Y." derivada dos dados reais da cidade+nicho.

    Regras (nunca inventa composicao):
      * so' entram servicos comerciais atrativos (_ATTRACTIVE_SERVICES);
      * descarta a categoria que repete a palavra do proprio nicho;
      * exige que as categorias escolhidas representem >=40% do total;
      * devolve "" caso contrario.
    """
    if not top_categories or total <= 0:
        return ""
    ex = (exclude or "").lower()
    picked: list[tuple[str, int]] = []
    for cat, n in top_categories:
        if n <= 0:
            continue
        word = _ATTRACTIVE_SERVICES.get(cat)
        if not word:
            continue
        if ex and ex in word.lower():
            continue
        picked.append((word, n))
        if len(picked) == 2:
            break
    if not picked:
        return ""
    if sum(n for _, n in picked) / total < COMPOSITION_MIN_SHARE:
        return ""
    words = [w for w, _ in picked]
    if len(words) == 1:
        return f" - including {words[0]}."
    return f" - including {words[0]} and {words[1]}."


def build_context(
    sample: Optional[Mapping[str, Any]],
    city: str,
    niche: Optional[str],
    count: int,
    sender_name: str = "MagicLeads Outreach",
    contact: Optional[Mapping[str, Any]] = None,
    top_categories: Optional[list[tuple[str, int]]] = None,
) -> dict[str, str]:
    """Merge REAL data (contact + lead row + niche + city) into placeholders.

    Recipient fields (`company_name`, `contact_name`) come from an enriched
    `outbound_contacts` row when available; otherwise they fall back to the
    lead's `owner_name`. Personalization degrades gracefully so the copy always
    reads naturally:

    * `company_name` -> the real business name, or "your team" when the name is
      missing, generic, or an address SPV ("20 E. 190TH ST. LLC").
    * `contact_name` -> the individual's name, else "<Company> team" when a
      usable business name exists, else "there".

    The opportunity fields (`address`, `category`) always come from the real
    lead. Every value is a string; missing data falls back to English - never PT.
    """
    sample = sample or {}
    contact = contact or {}
    display_city = CITY_DISPLAY.get(city, city.title() if city else "your city")

    company = (contact.get("company_name") or "").strip()
    if not company:
        company = (sample.get("owner_name") or "").strip()
    company_usable = is_usable_company(company)

    contact_name = (contact.get("contact_name") or "").strip()
    if contact_name:
        greeting_name = contact_name
        greeting = f"Hi {contact_name},"
    elif company_usable:
        greeting_name = f"{company} team"
        greeting = "Hi,"
    else:
        greeting_name = "there"
        greeting = "Hi,"

    # Conditional opportunity clause: a real address reads naturally; with no
    # address or an intersection, we fall back to the city so the sentence
    # describes the active public record notice accurately.
    from backend.utils.address import is_intersection
    raw_address = (sample.get("address") or "").strip()
    # Leads B2B importados nao tem endereco: `import_b2b_lead` grava um
    # placeholder unico ("B2B contact - <email>") para satisfazer o
    # UNIQUE(address, city). Sem isto, o copy sairia com
    # "...near B2B contact - info@empresa.com", que parece spam quebrado.
    is_b2b_placeholder = raw_address.lower().startswith(("b2b contact", "b2b:"))
    real_address = "" if is_b2b_placeholder else raw_address

    if real_address and not is_intersection(real_address):
        address_tail = f", including an active public record notice near {real_address}"
    elif is_b2b_placeholder:
        # A frase ja' diz "in {city}"; nao vale repetir "across {city}".
        address_tail = ""
    else:
        address_tail = f", including active public record notices across {display_city}"

    spec = NICHES.get(niche or DEFAULT_NICHE) or NICHES[DEFAULT_NICHE]
    trade_short = spec.get("subject_trade") or spec["label"]
    hook_trade = spec.get("hook_trade") or trade_short
    audience = spec.get("audience") or "contractors"
    city_short = CITY_SHORT.get((city or "").upper(), display_city)

    count_txt = _fmt_count(count)
    # Assunto: nunca perder a palavra do nicho (e' o teste de relevancia).
    # Cadeia de fallback: "open in" -> "in" -> sem nicho (ultimo recurso).
    subject = f"{count_txt} {trade_short} projects open in {city_short}"
    if len(subject) > SUBJECT_MAX:
        subject = f"{count_txt} {trade_short} projects in {city_short}"
    if len(subject) > SUBJECT_MAX:
        subject = f"{count_txt} projects in {city_short}"

    composition = composition_clause(top_categories, count, exclude=hook_trade)
    hook = f"{count_txt} active {hook_trade} projects in {display_city} this week"
    hook = f"{hook}{composition}" if composition else f"{hook}."

    return {
        "subject": subject,
        "hook": hook,
        "cta": 'Reply with "send" and I will forward this week\'s list.',
        "audience": audience,
        "company_name": company if company_usable else "your team",
        "contact_name": greeting_name,
        "greeting": greeting,
        "city": display_city,
        "state": (contact.get("state") or "").strip() or CITY_STATE.get(city, ""),
        "category": humanize_category(sample.get("issue_category")),
        "address": real_address or "a property in your area",
        "address_tail": address_tail,
        "count": copy_count(count),
        "sender_name": sender_name,
    }


def render(template: str, context: Mapping[str, str]) -> str:
    """Substitute {placeholders}; unknown placeholders are left untouched."""

    def _sub(match: re.Match) -> str:
        key = match.group(1)
        value = context.get(key)
        return str(value) if value is not None else match.group(0)

    return _PLACEHOLDER.sub(_sub, template)


def render_email(
    niche: Optional[str],
    context: Mapping[str, str],
) -> dict[str, str]:
    """Render subject+body for a niche with the given context; assert en-US."""
    tpl = get_template(niche)
    subject = render(tpl["subject"], context).strip()
    body = render(tpl["body"], context).strip()
    assert_english_only(subject)
    assert_english_only(body)
    return {"subject": subject, "body": body}

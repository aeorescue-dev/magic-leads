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

from .db import _TRADE_CATEGORIES

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
NICHES: dict[str, dict[str, Any]] = {
    "general_contractors": {
        "label": "General Contractors",
        "categories": list(_TRADE_CATEGORIES),
        "audience": "general contractors",
    },
    "roofing": {
        "label": "Roofing",
        "categories": ["Roof", "Structure"],
        "audience": "roofing companies",
    },
    "remodeling": {
        "label": "Remodeling & Renovation",
        "categories": ["Paint", "Structure", "Door_Window", "Debris", "Permit_Rejected"],
        "audience": "remodeling companies",
    },
    "plumbing": {
        "label": "Plumbing",
        "categories": ["Plumbing", "Unsanitary", "Lead"],
        "audience": "plumbing companies",
    },
    "electrical": {
        "label": "Electrical",
        "categories": ["Electrical", "Elevator", "Gas"],
        "audience": "electrical contractors",
    },
    "hvac": {
        "label": "Heating & HVAC",
        "categories": ["Heating", "Gas", "Mold"],
        "audience": "HVAC companies",
    },
    "restoration": {
        "label": "Restoration & Cleanup",
        "categories": ["Mold", "Unsanitary", "Rodent", "Debris", "Lead"],
        "audience": "restoration companies",
    },
}

DEFAULT_NICHE = "general_contractors"


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
        "subject": "New project opportunities in {city} this week",
        "body": (
            "Hi {contact_name},\n\n"
            "We connect licensed general contractors in {city} with active, "
            "exclusive job opportunities - homeowners who need work done right "
            "now.\n\n"
            "Instead of chasing shared or cold leads, each opportunity is matched "
            "to a single contractor and includes the homeowner's contact details, "
            "the address, and the exact service needed.\n\n"
            "We currently have {count} active project opportunities in {city}"
            "{address_tail}.\n\n"
            "Would your team be open to reviewing this week's list?\n\n"
            "Best regards,\n"
            "Magic Leads\n\n"
            "https://www.magicleads.app/\n\n"
            'To stop receiving these emails, reply "unsubscribe".'
        ),
    },
    "roofing": {
        "subject": "New roofing projects in {city} this week",
        "body": (
            "Hi {contact_name},\n\n"
            "We connect licensed roofing contractors in {city} with active, "
            "exclusive job opportunities - homeowners who need work done right "
            "now.\n\n"
            "Instead of chasing shared or cold leads, each opportunity is matched "
            "to a single contractor and includes the homeowner's contact details, "
            "the address, and the exact service needed.\n\n"
            "We currently have {count} active roofing opportunities in {city}"
            "{address_tail}.\n\n"
            "Would your team be open to reviewing this week's list?\n\n"
            "Best regards,\n"
            "Magic Leads\n\n"
            "https://www.magicleads.app/\n\n"
            'To stop receiving these emails, reply "unsubscribe".'
        ),
    },
    "remodeling": {
        "subject": "New remodeling projects in {city} this week",
        "body": (
            "Hi {contact_name},\n\n"
            "We connect licensed remodeling contractors in {city} with active, "
            "exclusive job opportunities - homeowners who need work done right "
            "now.\n\n"
            "Instead of chasing shared or cold leads, each opportunity is matched "
            "to a single contractor and includes the homeowner's contact details, "
            "the address, and the exact service needed.\n\n"
            "We currently have {count} active remodeling opportunities in {city}"
            "{address_tail}.\n\n"
            "Would your team be open to reviewing this week's list?\n\n"
            "Best regards,\n"
            "Magic Leads\n\n"
            "https://www.magicleads.app/\n\n"
            'To stop receiving these emails, reply "unsubscribe".'
        ),
    },
    "plumbing": {
        "subject": "New plumbing projects in {city} this week",
        "body": (
            "Hi {contact_name},\n\n"
            "We connect licensed plumbing contractors in {city} with active, "
            "exclusive job opportunities - homeowners who need work done right "
            "now.\n\n"
            "Instead of chasing shared or cold leads, each opportunity is matched "
            "to a single contractor and includes the homeowner's contact details, "
            "the address, and the exact service needed.\n\n"
            "We currently have {count} active plumbing opportunities in {city}"
            "{address_tail}.\n\n"
            "Would your team be open to reviewing this week's list?\n\n"
            "Best regards,\n"
            "Magic Leads\n\n"
            "https://www.magicleads.app/\n\n"
            'To stop receiving these emails, reply "unsubscribe".'
        ),
    },
    "electrical": {
        "subject": "New electrical projects in {city} this week",
        "body": (
            "Hi {contact_name},\n\n"
            "We connect licensed electrical contractors in {city} with active, "
            "exclusive job opportunities - homeowners who need work done right "
            "now.\n\n"
            "Instead of chasing shared or cold leads, each opportunity is matched "
            "to a single contractor and includes the homeowner's contact details, "
            "the address, and the exact service needed.\n\n"
            "We currently have {count} active electrical opportunities in {city}"
            "{address_tail}.\n\n"
            "Would your team be open to reviewing this week's list?\n\n"
            "Best regards,\n"
            "Magic Leads\n\n"
            "https://www.magicleads.app/\n\n"
            'To stop receiving these emails, reply "unsubscribe".'
        ),
    },
    "hvac": {
        "subject": "New heating and HVAC projects in {city} this week",
        "body": (
            "Hi {contact_name},\n\n"
            "We connect licensed HVAC contractors in {city} with active, "
            "exclusive job opportunities - homeowners who need work done right "
            "now.\n\n"
            "Instead of chasing shared or cold leads, each opportunity is matched "
            "to a single contractor and includes the homeowner's contact details, "
            "the address, and the exact service needed.\n\n"
            "We currently have {count} active heating and HVAC opportunities in "
            "{city}{address_tail}.\n\n"
            "Would your team be open to reviewing this week's list?\n\n"
            "Best regards,\n"
            "Magic Leads\n\n"
            "https://www.magicleads.app/\n\n"
            'To stop receiving these emails, reply "unsubscribe".'
        ),
    },
    "restoration": {
        "subject": "New restoration projects in {city} this week",
        "body": (
            "Hi {contact_name},\n\n"
            "We connect licensed restoration contractors in {city} with active, "
            "exclusive job opportunities - homeowners who need work done right "
            "now.\n\n"
            "Instead of chasing shared or cold leads, each opportunity is matched "
            "to a single contractor and includes the homeowner's contact details, "
            "the address, and the exact service needed.\n\n"
            "We currently have {count} active restoration opportunities in {city}"
            "{address_tail}.\n\n"
            "Would your team be open to reviewing this week's list?\n\n"
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


# Business rule: the copy must never show a small or zero opportunity count
# (it destroys commercial credibility). Anything under the floor is shown as
# "<floor>+"; 40-99 shows the real number; 100+ is floored to a round ten so a
# large city reads as an approximate weekly volume, not a fake-precise figure.
COPY_COUNT_FLOOR = 40
COPY_COUNT_ROUND_AT = 100
COPY_COUNT_STEP = 10


def copy_count(count: Any) -> str:
    """Opportunity count for the copy, with a consistency floor.

    Rules (business-approved):
      * 0..(floor-1)      -> "<floor>+"          (e.g. 3 -> "40+")
      * floor..99         -> the real number     (e.g. 47 -> "47")
      * >= 100            -> floor to a ten      (e.g. 203 -> "200")
    """
    try:
        n = int(count)
    except (TypeError, ValueError):
        n = 0
    if n < COPY_COUNT_FLOOR:
        return f"{COPY_COUNT_FLOOR}+"
    if n < COPY_COUNT_ROUND_AT:
        return str(n)
    return str(n - (n % COPY_COUNT_STEP))


def niche_options() -> list[dict[str, Any]]:
    """Niches for the panel selector: key + English label + target categories."""
    return [
        {"key": key, "label": spec["label"], "categories": spec["categories"]}
        for key, spec in NICHES.items()
    ]


def niche_categories(niche: Optional[str]) -> Optional[list[str]]:
    """Trade categories for a niche (None => all trades, i.e. no filter)."""
    spec = NICHES.get(niche or DEFAULT_NICHE) or NICHES[DEFAULT_NICHE]
    categories = spec.get("categories")
    return list(categories) if categories else None


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


def build_context(
    sample: Optional[Mapping[str, Any]],
    city: str,
    niche: Optional[str],
    count: int,
    sender_name: str = "MagicLeads Outreach",
    contact: Optional[Mapping[str, Any]] = None,
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
    elif company_usable:
        greeting_name = f"{company} team"
    else:
        greeting_name = "there"

    # Conditional opportunity clause: a real address reads naturally; with no
    # address we fall back to the city so the sentence never repeats "your area".
    real_address = (sample.get("address") or "").strip()
    if real_address:
        address_tail = f", including a verified project near {real_address}"
    else:
        address_tail = f", including verified projects across {display_city}"

    return {
        "company_name": company if company_usable else "your team",
        "contact_name": greeting_name,
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

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

# Placeholders available to every template (all resolved from real data):
#   {company_name}   recipient business name
#   {contact_name}   recipient contact / first line of address book
#   {city}           friendly market name ("New York City", "Chicago", ...)
#   {state}          two-letter state ("NY", "IL", "TX", "MA")
#   {category}       humanized trade for the niche ("roofing", "plumbing")
#   {address}        a REAL opportunity address in the city
#   {count}          number of matching opportunities
#   {sender_name}    signer (the MagicLeads rep)
#
# All copy is American Business English.
TEMPLATES: dict[str, dict[str, str]] = {
    "general_contractors": {
        "subject": "{count} new contractor leads in {city} this week",
        "body": (
            "Hi {contact_name},\n\n"
            "I'm {sender_name} with MagicLeads. We track open permits, code "
            "violations and 311 service requests across {city} every day and "
            "turn them into ready-to-work job leads.\n\n"
            "Right now we have {count} active opportunities in {city} - for "
            "example {address}. Each lead includes the property address and the "
            "owner's contact details, so your team can reach out the same day.\n\n"
            "Would you like a free sample of this week's list for {company_name}?\n\n"
            "Best regards,\n"
            "{sender_name}\n"
            "MagicLeads - contractor leads for {city}, {state}"
        ),
    },
    "roofing": {
        "subject": "{count} roofing jobs open in {city} - free sample inside",
        "body": (
            "Hi {contact_name},\n\n"
            "This is {sender_name} at MagicLeads. We monitor roof permits, "
            "structural violations and 311 reports across {city} and package "
            "them as closing-ready roofing leads.\n\n"
            "We currently have {count} active roofing and structure "
            "opportunities in {city} - for instance {address}. Every record "
            "comes with the property address, the issue on file and the owner's "
            "contact info.\n\n"
            "Want a free sample of this week's jobs for {company_name}?\n\n"
            "Best regards,\n"
            "{sender_name}\n"
            "MagicLeads - roofing leads for {city}, {state}"
        ),
    },
    "remodeling": {
        "subject": "{count} remodeling jobs in {city} - leads ready to work",
        "body": (
            "Hi {contact_name},\n\n"
            "I'm {sender_name} with MagicLeads. We collect remodeling, "
            "renovation and permit activity across {city} and hand it to local "
            "remodeling companies as qualified leads.\n\n"
            "There are {count} active remodeling opportunities in {city} right "
            "now - one example is {address}. Each lead lists the property "
            "address, the scope on record and the owner's contact details.\n\n"
            "Would you like a free sample for {company_name} to test the "
            "quality?\n\n"
            "Best regards,\n"
            "{sender_name}\n"
            "MagicLeads - remodeling leads for {city}, {state}"
        ),
    },
    "plumbing": {
        "subject": "{count} plumbing jobs in {city} - work available now",
        "body": (
            "Hi {contact_name},\n\n"
            "This is {sender_name} at MagicLeads. We track plumbing violations, "
            "unsanitary conditions and permit activity across {city} and turn "
            "them into plumbing work leads.\n\n"
            "We have {count} active plumbing opportunities in {city} - for "
            "example {address}. Each one comes with the property address, the "
            "issue on file and the owner's contact details.\n\n"
            "Interested in a free sample for {company_name}?\n\n"
            "Best regards,\n"
            "{sender_name}\n"
            "MagicLeads - plumbing leads for {city}, {state}"
        ),
    },
    "electrical": {
        "subject": "{count} electrical jobs in {city} - verified leads",
        "body": (
            "Hi {contact_name},\n\n"
            "I'm {sender_name} with MagicLeads. We monitor electrical, elevator "
            "and gas violations across {city} so licensed electrical "
            "contractors can act on them first.\n\n"
            "There are {count} active electrical opportunities in {city} right "
            "now - for example {address}. Every lead includes the property "
            "address, the issue on file and the owner's contact info.\n\n"
            "Would you like a free sample this week for {company_name}?\n\n"
            "Best regards,\n"
            "{sender_name}\n"
            "MagicLeads - electrical leads for {city}, {state}"
        ),
    },
    "hvac": {
        "subject": "{count} heating and HVAC jobs in {city} - free sample",
        "body": (
            "Hi {contact_name},\n\n"
            "This is {sender_name} at MagicLeads. We track heating complaints, "
            "gas issues and mold reports across {city} and package them as HVAC "
            "service leads.\n\n"
            "We currently have {count} active heating and HVAC opportunities in "
            "{city} - for example {address}. Each record includes the property "
            "address, the issue on file and the owner's contact details.\n\n"
            "Want a free sample of this week's jobs for {company_name}?\n\n"
            "Best regards,\n"
            "{sender_name}\n"
            "MagicLeads - HVAC leads for {city}, {state}"
        ),
    },
    "restoration": {
        "subject": "{count} restoration jobs in {city} - leads ready now",
        "body": (
            "Hi {contact_name},\n\n"
            "I'm {sender_name} with MagicLeads. We monitor mold, unsanitary, "
            "rodent and debris reports across {city} and turn them into "
            "restoration and cleanup leads.\n\n"
            "There are {count} active restoration opportunities in {city} right "
            "now - for example {address}. Each lead lists the property address, "
            "the issue on file and the owner's contact info.\n\n"
            "Would you like a free sample for {company_name}?\n\n"
            "Best regards,\n"
            "{sender_name}\n"
            "MagicLeads - restoration leads for {city}, {state}"
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
    lead's `owner_name` (clearly a stand-in) and a generic greeting. The
    opportunity fields (`address`, `category`) always come from the real lead.
    Every value is a string; missing data falls back to English - never PT.
    """
    sample = sample or {}
    contact = contact or {}
    display_city = CITY_DISPLAY.get(city, city.title() if city else "your city")

    company = (contact.get("company_name") or "").strip()
    if not company:
        company = (sample.get("owner_name") or "").strip()

    return {
        "company_name": company or "your company",
        "contact_name": (contact.get("contact_name") or "").strip() or "there",
        "city": display_city,
        "state": (contact.get("state") or "").strip() or CITY_STATE.get(city, ""),
        "category": humanize_category(sample.get("issue_category")),
        "address": (sample.get("address") or "").strip() or "a property in your area",
        "count": str(int(count)),
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

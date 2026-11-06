"""Cria e aprova o override city-wide de Dallas.

Executar depois do deploy da Fase 1, quando `voice_scripts` já tem a versão
global. O corpo usa `{{showcase_line}}` (linha city-wide da guard) e não
`{{count}}`, para não colidir com a regra exact-only do V7.4.

Uso:
    python scripts/seed_dallas_city_override.py
"""
from __future__ import annotations

from backend.services import voice_scripts

BODY = (
    "Hi {{company | Contractor}}. This is an automated message from Magic Leads "
    "in Dallas. We have {{showcase_line}} on MagicLeads.app right now. While "
    "shared lead apps sell the same contact to multiple contractors, we give "
    "you the owner's direct name, verified address, and job details before "
    "anyone else in Dallas. You just call, visit, or send a letter, and close "
    "the deal. Go to magicleads.app right now. To opt out, press 2."
)
TRADES = (
    "remodeling",
    "roofing",
    "electrical",
    "painting",
    "hvac",
    "plumbing",
    "landscaping",
    "windows",
    "general_contractor",
    "remediation",
    "cleaning",
    "pest_control",
    "debris_removal",
    "elevator",
    "signage",
)


def main() -> int:
    voice_scripts.init()
    for trade in TRADES:
        override = voice_scripts.save_override(
            trade,
            "city",
            "Dallas",
            BODY,
            disclosure="Hi {{company | Contractor}}, this is an automated assistant from Magic Leads.",
            user_id=0,
        )
        voice_scripts.approve_override(int(override["id"]), user_id=0)
    print(f"dallas city override: {len(TRADES)} trades approved")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

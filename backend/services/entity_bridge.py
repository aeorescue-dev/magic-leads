"""Ponte `contractor_entities (ready)` -> `outbound_contacts` (nicho confirmado).

Só cria contacto/lead quando o nicho é `confirmed`. O contacto entra com
`email_source='import'` e `niche_status='confirmed'`, que é o que o motor de
envio já aceita. Idempotente pelo e-mail (UNIQUE) e pelo `external_id`
(`b2b:<email>`). Nunca envia nada.
"""
from __future__ import annotations

from typing import Optional

from . import niche_classifier, outbound_templates
from .db import db_service


async def bridge_entity(entity: dict) -> str:
    """Confirma nicho e cria o contacto. Devolve o resultado para o scheduler."""
    entity_id = int(entity["id"])
    verdict = niche_classifier.classify(
        entity.get("legal_name") or "", domain=entity.get("domain") or ""
    )
    niche_key: Optional[str] = verdict.get("niche")
    niche_status = str(verdict.get("status") or "unknown")
    await db_service.set_contractor_entity_niche(entity_id, niche_key, niche_status)
    if niche_status != "confirmed" or not niche_key:
        await db_service.quarantine_contractor_entity(
            entity_id, "niche_unconfirmed"
        )
        return "niche_unconfirmed"

    label = outbound_templates.NICHES.get(
        niche_key, {}
    ).get("label", "General Contractors")
    contact = await db_service.import_b2b_lead(
        email=entity.get("email") or "",
        company_name=entity.get("legal_name") or "",
        city=entity.get("city") or "",
        category=label,
        domain=entity.get("domain"),
        state=entity.get("state"),
        niche_key=niche_key,
        niche_status="confirmed",
        create_contact=True,
    )
    if not contact or not contact.get("id"):
        await db_service.quarantine_contractor_entity(entity_id, "bridge_failed")
        return "bridge_failed"

    await db_service.mark_contractor_bridged(
        entity_id, int(contact["id"]), contact.get("lead_id")
    )
    return "bridged"


async def bridge_ready_entities(city: str, limit: int = 50) -> dict:
    """Ponte para entidades `ready` antigas (ex.: anteriores ao scheduler)."""
    rows = await db_service.list_entities_for_bridge(city, limit)
    counts: dict[str, int] = {}
    for entity in rows:
        result = await bridge_entity(entity)
        counts[result] = counts.get(result, 0) + 1
    return {"city": city.upper(), "processed": len(rows), "outcomes": counts}

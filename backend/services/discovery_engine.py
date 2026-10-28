"""Orquestrador do motor de descoberta automatica integrado com a base de dados.

Gerencia o ciclo de vida da descoberta por lead:
  1. Filtra lixo/institucionais (`should_skip_discovery`).
  2. Consulta diretorios em lote ou heuristica local.
  3. Valida via SMTP RCPT ($0) ou EmailListVerify (fallback pago).
  4. Persiste em `company_directory`, `email_candidates` e `outbound_contacts`.
"""

from __future__ import annotations

import asyncio
import logging
import time

from ..config import settings
from .company_discovery import (
    CompanyDiscovery,
    registrable_domain,
)
from .lead_filter import should_skip_discovery

logger = logging.getLogger(__name__)


async def enrich_lead_email(db_service, lead: dict) -> dict:
    """Executa a descoberta e validacao de e-mail para um unico lead.

    Devolve um dict com o resultado e regista telemetria na BD.
    """
    lead_id = lead.get("id")
    owner_name = lead.get("owner_name") or ""
    city = lead.get("city") or "NYC"

    if should_skip_discovery(owner_name):
        return {"status": "skipped", "reason": "institutional_or_empty"}

    discovery = CompanyDiscovery()
    t0 = time.time()
    # `discover` faz DNS + HTTP + SMTP de forma sincrona: corre num thread para
    # nao bloquear o event loop do uvicorn (antes, um unico lead podia congelar
    # a API inteira durante 5-30s).
    res = await asyncio.to_thread(
        discovery.discover, lead, settings.DISCOVERY_PER_LEAD_TIMEOUT
    )
    elapsed = round(time.time() - t0, 3)

    domain = res.get("domain")
    validation = res.get("validation") or {}
    accepted = validation.get("accepted") or []
    catch_all = validation.get("catch_all")

    # Se a validacao SMTP gratuita nao encontrou e a chave ELV existir, usar fallback
    email_source = res.get("domain_source") or "heuristic"
    email_status = "unknown"
    final_email = ""

    if accepted:
        final_email = accepted[0]
        email_status = "catch_all" if catch_all else "valid"
    elif catch_all and domain:
        # Dominio catch-all: assume o padrao info@ ou contact@ com status catch_all
        final_email = f"info@{domain}"
        email_status = "catch_all"
    elif not domain and settings.EMAILLISTVERIFY_API_KEY:
        # Fallback pago EmailListVerify find_and_verify
        try:
            from .enrichment_emaillistverify import find_and_verify

            elv_res = await find_and_verify(
                owner_email=lead.get("owner_email"),
                company_name=owner_name,
                contact_name=None,
                city=city,
            )
            if elv_res.success and elv_res.email:
                final_email = elv_res.email
                email_status = elv_res.status
                email_source = "emaillistverify"
                domain = registrable_domain(final_email.split("@")[1])
        except Exception as exc:  # noqa: BLE001
            logger.warning("Falha no fallback ELV: %s", exc)

    if final_email and domain:
        # Upsert no outbound_contacts
        try:
            await db_service.upsert_outbound_contact(
                lead_id=lead_id,
                email=final_email,
                city=city,
                state=lead.get("state"),
                company_name=owner_name,
                contact_name=None,
                email_source=email_source,
                email_status=email_status,
                company_domain=domain,
            )
            logger.info(
                "Descoberta com sucesso: lead=%s company=%r email=%s source=%s status=%s (%.2fs)",
                lead_id, owner_name, final_email, email_source, email_status, elapsed,
            )
            return {
                "status": "success",
                "email": final_email,
                "domain": domain,
                "email_status": email_status,
                "email_source": email_source,
            }
        except Exception as exc:  # noqa: BLE001
            logger.error("Erro ao persistir contacto descoberto: %s", exc)
            return {"status": "error", "error": str(exc)}

    return {"status": "no_email_found", "elapsed_s": elapsed}

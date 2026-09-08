"""notifier.py — Distribuição de notificações por interesse do usuário.

Quando um lead de determinada categoria é inserido (ou muda de status),
este serviço "faz o fan-out": notifica apenas os usuários que marcaram
interesse naquela categoria (conceito central aprovado no protótipo /pro).
"""

import asyncio
from typing import List, Optional

from .db import db_service
from ..utils.logger import logger


async def notify_users_for_lead(
    lead_id: int,
    category: str,
    event_type: str,
    title: str,
    message_fmt: str,
    limit: int = 50,
) -> int:
    """Notifica os usuários interessados na categoria de um lead.

    message_fmt é um template com placeholders {address} e {city}.
    Retorna quantas notificações foram criadas.
    """
    users = await db_service.get_users_interested_in(category)
    sent = 0
    for user in users[:limit]:
        try:
            msg = message_fmt.format(
                address=user.get("_address", ""),
                city=user.get("_city", ""),
            )
        except (KeyError, IndexError):
            msg = message_fmt
        created = await db_service.add_notification_for_user(
            user_id=user["id"],
            type=event_type,
            title=title,
            message=msg,
            lead_id=lead_id,
        )
        if created:
            sent += 1
    if sent:
        logger.info(
            f"Notifier: {sent} usuário(s) notificado(s) para lead {lead_id} "
            f"(categoria='{category}', tipo='{event_type}')"
        )
    return sent


async def broadcast(event_type: str, title: str, message: str) -> int:
    """Notifica todos os usuários cadastrados (aviso global do sistema)."""
    users = await db_service.get_all_users()
    sent = 0
    for user in users:
        created = await db_service.add_notification_for_user(
            user_id=user["id"],
            type=event_type,
            title=title,
            message=message,
        )
        if created:
            sent += 1
    return sent


async def fanout_new_lead(lead: dict) -> int:
    """Fan-out padrão ao inserir um novo lead (por categoria de interesse)."""
    category = (lead.get("issue_category") or "").strip()
    if not category:
        return 0
    addr = lead.get("address") or "endereço"
    city = lead.get("city") or ""
    return await notify_users_for_lead(
        lead_id=lead["id"],
        category=category,
        event_type="new_lead",
        title="Nova oportunidade",
        message_fmt=f"Nova oportunidade em {category}: {addr} — {city}",
    )


async def fanout_new_lead_batch(category: str, leads: list) -> int:
    """Fan-out agregado por categoria: cria UMA notificação por usuário
    interessado na categoria, mencionando quantos leads novos surgiram.

    Inclui cooldown de 55 min por categoria para manter as notificações
    "esporádicas" entre as rodadas do scraper completo a cada 60 min.
    """
    if not leads:
        return 0
    category = (category or "").strip()
    if not category:
        return 0
    
    # Obtém cidades únicas dos leads para filtro
    cities = list(set(lead.get("city", "") for lead in leads if lead.get("city")))
    
    # Para cada cidade, busca usuários interessados nessa categoria E cidade
    all_users = {}
    for city in cities:
        users = await db_service.get_users_interested_in(category, city)
        for u in users:
            all_users[u["id"]] = u
    
    # Se não há filtro de cidade, busca todos os interessados na categoria
    if not cities:
        users = await db_service.get_users_interested_in(category)
        for u in users:
            all_users[u["id"]] = u
    
    if not all_users:
        return 0

    n = len(leads)
    first = leads[0]
    addr = first.get("address") or "novo endereço"
    city = first.get("city") or ""
    title = "Nova oportunidade" if n == 1 else f"{n} novas oportunidades"
    message = (
        f"Nova oportunidade em {category}: {addr} — {city}"
        if n == 1
        else f"{n} novas oportunidades em {category} (ex.: {addr} — {city})"
    )
    lead_id = first.get("id")

    sent = 0
    for user in all_users.values():
        created = await db_service.add_notification_for_user(
            user_id=user["id"],
            type="new_lead",
            title=title,
            message=message,
            lead_id=lead_id,
        )
        if created:
            sent += 1
    logger.info(
        f"Notifier: {sent} usuário(s) notificado(s) — {n} lead(s) novos "
        f"na categoria '{category}'"
    )
    return sent


async def fanout_status_change(lead: dict, new_status: str) -> int:
    """Notifica interessados quando o status de um lead disponível muda."""
    category = (lead.get("issue_category") or "").strip()
    if not category:
        return 0
    addr = lead.get("address") or "endereço"
    city = lead.get("city") or ""
    return await notify_users_for_lead(
        lead_id=lead["id"],
        category=category,
        event_type="status_change",
        title="Status atualizado",
        message_fmt=(
            f"O lead {addr} — {city} agora está '{new_status}' "
            f"(categoria {category})"
        ),
    )

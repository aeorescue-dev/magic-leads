"""notifier.py — Distribuição de notificações por interesse do usuário.

Quando um lead de determinada categoria é inserido (ou muda de status),
este serviço "faz o fan-out": notifica apenas os usuários que marcaram
interesse naquela categoria (conceito central aprovado no protótipo /pro).

Cap de 10 alertas new_lead/dia por usuário (in-app + push juntos).
Dedup: mesmo lead nunca gera 2 alertas para o mesmo usuário.
Digest: resumo diário para quem bateu no teto (não conta no teto).

Elegibilidade (fonte única de verdade): services.access.is_access_active().
Recorte de categoria: interesses marcados OU, sem nenhum interesse gravado,
todas as categorias (fallback inteligente — ver db.get_users_interested_in).

Dead Man's Switch: se leads foram inseridos mas NENHUM destinatário elegível
foi encontrado, isso é tratado como bloqueio de fluxo e escalado (log CRITICAL
+ auditoria). Cap diário atingido NÃO é bloqueio (há elegíveis).
"""

from collections import defaultdict
from dataclasses import dataclass

from ..utils.logger import logger
from .db import db_service

DAILY_ALERT_LIMIT = 10


@dataclass
class FanoutReport:
    """Resultado de um fan-out.

    - created: notificações in-app efetivamente criadas.
    - audience: nº de usuários ELEGÍVEIS encontrados (independente de cap/dedup).
    """

    created: int = 0
    audience: int = 0


async def guard_silent_fanout(
    inserted: int, notified: int, audience: int, context: dict
) -> bool:
    """Dead Man's Switch do despacho de alertas.

    Dispara log CRITICAL + alerta de auditoria (tabela system_alerts) SOMENTE
    quando leads foram inseridos (`inserted > 0`) mas o fan-out não encontrou
    NENHUM destinatário elegível (`audience == 0`) — cenário do bug de whitelist
    de status que silenciava o despacho.

    Um `notified == 0` com `audience > 0` é considerado SAUDÁVEL: significa que
    os elegíveis já bateram no cap diário (ou os leads já haviam sido notificados).
    """
    if inserted > 0 and audience == 0:
        msg = (
            "BLOQUEIO DE FLUXO DE NOTIFICAÇÕES: "
            f"{inserted} lead(s) inserido(s) mas nenhum destinatário elegível "
            f"encontrado ({notified} notificação(ões) criada(s)). "
            "Possível divergência de status de acesso, interesses ou cities_filter."
        )
        logger.critical(msg)
        try:
            await db_service.record_system_alert(
                level="critical",
                code="NOTIFIER_SILENT_FAILURE",
                message=msg,
                context=context,
            )
        except Exception as e:  # nunca deixar o watchdog derrubar o run
            logger.error(f"Falha ao registrar alerta crítico de fanout: {e}")
        return False
    return True


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


async def fanout_new_lead_batch(category: str, leads: list) -> FanoutReport:
    """Fan-out por lead: cria UMA notificação por lead × usuário, com:
    - Dedup: (user_id, lead_id) já notificado → skip
    - Cap: user já atingiu DAILY_ALERT_LIMIT alertas new_lead hoje → skip
    - Digest: skippeados acumulam em upsert_daily_digest (não conta no teto)
    - Push: enviado apenas a quem recebeu in-app (corresponde city + cap)

    Retorna FanoutReport(created=..., audience=...) para o Dead Man's Switch
    distinguir "cap atingido" (saudável) de "nenhum elegível" (bloqueio).
    """
    from .push_service import push_service

    if not leads:
        return FanoutReport()
    category = (category or "").strip()
    if not category:
        return FanoutReport()

    lead_ids = [ld.get("id") for ld in leads if ld.get("id")]
    if not lead_ids:
        return FanoutReport()

    # --- 1) Busca em lote: contagens de hoje e dedup existente ---
    counts_rows = await db_service.get_new_lead_alert_counts_today()
    used_today: dict = {r["user_id"]: r["n"] for r in counts_rows}

    alerted_rows = await db_service.get_alerted_pairs_for_leads(lead_ids)
    already_notified: set = {(r["user_id"], r["lead_id"]) for r in alerted_rows}

    # --- 2) Cache de usuários por (category, city) ---
    users_cache: dict = {}

    async def _users_for_city(city: str):
        key = city or ""
        if key not in users_cache:
            users_cache[key] = await db_service.get_users_interested_in(
                category, city or None
            )
        return users_cache[key]

    # --- 3) Itera leads → usuários → dedup → cap → notifica ---
    skipped: dict = defaultdict(int)  # user_id → skipped count
    push_queue: dict = defaultdict(list)  # user_id → [lead, ...]
    sent = 0

    for lead in leads:
        lid = lead.get("id")
        if not lid:
            continue
        city = (lead.get("city") or "").strip()
        addr = lead.get("address") or "endereço"
        users = await _users_for_city(city)
        for u in users:
            uid = u["id"]
            # Dedup
            if (uid, lid) in already_notified:
                continue
            # Cap
            if used_today.get(uid, 0) >= DAILY_ALERT_LIMIT:
                skipped[uid] += 1
                continue
            # Notifica in-app
            msg = f"Nova oportunidade em {category}: {addr} — {city}"
            created = await db_service.add_notification_for_user(
                user_id=uid,
                type="new_lead",
                title="Nova oportunidade",
                message=msg,
                lead_id=lid,
            )
            if created:
                sent += 1
                used_today[uid] = used_today.get(uid, 0) + 1
                push_queue[uid].append(lead)

    # --- 4) Digest para usuários que atingiram o teto ---
    for uid, cnt in skipped.items():
        if cnt > 0:
            await db_service.upsert_daily_digest(uid, cnt)

    # --- 5) Push in-app-notificados (respeita city + cap automaticamente) ---
    for uid, push_leads in push_queue.items():
        for lead in push_leads:
            lid = lead.get("id")
            addr = lead.get("address") or "Endereço não informado"
            city = lead.get("city") or ""
            try:
                await push_service.send_to_user(uid, {
                    "title": "Nova oportunidade",
                    "body": f"{category}: {addr} — {city}",
                    "icon": "https://magicleads-oficial.vercel.app/icons/magicleads-brand.svg",
                    "badge": "https://magicleads-oficial.vercel.app/icons/magicleads-brand.svg",
                    "tag": f"new_lead_{lid}",
                    "leadId": lid,
                    "url": f"/dashboard?lead={lid}",
                    "category": category,
                    "timestamp": lead.get("date_reported"),
                })
            except Exception as e:
                logger.error(f"Push error user={uid} lead={lid}: {e}")

    # --- 6) Push digest para quem atingiu o teto ---
    from datetime import date
    today_tag = date.today().isoformat()
    for uid, cnt in skipped.items():
        if cnt > 0:
            try:
                await push_service.send_to_user(uid, {
                    "title": "Resumo diário de alertas",
                    "body": (
                        f"Mais {cnt} ofertas chegaram hoje "
                        f"— o limite de 10 renova amanhã."
                    ),
                    "icon": "https://magicleads-oficial.vercel.app/icons/magicleads-brand.svg",
                    "badge": "https://magicleads-oficial.vercel.app/icons/magicleads-brand.svg",
                    "tag": f"digest_{today_tag}",
                    "url": "/dashboard",
                })
            except Exception as e:
                logger.error(f"Push digest error user={uid}: {e}")

    # Audiência elegível = usuários distintos encontrados (antes de cap/dedup).
    audience = len({u["id"] for users in users_cache.values() for u in users})

    logger.info(
        f"Notifier: {sent} notificações criadas, "
        f"{len(skipped)} usuário(s) no teto, "
        f"{audience} elegível(is), "
        f"{len(leads)} leads na categoria '{category}'"
    )
    return FanoutReport(created=sent, audience=audience)


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

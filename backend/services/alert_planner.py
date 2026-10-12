"""alert_planner.py — planeador central de alertas.

Transforma os leads recém-inseridos num plano de despacho justo por utilizador:

  * teto diário GLOBAL (settings.PUSH_DAILY_LIMIT, default 6) por utilizador;
  * orçamento COMBINADO: 1 alerta = 1 in-app + push (se elegível) e consome 1
    unidade; `push_enabled=false` → só in-app, mas consome na mesma;
  * distribuição fair-equal por especialidade (round-robin entre as categorias
    em que o utilizador é elegível no run);
  * rotação persistida (users.alert_rotation_cursor) para que a categoria e o
    lead que ganham a rara vaga não sejam sempre os mesmos entre runs;
  * digest diário para o excedente (NÃO conta no teto; push adicional).

Entrypoint: `plan_and_dispatch(leads)`.
"""
import asyncio
import json
import random
from dataclasses import dataclass

from ..config import settings
from ..utils.logger import logger
from .db import _OPEN_STATUSES, db_service
from .lead_rules import is_institutional_name
from .translations import DEFAULT_LOCALE, normalize, render, tr


@dataclass
class PlanReport:
    """Resultado de um plano de despacho.

    - candidates: leads despacháveis após o filtro de qualidade (institucional /
      sem categoria fora). É o "havia conteúdo para alertar" que o Dead Man's
      Switch usa — distingue "nada a despachar" (0) de "candidatos sem
      elegíveis".
    - audience: utilizadores ELEGÍVEIS encontrados (independente de cap/dedup).
    - city_filtered: a audiência ficou a 0 apesar de haver utilizadores
      interessados, ou seja, o `cities_filter` de todos eles é que excluiu os
      leads. Ruído de configuração, não bloqueio de fluxo.
    """

    created: int = 0       # notificações in-app criadas
    audience: int = 0      # utilizadores elegíveis encontrados (pré-cap/dedup)
    digest: int = 0        # utilizadores com digest (excedente)
    pushed: int = 0        # pushes aceites pelo serviço
    candidates: int = 0    # leads despacháveis (filtro de qualidade aplicado)
    city_filtered: bool = False  # audiência zerada apenas pelo cities_filter


def _city_allows(user: dict, city: str) -> bool:
    """Aplica o cities_filter do utilizador (sem filtro = todas as cidades)."""
    cf = user.get("cities_filter")
    if not cf or not city:
        return True
    try:
        allowed = json.loads(cf)
    except (ValueError, TypeError):
        return True
    return not allowed or city in allowed


def _order_leads(leads: list) -> list:
    """Frescura (date_reported DESC) e, como desempate, chamado aberto primeiro."""
    epoch = ""

    def key(ld: dict):
        status = (ld.get("case_status") or ld.get("status") or "").strip().lower()
        is_open = 1 if status in _OPEN_STATUSES else 0
        return (is_open, str(ld.get("date_reported") or epoch))

    return sorted(leads, key=key, reverse=True)


def select_fair(cat_map: dict, remaining: int, cursor: int) -> tuple:
    """Seleciona até `remaining` leads, fair-equal por categoria.

    - categorias ordenadas de forma rotativa por `cursor`;
    - dentro de cada categoria: ordena por frescura/estado e aplica um offset
      rotativo por `cursor` (alterna quais leads apanham a vaga entre runs);
    - round-robin entre categorias até esgotar o orçamento.

    Devolve (selected=[(category, lead), ...], overflow=int).
    """
    total = sum(len(v) for v in cat_map.values())
    if remaining <= 0 or total == 0:
        return [], total

    cats = sorted(cat_map.keys())
    off = cursor % len(cats)
    rotated = cats[off:] + cats[:off]

    ordered: dict = {}
    for c in rotated:
        lst = _order_leads(cat_map[c])
        n = len(lst)
        if n:
            k = cursor % n
            lst = lst[k:] + lst[:k]
        ordered[c] = lst

    selected: list = []
    idx = {c: 0 for c in rotated}
    while len(selected) < remaining:
        progressed = False
        for c in rotated:
            if idx[c] < len(ordered[c]):
                selected.append((c, ordered[c][idx[c]]))
                idx[c] += 1
                progressed = True
                if len(selected) >= remaining:
                    break
        if not progressed:
            break
    return selected, total - len(selected)


async def _create_inapp(uid: int, lead_id: int, params: dict, title: str, message: str):
    """Cria a notificação in-app com retry exponencial e fallback para a DLQ."""
    for attempt in range(4):
        try:
            return await db_service.add_notification_for_user(
                user_id=uid,
                type="new_lead",
                title=title,
                message=message,
                lead_id=lead_id,
                msg_key="new_lead",
                msg_params=params,
            )
        except Exception as e:
            if attempt < 3:
                wait_time = min(0.5 * (2 ** attempt) + random.uniform(0, 0.2), 5.0)
                logger.warning(
                    f"Notificação in-app user={uid} lead={lead_id} "
                    f"(tentativa {attempt + 1}/4): {e}. Retry em {wait_time:.1f}s"
                )
                await asyncio.sleep(wait_time)
                continue
            logger.error(
                f"Notificação in-app user={uid} lead={lead_id} falhou após 4 tentativas: {e}"
            )
            try:
                await db_service._save_notification_dlq(
                    uid, "new_lead", title, message, lead_id, str(e)
                )
            except Exception:
                pass
            return None
    return None


async def plan_and_dispatch(leads: list) -> PlanReport:
    """Planeia e executa o despacho de alertas para os leads recém-inseridos."""
    from .push_service import push_service

    if not leads:
        return PlanReport()

    # 1) Agrupar por categoria + filtro de qualidade (institucional fora: sem
    #    telefone de pessoa, nunca compensa gastar uma vaga escassa do teto).
    by_cat: dict = {}
    for ld in leads:
        if not ld.get("id"):
            continue
        if is_institutional_name(ld.get("owner_name")):
            continue
        cat = (ld.get("issue_category") or "").strip()
        if not cat:
            continue
        by_cat.setdefault(cat, []).append(ld)

    if not by_cat:
        return PlanReport()

    lead_ids = [ld["id"] for v in by_cat.values() for ld in v]

    # 2) Dados em lote.
    usage = await db_service.get_alert_usage_today()
    alerted = await db_service.get_alerted_pairs_for_leads(lead_ids)
    already = {(r["user_id"], r["lead_id"]) for r in alerted}
    limit = settings.PUSH_DAILY_LIMIT

    # 3) Candidatos por utilizador (filtro de cidade aplicado por lead).
    audience: set = set()
    per_user: dict = {}
    user_locale: dict = {}
    saw_users = False  # houve utilizadores interessados (antes do filtro de cidade)?
    for cat, cat_leads in by_cat.items():
        users = await db_service.get_users_interested_in(cat)
        if users:
            saw_users = True
        for u in users:
            uid = u["id"]
            for ld in cat_leads:
                if not _city_allows(u, ld.get("city") or ""):
                    continue
                audience.add(uid)
                if (uid, ld["id"]) in already:
                    continue
                per_user.setdefault(uid, {}).setdefault(cat, []).append(ld)
                user_locale[uid] = normalize(u.get("locale"))

    # Audiência vazia só é bloqueio de fluxo quando NÃO havia ninguém
    # interessado. Se havia e o cities_filter de todos excluiu os leads, é ruído
    # de configuração (city_filtered) e não deve disparar o Dead Man's Switch.
    city_filtered = len(audience) == 0 and saw_users
    report = PlanReport(
        audience=len(audience),
        candidates=len(lead_ids),
        city_filtered=city_filtered,
    )
    push_jobs: list = []   # (uid, lead, cat)
    digest_jobs: list = []  # (uid, count)

    # 4) Seleção fair-equal + criação in-app (orçamento combinado).
    for uid, cat_map in per_user.items():
        used = sum(usage.get(uid, {}).values())
        remaining = max(0, limit - used)
        cursor = await db_service.get_alert_rotation_cursor(uid)

        selected, overflow = select_fair(cat_map, remaining, cursor)

        for cat, ld in selected:
            params = {
                "category": cat,
                "addr": ld.get("address") or "",
                "city": ld.get("city") or "",
            }
            created = await _create_inapp(
                uid, ld["id"], params,
                tr("new_lead.title", DEFAULT_LOCALE),
                tr("new_lead.main_msg", DEFAULT_LOCALE, **params),
            )
            if created:
                await db_service.increment_alert_usage(uid, cat)
                report.created += 1
                push_jobs.append((uid, ld, cat))

        if overflow > 0:
            digest_jobs.append((uid, overflow))

        # Avança a rotação para o próximo run (alterna categoria/lead).
        await db_service.advance_alert_rotation_cursor(uid, 1)

    # 4b) Digest do excedente (não conta no teto).
    for uid, count in digest_jobs:
        try:
            await db_service.upsert_daily_digest(uid, count)
            report.digest += 1
        except Exception as e:
            logger.error(f"Digest diário user={uid} falhou: {e}")

    # 5) Push das notificações in-app criadas (orçamento combinado: não soma).
    for uid, lead, cat in push_jobs:
        try:
            if not await db_service.is_push_enabled(uid):
                continue
            locale = user_locale.get(uid)
            params = {
                "category": cat,
                "addr": lead.get("address") or "",
                "city": lead.get("city") or "",
            }
            rendered = render("new_lead", locale, **params) or {}
            sent = await push_service.send_to_user(
                uid,
                {
                    "title": rendered.get("title") or tr("new_lead.title", locale),
                    "body": rendered.get("message")
                    or tr("new_lead.main_msg", locale, **params),
                    "icon": "https://magicleads-oficial.vercel.app/icons/magicleads-brand.svg",
                    "badge": "https://magicleads-oficial.vercel.app/icons/magicleads-brand.svg",
                    "tag": f"new_lead_{lead.get('id')}",
                    "leadId": lead.get("id"),
                    "url": f"/dashboard?lead={lead.get('id')}",
                    "category": cat,
                    "timestamp": lead.get("date_reported"),
                },
                "lead_alert",
            )
            if sent:
                report.pushed += 1
        except Exception as e:
            logger.error(f"Push error user={uid} lead={lead.get('id')}: {e}")

    # 6) Push do digest (adicional, nunca conta para o teto).
    for uid, count in digest_jobs:
        try:
            if not await db_service.is_push_enabled(uid):
                continue
            locale = user_locale.get(uid)
            rendered = render("digest", locale, n=count, limit=limit) or {}
            await push_service.send_to_user(
                uid,
                {
                    "title": rendered.get("title") or tr("digest.title", locale),
                    "body": rendered.get("message")
                    or tr("digest.main_msg", locale, n=count, limit=limit),
                    "icon": "https://magicleads-oficial.vercel.app/icons/magicleads-brand.svg",
                    "badge": "https://magicleads-oficial.vercel.app/icons/magicleads-brand.svg",
                    "tag": f"digest_{DEFAULT_LOCALE}",
                    "url": "/dashboard",
                },
                "digest",
            )
        except Exception as e:
            logger.error(f"Push digest user={uid} falhou: {e}")

    logger.info(
        f"Alert Planner: {report.created} in-app, {report.digest} digest, "
        f"{report.pushed} push, audiência {report.audience} "
        f"({report.candidates} candidato(s), teto {limit})"
    )
    return report

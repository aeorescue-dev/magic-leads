"""alert_planner.py — planeador central de alertas (Alert Engine v2).

Transforma os leads recém-inseridos num plano de despacho justo por utilizador:

  * gate semântico (P0-B): `signal_type` permitido, `signal_status != closed`,
    não institucional, morada resolvível, fresco (≤48 h) ou reincidente;
  * interesses ESTRITOS: sem categoria escolhida não há alerta individual
    (`strict=True` em `get_users_interested_in`);
  * teto diário global (`PUSH_DAILY_LIMIT`, default 6) por utilizador, com
    orçamento combinado in-app + push;
  * distribuição fair-equal por especialidade (round-robin entre categorias);
  * ordenação inteligente dentro da categoria: sinal (legal > obra > 311),
    estado aberto, frescura e — por último — distância. A distância é apenas
    informativa/ordenação: NUNCA filtra nem bloqueia um lead da mesma cidade;
  * quiet hours 21:00–08:00 America/New_York, com exceção de
    `legal_obligation`; fora da janela a notificação in-app é criada e o push
    é suprimido;
  * digest diário do excedente (não conta no teto).

Entrypoint: `plan_and_dispatch(leads)`.
"""
import asyncio
import json
import math
import random
from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from ..config import settings
from ..utils.logger import logger
from .db import db_service
from .lead_rules import (
    address_is_resolvable,
    derive_signal,
    get_owner_class,
    is_institutional_name,
)
from .push_click import sign_click
from .translations import (
    alert_confidence_label,
    alert_why_now,
    category_label,
    normalize,
    render,
    signal_label,
    tr,
)

SIGNAL_RANK = {
    "legal_obligation": 0,
    "authorized_work": 1,
    "open_request": 2,
}
SIGNAL_EMOJI = {
    "legal_obligation": "⚖️",
    "authorized_work": "🏗️",
    "open_request": "🔧",
}
_PUSH_ICON = "https://magicleads-oficial.vercel.app/icons/magicleads-brand.svg"


@dataclass
class PlanReport:
    """Resultado de um plano de despacho.

    - candidates: leads despacháveis depois do gate semântico. Distingue
      "nada a despachar" (0) de "candidatos sem elegíveis" para o Dead Man's
      Switch.
    - audience: utilizadores ELEGÍVEIS encontrados (pré-cap/dedup).
    - quiet_suppressed: pushes suprimidos pelo silêncio noturno (o in-app foi
      criado na mesma).
    """

    created: int = 0       # notificações in-app criadas
    audience: int = 0      # utilizadores elegíveis encontrados (pré-cap/dedup)
    digest: int = 0        # utilizadores com digest (excedente)
    pushed: int = 0        # pushes aceites pelo serviço
    candidates: int = 0    # leads despacháveis (gate semântico)
    city_filtered: bool = False  # audiência zerada apenas pelo cities_filter
    quiet_suppressed: int = 0    # pushes adiados pelo silêncio
    gap_suppressed: int = 0      # pushes adiados pelo min-gap
    batched: int = 0             # pushes agrupados (1 por run)


# ---------------------------------------------------------------------------
# Helpers puros
# ---------------------------------------------------------------------------

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(value) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    raw = str(value).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        try:
            dt = datetime.strptime(raw[:19], "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _age_hours(lead: dict, now: datetime) -> float:
    dt = _parse_dt(lead.get("date_reported"))
    if not dt:
        return 0.0
    # Datas futuras (fonte com erro de data) contam como "agora": nunca
    # penalizam o lead nem o excluem.
    return max(0.0, (now - dt).total_seconds() / 3600.0)


def _signal_of(lead: dict) -> tuple[str, str]:
    st = (lead.get("signal_type") or "").strip()
    ss = (lead.get("signal_status") or "").strip()
    derived_st, derived_ss = derive_signal(
        lead.get("source_type"), lead.get("case_status")
    )
    if not st:
        st = derived_st or "open_request"
    # `signal_status` tem DEFAULT 'unknown' na BD: quando a linha ainda nao
    # foi classificada, o case_status manda (ex.: 311 "Completed" = closed).
    # Um 'unknown' real da fonte continua unknown se o case_status tambem for.
    if (not ss or ss == "unknown") and derived_ss and derived_ss != "unknown":
        ss = derived_ss
    return st, ss or "unknown"


def _allowed_signals() -> set[str]:
    raw = str(getattr(settings, "PUSH_ALERT_SIGNALS", "") or "")
    return {part.strip() for part in raw.split(",") if part.strip()}


def _is_alertable(lead: dict, now: datetime) -> tuple[bool, str, str]:
    """Gate semântico. Devolve (elegível, signal_type, signal_status)."""
    signal, status = _signal_of(lead)
    if signal not in _allowed_signals():
        return False, signal, status
    if status == "closed":
        return False, signal, status
    if is_institutional_name(lead.get("owner_name")):
        return False, signal, status
    if not address_is_resolvable(lead.get("address")):
        return False, signal, status
    repeat = int(lead.get("repeat_365") or 0)
    max_age = float(getattr(settings, "PUSH_MAX_AGE_HOURS", 48) or 48)
    if _age_hours(lead, now) > max_age and repeat < 2:
        return False, signal, status
    return True, signal, status


def _parse_hhmm(value: str) -> tuple[int, int] | None:
    try:
        hh, mm = str(value).strip().split(":")
        hh_i, mm_i = int(hh), int(mm)
        if 0 <= hh_i <= 23 and 0 <= mm_i <= 59:
            return hh_i, mm_i
    except (ValueError, AttributeError):
        pass
    return None


def _is_quiet_hours(now: datetime | None = None) -> bool:
    """True dentro da janela de silêncio local (default 21:00–08:00 NY)."""
    start = _parse_hhmm(getattr(settings, "PUSH_QUIET_START", "21:00"))
    end = _parse_hhmm(getattr(settings, "PUSH_QUIET_END", "08:00"))
    if not start or not end or start == end:
        return False
    try:
        tz = ZoneInfo(getattr(settings, "PUSH_QUIET_TZ", "America/New_York"))
    except Exception:  # tzdata ausente: melhor não silenciar do que silenciar errado
        return False
    local = (now or _now_utc()).astimezone(tz)
    minutes = local.hour * 60 + local.minute
    start_m = start[0] * 60 + start[1]
    end_m = end[0] * 60 + end[1]
    if start_m < end_m:
        return start_m <= minutes < end_m
    return minutes >= start_m or minutes < end_m


def _distance_miles(base: tuple[float, float] | None, lead: dict) -> float | None:
    """Haversine local. `None` quando falta base ou coordenadas."""
    if not base:
        return None
    try:
        lat1, lng1 = float(base[0]), float(base[1])
        lat2, lng2 = float(lead.get("lat")), float(lead.get("lng"))
    except (TypeError, ValueError):
        return None
    if lat1 is None or lng1 is None:
        return None
    r = 3958.8  # milhas
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def _rank(lead: dict, now: datetime, base: tuple[float, float] | None) -> tuple:
    """Ordenação: sinal > estado > frescura > distância.

    A distância é o último critério e nunca remove ninguém: um lead a 28 mi
    dentro da mesma cidade continua elegível.
    """
    signal, status = _signal_of(lead)
    signal_rank = SIGNAL_RANK.get(signal, 3)
    closed_rank = 1 if status == "closed" else 0
    age = _age_hours(lead, now)
    dist = _distance_miles(base, lead)
    return (signal_rank, closed_rank, age, dist if dist is not None else float("inf"))


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


def select_fair(
    cat_map: dict,
    remaining: int,
    cursor: int,
    base: tuple[float, float] | None = None,
    now: datetime | None = None,
) -> tuple:
    """Seleciona até `remaining` leads, fair-equal por categoria.

    - categorias ordenadas de forma rotativa por `cursor` (justiça entre nichos);
    - dentro de cada categoria: ranking inteligente (sinal, frescura, distância)
      sem offset aleatório — os melhores ganham a vaga;
    - round-robin entre categorias até esgotar o orçamento.
    """
    total = sum(len(v) for v in cat_map.values())
    if remaining <= 0 or total == 0:
        return [], total

    now = now or _now_utc()
    cats = sorted(cat_map.keys())
    off = cursor % len(cats) if cats else 0
    rotated = cats[off:] + cats[:off]

    ordered: dict = {
        c: sorted(cat_map[c], key=lambda ld: _rank(ld, now, base)) for c in rotated
    }

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


def _fmt_miles(distance: float, locale: str | None) -> str:
    txt = f"{distance:.1f}"
    if normalize(locale) in ("pt", "es"):
        txt = txt.replace(".", ",")
    return txt


async def _confidence_pct(lead: dict, cache: dict) -> int | None:
    """Percentagem real de sucesso (≥30 amostras), por cidade→classe."""
    city = (lead.get("city") or "").strip()
    owner_class = get_owner_class(lead.get("owner_name"))
    key = (city.upper(), owner_class)
    if key in cache:
        return cache[key]
    pct = None
    try:
        for scope in (city or None, None):
            stats = await db_service.get_phone_success_stats(scope, owner_class)
            samples = int(stats.get("samples") or 0)
            if samples >= 30:
                pct = round(int(stats.get("successes") or 0) * 100 / samples)
                break
    except Exception as e:  # nunca bloquear um alerta por falta de estatística
        logger.debug("[ALERT] estatistica de telefone falhou: %s", e)
    cache[key] = pct
    return pct


def _click_fields(notification_id: int | None) -> dict:
    if not notification_id:
        return {}
    try:
        nid = int(notification_id)
    except (TypeError, ValueError):
        return {}
    sig = sign_click(nid)
    return {"nid": nid, "sig": sig}


def _build_push_payload(
    lead: dict,
    category: str,
    signal: str,
    locale: str | None,
    distance_mi: float | None,
    show_distance: bool,
    confidence_pct: int | None,
    show_address: bool,
    notification_id: int | None = None,
) -> dict:
    loc = normalize(locale)
    cat_label = category_label(category, loc)
    sig_label = signal_label(signal, loc)
    emoji = SIGNAL_EMOJI.get(signal, "")
    title = f"{emoji} {sig_label} · {cat_label}".strip(" ·")
    city = (lead.get("city") or "").strip()
    if city and len(title) + len(city) + 3 <= 60:
        title = f"{title} — {city}"

    parts: list[str] = []
    if show_address and lead.get("address"):
        parts.append(str(lead["address"]))
    else:
        parts.append(
            {
                "pt": "Nova oportunidade perto de si",
                "en": "New opportunity near you",
                "es": "Nueva oportunidad cerca de ti",
            }[loc]
        )
    if show_distance and distance_mi is not None:
        miles = _fmt_miles(distance_mi, loc)
        parts.append(
            {"pt": f"a {miles} mi", "en": f"{miles} mi away", "es": f"a {miles} mi"}[loc]
        )
    why = alert_why_now(
        signal,
        loc,
        oldest_open_days=lead.get("oldest_open_days"),
        repeat_365=int(lead.get("repeat_365") or 0),
    )
    if why:
        parts.append(why)
    parts.append(
        alert_confidence_label(
            loc,
            phone_verified=bool(lead.get("phone_verified")),
            success_pct=confidence_pct,
        )
    )

    occurrence = str(lead.get("external_id") or "")
    tag = f"occ_{lead.get('id')}_{occurrence}"[:64]
    try:
        stamp = int((_parse_dt(lead.get("date_reported")) or _now_utc()).timestamp() * 1000)
    except (OverflowError, ValueError):
        stamp = None

    click = _click_fields(notification_id)
    url = f"/dashboard?lead={lead.get('id')}&occ={occurrence}&src=push"
    if click:
        url += f"&nid={click['nid']}&sig={click['sig']}"

    payload = {
        "title": title,
        "body": " · ".join(parts),
        "icon": _PUSH_ICON,
        "badge": _PUSH_ICON,
        "tag": tag,
        "renotify": True,
        "silent": False,
        "leadId": lead.get("id"),
        "occurrence": occurrence,
        "signalType": signal,
        "category": category,
        "url": url,
        "actions": [
            {
                "action": "open",
                "title": {"pt": "Ver lead", "en": "View lead", "es": "Ver lead"}[loc],
            },
            {
                "action": "dismiss",
                "title": {"pt": "Dispensar", "en": "Dismiss", "es": "Descartar"}[loc],
            },
        ],
        "vibrate": [180, 90, 180, 90, 260] if signal == "legal_obligation" else [120, 80, 120],
        "requireInteraction": signal == "legal_obligation",
    }
    payload.update(click)
    if stamp:
        payload["timestamp"] = stamp
    return payload


def _build_batch_payload(
    jobs: list[tuple[dict, str]],
    locale: str | None,
    distances: dict[int, float] | None,
    show_distance: bool,
    notification_id: int | None = None,
) -> dict:
    """Um unico push para varios leads do mesmo run (coalescencia B1).

    O in-app continua a listar cada lead; o push e' o resumo acionavel.
    """
    loc = normalize(locale)
    n = len(jobs)
    signals = [_signal_of(lead)[0] for lead, _cat in jobs]
    has_legal = "legal_obligation" in signals
    if all(s == "legal_obligation" for s in signals):
        emoji = "⚖️"
    elif all(s == "authorized_work" for s in signals):
        emoji = "🏗️"
    elif all(s == "open_request" for s in signals):
        emoji = "🔧"
    else:
        emoji = "📋"

    title = (
        {"pt": f"{emoji} {n} novas oportunidades",
         "en": f"{emoji} {n} new opportunities",
         "es": f"{emoji} {n} nuevas oportunidades"}[loc]
    )
    cities = {(lead.get("city") or "").strip() for lead, _cat in jobs if lead.get("city")}
    if len(cities) == 1 and len(title) + len(next(iter(cities))) + 3 <= 60:
        title = f"{title} — {next(iter(cities))}"

    counts = {
        "legal_obligation": signals.count("legal_obligation"),
        "authorized_work": signals.count("authorized_work"),
        "open_request": signals.count("open_request"),
    }
    parts: list[str] = []
    if counts["legal_obligation"]:
        c = counts["legal_obligation"]
        parts.append(
            {
                "pt": f"{c} obrigação legal" if c == 1 else f"{c} obrigações legais",
                "en": f"{c} legal obligation" if c == 1 else f"{c} legal obligations",
                "es": f"{c} obligación legal" if c == 1 else f"{c} obligaciones legales",
            }[loc]
        )
    if counts["authorized_work"]:
        c = counts["authorized_work"]
        parts.append(
            {
                "pt": f"{c} obra autorizada" if c == 1 else f"{c} obras autorizadas",
                "en": f"{c} authorized work",
                "es": f"{c} obra autorizada" if c == 1 else f"{c} obras autorizadas",
            }[loc]
        )
    if counts["open_request"]:
        c = counts["open_request"]
        parts.append(
            {
                "pt": f"{c} chamado" if c == 1 else f"{c} chamados",
                "en": f"{c} request" if c == 1 else f"{c} requests",
                "es": f"{c} solicitud" if c == 1 else f"{c} solicitudes",
            }[loc]
        )

    if show_distance and distances:
        nearest = min(distances.values())
        miles = _fmt_miles(nearest, loc)
        parts.append(
            {"pt": f"a mais próxima a {miles} mi",
             "en": f"nearest {miles} mi away",
             "es": f"la más cercana a {miles} mi"}[loc]
        )
    parts.append(
        {"pt": "telefones sob consulta",
         "en": "phones on request",
         "es": "teléfonos bajo consulta"}[loc]
    )

    click = _click_fields(notification_id)
    url = "/dashboard?src=push&batch=1"
    if click:
        url += f"&nid={click['nid']}&sig={click['sig']}"

    payload = {
        "title": title,
        "body": " · ".join(parts),
        "icon": _PUSH_ICON,
        "badge": _PUSH_ICON,
        "tag": f"batch_{notification_id or n}",
        "renotify": True,
        "silent": False,
        "signalType": "legal_obligation" if has_legal else "batch",
        "batch": n,
        "url": url,
        "actions": [
            {
                "action": "open",
                "title": {"pt": "Ver oportunidades", "en": "View opportunities", "es": "Ver oportunidades"}[loc],
            },
            {
                "action": "dismiss",
                "title": {"pt": "Dispensar", "en": "Dismiss", "es": "Descartar"}[loc],
            },
        ],
        "vibrate": [180, 90, 180, 90, 260] if has_legal else [120, 80, 120],
        "requireInteraction": has_legal,
        "timestamp": int(_now_utc().timestamp() * 1000),
    }
    payload.update(click)
    return payload


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

    lead_ids = [int(ld["id"]) for ld in leads if ld.get("id")]
    if not lead_ids:
        return PlanReport()

    # 1) Contexto completo (P0-B + reincidência). O dict do insert é anterior
    #    ao enriquecimento e não traz signal_* nem owner_phone.
    context = await db_service.get_leads_for_alert(lead_ids)
    now = _now_utc()

    by_cat: dict = {}
    for ld in context:
        ok, _signal, _status = _is_alertable(ld, now)
        if not ok:
            continue
        cat = (ld.get("issue_category") or "").strip()
        if not cat:
            continue
        by_cat.setdefault(cat, []).append(ld)

    if not by_cat:
        return PlanReport()

    dispatchable_ids = [ld["id"] for v in by_cat.values() for ld in v]

    # 2) Dados em lote.
    usage = await db_service.get_alert_usage_today()
    alerted = await db_service.get_alerted_pairs_for_leads(dispatchable_ids)
    already = {(r["user_id"], r["lead_id"]) for r in alerted}
    limit = settings.PUSH_DAILY_LIMIT
    quiet = _is_quiet_hours(now)

    # 3) Audiência ESTRITA (sem interesses = sem alerta individual).
    audience: set = set()
    per_user: dict = {}
    user_locale: dict = {}
    user_base: dict = {}
    user_base_source: dict = {}
    user_show_address: dict = {}
    user_gap: dict = {}
    saw_users = False
    for cat, cat_leads in by_cat.items():
        users = await db_service.get_users_interested_in(cat, strict=True)
        if users:
            saw_users = True
        for u in users:
            uid = u["id"]
            base = None
            if u.get("base_lat") is not None and u.get("base_lng") is not None:
                base = (float(u["base_lat"]), float(u["base_lng"]))
            for ld in cat_leads:
                if not _city_allows(u, ld.get("city") or ""):
                    continue
                audience.add(uid)
                if (uid, ld["id"]) in already:
                    continue
                per_user.setdefault(uid, {}).setdefault(cat, []).append(ld)
                user_locale[uid] = normalize(u.get("locale"))
                user_base[uid] = base
                user_base_source[uid] = (u.get("base_source") or "").strip().lower()
                user_show_address[uid] = bool(u.get("show_address_in_push", 1))
                gap = u.get("push_min_gap_min")
                user_gap[uid] = 30 if gap is None else int(gap)

    city_filtered = len(audience) == 0 and saw_users
    report = PlanReport(
        audience=len(audience),
        candidates=len(dispatchable_ids),
        city_filtered=city_filtered,
    )

    # Min-gap: tem de ser lido ANTES de criar os in-app deste run, senao o
    # proprio alerta acabado de criar contava como "ultimo alerta".
    last_alerts = await db_service.get_last_alert_times(list(per_user.keys()))

    push_jobs: dict = {}
    digest_jobs: list = []
    confidence_cache: dict = {}

    # 4) Seleção + in-app (orçamento combinado).
    for uid, cat_map in per_user.items():
        used = sum(usage.get(uid, {}).values())
        remaining = max(0, limit - used)
        cursor = await db_service.get_alert_rotation_cursor(uid)

        selected, overflow = select_fair(
            cat_map, remaining, cursor, base=user_base.get(uid), now=now
        )

        for cat, ld in selected:
            locale = user_locale.get(uid)
            params = {
                "category": category_label(cat, locale),
                "addr": ld.get("address") or "",
                "city": ld.get("city") or "",
            }
            created = await _create_inapp(
                uid,
                ld["id"],
                params,
                tr("new_lead.title", locale),
                tr("new_lead.main_msg", locale, **params),
            )
            if created:
                await db_service.increment_alert_usage(uid, cat)
                report.created += 1
                push_jobs.setdefault(uid, []).append((ld, cat, created.get("id")))

        if overflow > 0:
            digest_jobs.append((uid, overflow, user_locale.get(uid)))

        await db_service.advance_alert_rotation_cursor(uid, 1)

    # 4b) Digest do excedente (fora do silêncio). Durante a noite não se cria:
    # o primeiro run da manhã cria-o com o excedente desse run e envia o push
    # (se criássemos agora, `_is_new` seria falso de manhã e o push morria).
    for uid, count, locale in digest_jobs:
        if quiet:
            continue
        try:
            res = await db_service.upsert_daily_digest(uid, count, locale=locale)
            report.digest += 1
            if res and res.get("_is_new"):
                total_n = count
                try:
                    total_n = int(json.loads(res.get("msg_params") or "{}").get("n", count))
                except (ValueError, TypeError):
                    total_n = count
                if await db_service.is_push_enabled(uid):
                    # Coalescencia B1: se este run ja vai enviar um alerta de
                    # lead, o digest fica so no in-app. Nunca dois pushes no
                    # mesmo run.
                    if push_jobs.get(uid):
                        continue
                    rendered = render("digest", locale, n=total_n, limit=limit) or {}
                    click = _click_fields(res.get("id"))
                    digest_url = "/dashboard?src=push"
                    if click:
                        digest_url += f"&nid={click['nid']}&sig={click['sig']}"
                    digest_payload = {
                        "title": rendered.get("title") or tr("digest.title", locale),
                        "body": rendered.get("message")
                        or tr("digest.main_msg", locale, n=total_n, limit=limit),
                        "icon": _PUSH_ICON,
                        "badge": _PUSH_ICON,
                        "tag": f"digest_{normalize(locale)}",
                        "url": digest_url,
                        "actions": [
                            {
                                "action": "open",
                                "title": "Ver oportunidades",
                            },
                            {"action": "dismiss", "title": "Dispensar"},
                        ],
                    }
                    digest_payload.update(click)
                    await push_service.send_to_user(
                        uid,
                        digest_payload,
                        "digest",
                        ttl=settings.PUSH_TTL_DIGEST_S,
                        urgency="normal",
                    )
        except Exception as e:
            logger.error(f"Digest diário user={uid} falhou: {e}")

    # 5) Push coalescido (1 por run) + min-gap + silêncio.
    for uid, jobs in push_jobs.items():
        try:
            if not await db_service.is_push_enabled(uid):
                continue
            locale = user_locale.get(uid)
            base = user_base.get(uid)
            source = user_base_source.get(uid)
            show_address = user_show_address.get(uid, True)

            eligible: list = []
            for lead, cat, nid in jobs:
                signal, _status = _signal_of(lead)
                if quiet and signal != "legal_obligation":
                    report.quiet_suppressed += 1
                    continue
                eligible.append((lead, cat, nid, signal))
            if not eligible:
                continue

            gap_min = int(user_gap.get(uid) or 0)
            last_dt = _parse_dt(last_alerts.get(uid))
            if gap_min > 0 and last_dt and (now - last_dt).total_seconds() < gap_min * 60:
                report.gap_suppressed += len(eligible)
                continue

            if len(eligible) == 1:
                lead, cat, nid, signal = eligible[0]
                pct = await _confidence_pct(lead, confidence_cache)
                distance = _distance_miles(base, lead) if base else None
                show_distance = (
                    distance is not None
                    and source in ("gps", "manual")
                    and bool(getattr(settings, "PUSH_DISTANCE_ENABLED", True))
                )
                payload = _build_push_payload(
                    lead,
                    cat,
                    signal,
                    locale,
                    distance,
                    show_distance,
                    pct,
                    show_address,
                    notification_id=nid,
                )
                sent = await push_service.send_to_user(
                    uid,
                    payload,
                    "lead_alert",
                    ttl=settings.PUSH_TTL_LEAD_S,
                    urgency="high" if signal == "legal_obligation" else "normal",
                )
            else:
                distances: dict = {}
                for lead, _cat, _nid, _signal in eligible:
                    d = _distance_miles(base, lead) if base else None
                    if d is not None:
                        distances[lead["id"]] = d
                show_distance = (
                    bool(distances)
                    and source in ("gps", "manual")
                    and bool(getattr(settings, "PUSH_DISTANCE_ENABLED", True))
                )
                has_legal = any(
                    sig == "legal_obligation"
                    for (_lead, _cat, _nid, sig) in eligible
                )
                payload = _build_batch_payload(
                    [(lead, cat) for (lead, cat, _nid, _sig) in eligible],
                    locale,
                    distances if show_distance else None,
                    show_distance,
                    eligible[0][2],
                )
                sent = await push_service.send_to_user(
                    uid,
                    payload,
                    "lead_alert",
                    ttl=settings.PUSH_TTL_LEAD_S,
                    urgency="high" if has_legal else "normal",
                )
                if sent:
                    report.batched += 1
            if sent:
                report.pushed += 1
        except Exception as e:
            logger.error(f"Push error user={uid}: {e}")

    logger.info(
        f"Alert Planner: {report.created} in-app, {report.digest} digest, "
        f"{report.pushed} push ({report.batched} lote(s), "
        f"{report.quiet_suppressed} em silêncio, {report.gap_suppressed} em min-gap), "
        f"audiência {report.audience} ({report.candidates} candidato(s), teto {limit})"
    )
    return report

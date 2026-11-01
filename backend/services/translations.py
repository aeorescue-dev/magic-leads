"""translations.py — Dicionários i18n para notificações (PT/EN/ES).

Fonte única para títulos + mensagens de push e notificações in-app, localizadas
por usuário. Cada fan-out lê o campo `locale` do usuário (coluna `users.locale`,
padrão "en") e escolhe a língua correspondente.

Estrutura: TRANSLATIONS[grupo][locale]["chave"].
  - "new_lead":     nova oportunidade (base junto ao evitar 10/dia + push WNS).
  - "status_change": mudança de status de um lead favorito.
  - "system":       avisos gerais/broadcast e fallback.

Helper público:
  - tr(key, locale=None, **kw)        → texto com {placeholders} preenchidos.
  - group(locale=None, group=...)     → dict completo de um grupo para bulk/digest.
  - normalize(locale)                 → "pt" | "en" | "es" (fallback "en").
"""

from typing import Optional

DEFAULT_LOCALE = "en"
SUPPORTED = ("pt", "en", "es")


def normalize(locale: Optional[str]) -> str:
    """Normaliza e valida um locale (ex.: "pt-BR" / "pt_br" / "en-US" → base)."""
    if not locale:
        return DEFAULT_LOCALE
    code = str(locale).strip().lower()
    if not code:
        return DEFAULT_LOCALE
    base = code.split("-")[0].split("_")[0]
    return base if base in SUPPORTED else DEFAULT_LOCALE


TRANSLATIONS = {
    "new_lead": {
        "pt": {
            "title": "Nova oportunidade",
            "main_msg": "Nova oportunidade de {category} em {addr} — {city}",
            "batch_title": "Novas oportunidades",
            "batch_body": "Chegaram {n} novos leads em seus filtros.",
            "daily_limit_body": "Você atingiu o limite de {limit} novos leads hoje. Volte amanhã.",
            "digest_body": "Resumo diário: {n} novos leads hoje. Limite de {limit} renova amanhã.",
            "push_tag": "new-lead",
        },
        "en": {
            "title": "New opportunity",
            "main_msg": "New {category} opportunity in {addr} — {city}",
            "batch_title": "New opportunities",
            "batch_body": "{n} new leads arrived matching your filters.",
            "daily_limit_body": "You reached the daily limit of {limit} new leads. Come back tomorrow.",
            "digest_body": "Daily digest: {n} new leads today. Limit of {limit} resets tomorrow.",
            "push_tag": "new-lead",
        },
        "es": {
            "title": "Nueva oportunidad",
            "main_msg": "Nueva oportunidad de {category} en {addr} — {city}",
            "batch_title": "Nuevas oportunidades",
            "batch_body": "Llegaron {n} nuevos leads que coinciden con sus filtros.",
            "daily_limit_body": "Alcanzó el límite diario de {limit} nuevos leads. Vuelva mañana.",
            "digest_body": "Resumen diario: {n} nuevos leads hoy. Límite de {limit} se renueva mañana.",
            "push_tag": "nueva-oportunidad",
        },
    },
    "status_change": {
        "pt": {
            "title": "Status atualizado",
            "main_msg": "O lead {addr} — {city} agora está '{status}' (categoria {category}).",
            "push_tag": "status-change",
        },
        "en": {
            "title": "Status updated",
            "main_msg": "The lead {addr} — {city} is now '{status}' (category {category}).",
            "push_tag": "status-change",
        },
        "es": {
            "title": "Estado actualizado",
            "main_msg": "El lead {addr} — {city} ahora está '{status}' (categoría {category}).",
            "push_tag": "estado-actualizado",
        },
    },
    "system": {
        "pt": {
            "title": "Aviso do sistema",
            "main_msg": "Uma nova mensagem chegou.",
            "push_tag": "system",
        },
        "en": {
            "title": "System notice",
            "main_msg": "A new message has arrived.",
            "push_tag": "system",
        },
        "es": {
            "title": "Aviso del sistema",
            "main_msg": "Llegó un nuevo mensaje.",
            "push_tag": "sistema",
        },
    },
    "digest": {
        "pt": {
            "title": "Resumo diário de alertas",
            "main_msg": "{n} oportunidades nos seus ofícios hoje. O limite de {limit} renova amanhã.",
            "push_tag": "digest",
        },
        "en": {
            "title": "Daily digest",
            "main_msg": "{n} opportunities in your trades today. The limit of {limit} resets tomorrow.",
            "push_tag": "digest",
        },
        "es": {
            "title": "Resumen diario",
            "main_msg": "{n} oportunidades en sus oficios hoy. El límite de {limit} se renueva mañana.",
            "push_tag": "digest",
        },
    },
    # B3: variante B do digest (A/B de copy). Mensagem mais concreta e com
    # prazo — o objetivo e' medir CTR contra a variante A (neutra).
    "digest_b": {
        "pt": {
            "title": "{n} novas oportunidades perto de si",
            "main_msg": "{n} chamados e obras na sua cidade. Os Melhores leads são reservados primeiro.",
            "push_tag": "digest",
        },
        "en": {
            "title": "{n} new opportunities near you",
            "main_msg": "{n} requests and permits in your city. The best leads get booked first.",
            "push_tag": "digest",
        },
        "es": {
            "title": "{n} nuevas oportunidades cerca de ti",
            "main_msg": "{n} solicitudes y obras en tu ciudad. Los mejores leads se reservan primero.",
            "push_tag": "digest",
        },
    },
    "owner_enriched": {
        "pt": {
            "title": "Novos proprietários identificados",
            "main_msg": "{n} novo(s) proprietário(s) encontrado(s) em {city}",
            "push_tag": "owner_enriched",
        },
        "en": {
            "title": "New owners identified",
            "main_msg": "{n} new owner(s) found in {city}",
            "push_tag": "owner_enriched",
        },
        "es": {
            "title": "Nuevos propietarios identificados",
            "main_msg": "{n} nuevo(s) propietario(s) encontrado(s) en {city}",
            "push_tag": "owner_enriched",
        },
    },
    "enrichment_complete": {
        "pt": {
            "title": "Enriquecimento concluído",
            "main_msg": "{owners} proprietário(s), {mailing} morada(s) postal(is), {phones} telefone(s) e {emails} email(s) encontrados.",
            "push_tag": "enrichment_complete",
        },
        "en": {
            "title": "Enrichment complete",
            "main_msg": "{owners} owner(s), {mailing} mailing address(es), {phones} phone(s) and {emails} email(s) found.",
            "push_tag": "enrichment_complete",
        },
        "es": {
            "title": "Enriquecimiento completo",
            "main_msg": "{owners} propietario(s), {mailing} dirección(es), {phones} teléfono(s) y {emails} correo(s) encontrados.",
            "push_tag": "enrichment_complete",
        },
    },
    # Ciclo de vida (watchdog de reveals e fases). Antes eram strings PT
    # hardcoded na BD; agora têm chave + params e são renderizadas no locale
    # do destinatário (in-app e push).
    "reveal_timeout": {
        "pt": {"title": "🕒 Lead voltou ao pool", "main_msg": "{subject} voltou a ficar disponível para outros empreiteiros. Nenhum contato foi sinalizado em 1 hora."},
        "en": {"title": "🕒 Lead returned to the pool", "main_msg": "{subject} is available to other contractors again. No contact was flagged within 1 hour."},
        "es": {"title": "🕒 El lead volvió al pool", "main_msg": "{subject} vuelve a estar disponible para otros contratistas. No se marcó ningún contacto en 1 hora."},
    },
    "reveal_urgent": {
        "pt": {"title": "🚨 Últimos 15 minutos!", "main_msg": "Você revelou {subject} ({category}) e ainda não sinalizou contato. Em 15 min o lead volta ao pool."},
        "en": {"title": "🚨 Last 15 minutes!", "main_msg": "You revealed {subject} ({category}) and haven't flagged contact yet. In 15 min the lead returns to the pool."},
        "es": {"title": "🚨 ¡Últimos 15 minutos!", "main_msg": "Revelaste {subject} ({category}) y aún no marcaste contacto. En 15 min el lead vuelve al pool."},
    },
    "reveal_followup": {
        "pt": {"title": "⏰ Lead revelado, aguardando você", "main_msg": "Faltam 30 min para {subject} ({category}) voltar ao pool. Registre o contato ou ligue agora."},
        "en": {"title": "⏰ Lead revealed, waiting on you", "main_msg": "30 min left before {subject} ({category}) returns to the pool. Flag the contact or call now."},
        "es": {"title": "⏰ Lead revelado, esperando por ti", "main_msg": "Quedan 30 min para que {subject} ({category}) vuelva al pool. Marca el contacto o llama ahora."},
    },
    "stage_urgent_contact": {
        "pt": {"title": "Últimas 2 horas!", "main_msg": "A fase Contactar do lead {address} expira em 2h."},
        "en": {"title": "Last 2 hours!", "main_msg": "The Contact stage for lead {address} expires in 2h."},
        "es": {"title": "¡Últimas 2 horas!", "main_msg": "La fase Contactar del lead {address} expira en 2h."},
    },
    "stage_urgent_negotiate": {
        "pt": {"title": "Últimas 2 horas!", "main_msg": "A fase Negociar do lead {address} expira em 2h."},
        "en": {"title": "Last 2 hours!", "main_msg": "The Negotiation stage for lead {address} expires in 2h."},
        "es": {"title": "¡Últimas 2 horas!", "main_msg": "La fase Negociar del lead {address} expira en 2h."},
    },
    "stage_warning_contact": {
        "pt": {"title": "Faltam 24 horas", "main_msg": "A fase Contactar do lead {address} expira em 24h."},
        "en": {"title": "24 hours left", "main_msg": "The Contact stage for lead {address} expires in 24h."},
        "es": {"title": "Quedan 24 horas", "main_msg": "La fase Contactar del lead {address} expira en 24h."},
    },
    "stage_warning_negotiate": {
        "pt": {"title": "Faltam 24 horas", "main_msg": "A fase Negociar do lead {address} expira em 24h."},
        "en": {"title": "24 hours left", "main_msg": "The Negotiation stage for lead {address} expires in 24h."},
        "es": {"title": "Quedan 24 horas", "main_msg": "La fase Negociar del lead {address} expira en 24h."},
    },
    # Fallback para avisos antigos sem msg_key (criados antes da Fase 25).
    "stage_urgent": {
        "pt": {"title": "Últimas 2 horas!", "main_msg": "Uma fase do seu lead expira em 2h."},
        "en": {"title": "Last 2 hours!", "main_msg": "A stage of your lead expires in 2h."},
        "es": {"title": "¡Últimas 2 horas!", "main_msg": "Una fase de tu lead expira en 2h."},
    },
    "stage_warning": {
        "pt": {"title": "Faltam 24 horas", "main_msg": "Uma fase do seu lead expira em 24h."},
        "en": {"title": "24 hours left", "main_msg": "A stage of your lead expires in 24h."},
        "es": {"title": "Quedan 24 horas", "main_msg": "Una fase de tu lead expira en 24h."},
    },
}


def group(group: str, locale: Optional[str] = None) -> dict:
    """Retorna o dict completo de um grupo para um locale (fallback PT)."""
    table = TRANSLATIONS.get(group) or {}
    return table.get(normalize(locale)) or table.get(DEFAULT_LOCALE) or {}


def tr(key: str, locale: Optional[str] = None, **kw) -> str:
    """Busca e preenche o texto localizado.

    key tem formato "grupo.chave" (ex.: "new_lead.title").
    Placeholders no formato {nome} são preenchidos por kw. Se o texto não
    existir no grupo/locale, devolve a própria key (nunca quebra).
    """
    group_name, _, k = key.partition(".")
    text = group(group_name, locale).get(k)
    if text is None:
        _hidden = _LAST_KNOWN.get(key)
        # Guarda para depuração caso algum texto ainda esteja ausente.
        _LAST_KNOWN[key] = (locale, _hidden if _hidden else None)
        return key
    if not kw:
        return text
    try:
        return text.format(**kw)
    except (KeyError, IndexError, ValueError):
        return text


    try:
        return text.format(**kw)
    except (KeyError, IndexError, ValueError):
        return text


def render(group_key: str, locale: Optional[str] = None, **params) -> Optional[dict]:
    """Renderiza {title, message} de um grupo, ou None se faltar o par.

    Convenção dos grupos de notificação: chaves `title` + `main_msg`. Isso
    permite guardar em `notifications.msg_key` apenas o nome do grupo e
    localizar o texto na leitura (no locale do utilizador).
    """
    table = group(group_key, locale)
    title = table.get("title")
    message = table.get("main_msg")
    if title is None or message is None:
        return None

    def _fmt(text: str) -> str:
        if not params:
            return text
        try:
            return text.format(**params)
        except (KeyError, IndexError, ValueError):
            return text

    return {"title": _fmt(title), "message": _fmt(message)}


_LAST_KNOWN: dict = {}


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Alert Engine v2 — etiquetas de categoria e sinal para o payload de push.
# O push nao pode mostrar chaves internas ("Door_Window") nem prometer
# "alta probabilidade" sem numero.
# ---------------------------------------------------------------------------

CATEGORY_LABELS = {
    "Roof": {"pt": "Telhado & Estrutura", "en": "Roofing & Structure", "es": "Tejado y Estructura"},
    "Structure": {"pt": "Estrutura", "en": "Structure", "es": "Estructura"},
    "Plumbing": {"pt": "Encanamento", "en": "Plumbing", "es": "Fontanería"},
    "Grass": {"pt": "Mato & Entulho", "en": "Lawn & Debris", "es": "Maleza y Escombros"},
    "Paint": {"pt": "Pintura", "en": "Painting", "es": "Pintura"},
    "Permit_Rejected": {"pt": "Obras & Permissões", "en": "Permits & Works", "es": "Obras y Permisos"},
    "Heating": {"pt": "Aquecimento & Água Quente", "en": "Heating & Hot Water", "es": "Calefacción y Agua Caliente"},
    "Electrical": {"pt": "Elétrica", "en": "Electrical", "es": "Eléctrica"},
    "Elevator": {"pt": "Elevadores", "en": "Elevators", "es": "Ascensores"},
    "Gas": {"pt": "Gás & Vazamentos", "en": "Gas & Leaks", "es": "Gas y Fugas"},
    "Rodent": {"pt": "Roedores & Pragas", "en": "Rodents & Pests", "es": "Roedores y Plagas"},
    "Mold": {"pt": "Mofo & Umidade", "en": "Mold & Moisture", "es": "Moho y Humedad"},
    "Lead": {"pt": "Chumbo & Tinta", "en": "Lead & Paint", "es": "Plomo y Pintura"},
    "Unsanitary": {"pt": "Insanitário & Esgoto", "en": "Unsanitary & Sewage", "es": "Insalubre y Alcantarillado"},
    "Door_Window": {"pt": "Portas & Janelas", "en": "Doors & Windows", "es": "Puertas y Ventanas"},
    "Debris": {"pt": "Entulho & Lixo", "en": "Debris & Trash", "es": "Escombros y Basura"},
}

SIGNAL_LABELS = {
    "legal_obligation": {"pt": "Obrigação legal", "en": "Legal obligation", "es": "Obligación legal"},
    "authorized_work": {"pt": "Obra autorizada", "en": "Authorized work", "es": "Obra autorizada"},
    "open_request": {"pt": "Chamado aberto", "en": "Open request", "es": "Solicitud abierta"},
}


def category_label(category: Optional[str], locale: Optional[str] = None) -> str:
    loc = normalize(locale)
    entry = CATEGORY_LABELS.get(str(category or "").strip())
    if not entry:
        return str(category or "").replace("_", " ")
    return entry.get(loc) or entry.get(DEFAULT_LOCALE) or str(category)


def signal_label(signal: Optional[str], locale: Optional[str] = None) -> str:
    loc = normalize(locale)
    entry = SIGNAL_LABELS.get(str(signal or "").strip())
    if not entry:
        return ""
    return entry.get(loc) or entry.get(DEFAULT_LOCALE) or ""


def alert_why_now(
    signal: Optional[str],
    locale: Optional[str],
    oldest_open_days: Optional[int] = None,
    repeat_365: int = 0,
) -> str:
    """Frase curta de contexto para o corpo do push (sem dados sensiveis)."""
    loc = normalize(locale)
    days = int(oldest_open_days or 0)
    repeat = int(repeat_365 or 0)
    if signal == "authorized_work":
        return {"pt": "licença emitida", "en": "permit issued", "es": "licencia emitida"}[loc]
    if days > 0:
        if loc == "en":
            return f"open for {days} day" + ("s" if days != 1 else "")
        if loc == "es":
            return f"abierto hace {days} día" + ("s" if days != 1 else "")
        return f"aberto há {days} dia" + ("s" if days != 1 else "")
    if repeat > 1:
        if loc == "en":
            return f"{repeat} reports in 12 months"
        if loc == "es":
            return f"{repeat} reportes en 12 meses"
        return f"{repeat} ocorrências em 12 meses"
    if signal == "legal_obligation":
        return {"pt": "obrigação em aberto", "en": "open obligation", "es": "obligación abierta"}[loc]
    return {"pt": "disponível agora", "en": "available now", "es": "disponible ahora"}[loc]


def alert_confidence_label(
    locale: Optional[str], phone_verified: bool = False, success_pct: Optional[int] = None
) -> str:
    loc = normalize(locale)
    if phone_verified:
        return {"pt": "telefone verificado", "en": "verified phone", "es": "teléfono verificado"}[loc]
    if success_pct is not None:
        if loc == "en":
            return f"phone: {success_pct}% findable"
        if loc == "es":
            return f"teléfono: {success_pct}% localizable"
        return f"telefone: {success_pct}% encontrável"
    return {"pt": "telefone sob consulta", "en": "phone on request", "es": "teléfono bajo consulta"}[loc]

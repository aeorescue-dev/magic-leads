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
            "main_msg": "Mais {n} oportunidades chegaram hoje — o limite de {limit} renova amanhã.",
            "push_tag": "digest",
        },
        "en": {
            "title": "Daily digest",
            "main_msg": "More {n} new opportunities today — the limit of {limit} resets tomorrow.",
            "push_tag": "digest",
        },
        "es": {
            "title": "Resumen diario",
            "main_msg": "Hoy llegaron {n} oportunidades más — el límite de {limit} se renueva mañana.",
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

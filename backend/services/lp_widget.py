"""Widget de captação da LP — persistência e entrega (Fase 0/1).

Isolamento deliberado:
- Tabelas `lp_*` no SQLite principal, sem tocar em `leads`, `users`, `voice_*`
  ou em qualquer tabela de faturação.
- Nenhum LLM nesta fase. A tradução é feita pela equipa na inbox; o envio
  final em inglês é sempre revisto por um humano.
- O envio de e-mail usa a API HTTP da Resend (HTTPS :443) já usada pelo
  projeto. Sem `EMAIL_API_KEY`, o envio é registado em log e não bloqueia.
"""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx

from ..config import settings
from ..utils.logger import logger
from . import db

MAX_MESSAGE_CHARS = 2000
MAX_REPLY_CHARS = 4000
MAX_THREAD_MESSAGES = 60
VALID_INTENTS = {"vs_ads", "vs_angi", "phones", "price", "area", "question"}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS lp_threads (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  token_hash TEXT NOT NULL UNIQUE,
  email TEXT NOT NULL,
  name TEXT,
  company TEXT,
  city TEXT,
  trade TEXT,
  intent TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'new',
  locale TEXT NOT NULL DEFAULT 'en',
  source_section TEXT,
  consent_email INTEGER NOT NULL DEFAULT 0,
  consent_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  last_message_at TEXT,
  assigned_to INTEGER,
  sla_due_at TEXT,
  ip_hash TEXT,
  user_agent TEXT
);
CREATE INDEX IF NOT EXISTS idx_lp_threads_status
  ON lp_threads (status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_lp_threads_last_message
  ON lp_threads (last_message_at DESC);

CREATE TABLE IF NOT EXISTS lp_messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  thread_id INTEGER NOT NULL,
  direction TEXT NOT NULL,
  channel TEXT NOT NULL DEFAULT 'widget',
  body TEXT NOT NULL,
  body_pt TEXT,
  body_en TEXT,
  lang TEXT NOT NULL DEFAULT 'en',
  author_type TEXT NOT NULL DEFAULT 'lead',
  author_id INTEGER,
  email_status TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lp_messages_thread
  ON lp_messages (thread_id, id ASC);

CREATE TABLE IF NOT EXISTS lp_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  thread_id INTEGER,
  event TEXT NOT NULL,
  payload TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lp_events_thread
  ON lp_events (thread_id, id DESC);
"""

_initialized = False


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: Optional[datetime] = None) -> str:
    return (value or _now()).isoformat()


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _ip_hash(ip: str) -> str:
    raw = f"lp-widget:{ip or 'unknown'}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _clean(value: Any, limit: int = 200) -> str:
    return str(value or "").strip()[:limit]


def init() -> None:
    """Cria as tabelas `lp_*` se ainda não existirem (idempotente)."""
    global _initialized
    if _initialized:
        return
    try:
        conn = db.get_connection()
        try:
            conn.executescript(_SCHEMA)
            conn.commit()
        finally:
            conn.close()
    except sqlite3.OperationalError as exc:
        logger.warning("[LP-WIDGET] não foi possível criar tabelas: %s", exc)
        return
    _initialized = True


def _event(conn: sqlite3.Connection, thread_id: int, event: str, payload: Any = None) -> None:
    try:
        conn.execute(
            "INSERT INTO lp_events (thread_id, event, payload, created_at) "
            "VALUES (?, ?, ?, ?)",
            (
                thread_id,
                event,
                None if payload is None else str(payload)[:2000],
                _iso(),
            ),
        )
    except sqlite3.Error:
        # Auditoria não pode quebrar a conversão.
        pass


def send_email(
    to: str,
    subject: str,
    text: str,
    *,
    reply_to: Optional[str] = None,
) -> bool:
    """Envia e-mail transacional via Resend. Fail-soft: devolve False."""
    if not settings.EMAIL_API_KEY or not settings.EMAIL_FROM:
        logger.info(
            "[LP-WIDGET] e-mail não enviado (EMAIL_API_KEY/EMAIL_FROM ausentes) to=%s subject=%s",
            to,
            subject,
        )
        return False

    payload: dict[str, Any] = {
        "from": settings.EMAIL_FROM,
        "to": [to],
        "subject": subject,
        "text": text,
    }
    if reply_to:
        payload["reply_to"] = reply_to

    try:
        response = httpx.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {settings.EMAIL_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=15,
        )
    except Exception as exc:  # noqa: BLE001 - rede/HTTP nunca derruba o pedido
        logger.error("[LP-WIDGET] falha de rede na Resend: %r", exc)
        return False

    if response.status_code in (200, 201, 202):
        logger.info("[LP-WIDGET] e-mail enviado via Resend para %s", to)
        return True

    logger.error(
        "[LP-WIDGET] Resend recusou o envio HTTP %s: %s",
        response.status_code,
        response.text[:500],
    )
    return False


def _public_url(base: str, token: str) -> str:
    if not base:
        return ""
    separator = "&" if "?" in base else "?"
    return f"{base}{separator}thread={token}"


def _send_ack(thread: dict, token: str) -> bool:
    name = _clean(thread.get("name"), 80)
    greeting = f"Hi {name}," if name else "Hi,"
    sla = int(getattr(settings, "LP_WIDGET_SLA_HOURS", 4) or 4)
    lines = [
        greeting,
        "",
        "Thanks for reaching out to Magic Leads. We received your message and "
        "a specialist is reviewing it.",
        "",
        f"You can expect a reply within {sla} business hours. Your reference is "
        f"#LP-{thread.get('id')}.",
    ]
    link = _public_url(
        str(getattr(settings, "LP_WIDGET_PUBLIC_URL", "") or ""),
        token,
    )
    if link:
        lines.extend(["", f"Continue the conversation here: {link}"])
    lines.extend(
        [
            "",
            "— Magic Leads",
            "New York · Boston · Dallas · Chicago",
        ]
    )
    return send_email(
        str(thread.get("email") or ""),
        "We received your message — Magic Leads",
        "\n".join(lines),
        reply_to=str(getattr(settings, "LP_WIDGET_REPLY_TO", "") or "") or None,
    )


def create_thread(
    *,
    email: str,
    intent: str,
    message: str,
    name: str = "",
    company: str = "",
    city: str = "",
    trade: str = "",
    consent_email: bool = False,
    locale: str = "en",
    source_section: str = "",
    ip: str = "",
    user_agent: str = "",
) -> dict:
    """Cria o fio e a primeira mensagem. Devolve o token em claro uma única vez."""
    init()
    intent = _clean(intent, 40).lower()
    if intent not in VALID_INTENTS:
        intent = "question"
    message = _clean(message, MAX_MESSAGE_CHARS)
    email = _clean(email, 254).lower()
    if not email or "@" not in email:
        raise ValueError("invalid_email")
    if not message:
        raise ValueError("empty_message")
    if not consent_email:
        raise ValueError("consent_required")

    token = secrets.token_urlsafe(32)
    now = _now()
    sla_at = now + timedelta(
        hours=max(1, int(getattr(settings, "LP_WIDGET_SLA_HOURS", 4) or 4))
    )

    conn = db.get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO lp_threads ("
            "token_hash, email, name, company, city, trade, intent, status, "
            "locale, source_section, consent_email, consent_at, created_at, "
            "updated_at, last_message_at, sla_due_at, ip_hash, user_agent"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, 'new', ?, ?, 1, ?, ?, ?, ?, ?, ?, ?)",
            (
                _hash_token(token),
                email,
                _clean(name, 80),
                _clean(company, 160),
                _clean(city, 80),
                _clean(trade, 80),
                intent,
                _clean(locale, 8) or "en",
                _clean(source_section, 80),
                _iso(now),
                _iso(now),
                _iso(now),
                _iso(now),
                _iso(sla_at),
                _ip_hash(ip),
                _clean(user_agent, 300),
            ),
        )
        thread_id = int(cur.lastrowid)
        conn.execute(
            "INSERT INTO lp_messages ("
            "thread_id, direction, channel, body, body_pt, body_en, lang, "
            "author_type, created_at"
            ") VALUES (?, 'inbound', 'widget', ?, NULL, NULL, ?, 'lead', ?)",
            (thread_id, message, _clean(locale, 8) or "en", _iso(now)),
        )
        _event(conn, thread_id, "thread_created", {"intent": intent})
        conn.commit()
        thread = {
            "id": thread_id,
            "email": email,
            "name": name,
            "created_at": _iso(now),
        }
    finally:
        conn.close()

    ack_sent = _send_ack(thread, token)
    logger.info(
        "[LP-WIDGET] thread #%s criado intent=%s ack=%s",
        thread["id"],
        intent,
        ack_sent,
    )
    return {
        "id": thread["id"],
        "token": token,
        "created_at": thread["created_at"],
        "ack_sent": ack_sent,
        "sla_hours": int(getattr(settings, "LP_WIDGET_SLA_HOURS", 4) or 4),
    }


def _thread_by_token(conn: sqlite3.Connection, token: str) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM lp_threads WHERE token_hash = ?",
        (_hash_token(token),),
    ).fetchone()


def get_thread_public(token: str) -> Optional[dict]:
    """Vista para o lead: só mensagens de saída, sem notas internas PT-BR."""
    init()
    if not token:
        return None
    conn = db.get_connection()
    try:
        thread = _thread_by_token(conn, token)
        if not thread:
            return None
        rows = conn.execute(
            "SELECT id, direction, body, body_en, created_at "
            "FROM lp_messages WHERE thread_id = ? ORDER BY id ASC",
            (thread["id"],),
        ).fetchall()
        messages = []
        for row in rows:
            if row["direction"] == "inbound":
                text = row["body"]
                role = "lead"
            else:
                text = row["body_en"] or row["body"]
                role = "team"
            messages.append(
                {
                    "id": int(row["id"]),
                    "role": role,
                    "text": text,
                    "created_at": row["created_at"],
                }
            )
        return {
            "id": int(thread["id"]),
            "status": thread["status"],
            "created_at": thread["created_at"],
            "sla_hours": int(getattr(settings, "LP_WIDGET_SLA_HOURS", 4) or 4),
            "messages": messages,
        }
    finally:
        conn.close()


def add_lead_message(token: str, message: str) -> Optional[dict]:
    """Follow-up do lead no mesmo fio. Devolve None se o token não existir."""
    init()
    text = _clean(message, MAX_MESSAGE_CHARS)
    if not text:
        raise ValueError("empty_message")

    conn = db.get_connection()
    try:
        thread = _thread_by_token(conn, token)
        if not thread:
            return None
        count = conn.execute(
            "SELECT COUNT(*) AS n FROM lp_messages WHERE thread_id = ?",
            (thread["id"],),
        ).fetchone()["n"]
        if int(count) >= MAX_THREAD_MESSAGES:
            raise ValueError("thread_full")

        now = _now()
        sla_at = now + timedelta(
            hours=max(1, int(getattr(settings, "LP_WIDGET_SLA_HOURS", 4) or 4))
        )
        cur = conn.execute(
            "INSERT INTO lp_messages ("
            "thread_id, direction, channel, body, lang, author_type, created_at"
            ") VALUES (?, 'inbound', 'widget', ?, ?, 'lead', ?)",
            (thread["id"], text, _clean(thread["locale"], 8) or "en", _iso(now)),
        )
        conn.execute(
            "UPDATE lp_threads SET status = 'new', updated_at = ?, "
            "last_message_at = ?, sla_due_at = ? WHERE id = ?",
            (_iso(now), _iso(now), _iso(sla_at), thread["id"]),
        )
        _event(conn, int(thread["id"]), "lead_message", {"message_id": cur.lastrowid})
        conn.commit()
        return {"ok": True, "message_id": int(cur.lastrowid)}
    finally:
        conn.close()


def list_threads(status: str = "", limit: int = 50) -> list[dict]:
    init()
    limit = max(1, min(200, int(limit or 50)))
    status = _clean(status, 30)
    conn = db.get_connection()
    try:
        rows = conn.execute(
            "SELECT t.id, t.email, t.name, t.company, t.city, t.trade, "
            "t.intent, t.status, t.created_at, t.last_message_at, t.sla_due_at, "
            "(SELECT body FROM lp_messages m WHERE m.thread_id = t.id "
            " ORDER BY m.id DESC LIMIT 1) AS last_message, "
            "(SELECT COUNT(*) FROM lp_messages m WHERE m.thread_id = t.id) "
            " AS message_count "
            "FROM lp_threads t "
            "WHERE (? = '' OR t.status = ?) "
            "ORDER BY COALESCE(t.last_message_at, t.created_at) DESC "
            "LIMIT ?",
            (status, status, limit),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_thread_admin(thread_id: int) -> Optional[dict]:
    init()
    conn = db.get_connection()
    try:
        thread = conn.execute(
            "SELECT id, email, name, company, city, trade, intent, status, "
            "locale, source_section, created_at, updated_at, last_message_at, "
            "sla_due_at FROM lp_threads WHERE id = ?",
            (int(thread_id),),
        ).fetchone()
        if not thread:
            return None
        messages = conn.execute(
            "SELECT id, direction, channel, body, body_pt, body_en, lang, "
            "author_type, author_id, email_status, created_at "
            "FROM lp_messages WHERE thread_id = ? ORDER BY id ASC",
            (int(thread_id),),
        ).fetchall()
        result = dict(thread)
        result["messages"] = [dict(row) for row in messages]
        return result
    finally:
        conn.close()


def reply(
    thread_id: int,
    *,
    body_pt: str,
    body_en: str,
    admin_id: Optional[int] = None,
) -> Optional[dict]:
    """Resposta da equipa: guarda PT-BR + EN, envia o EN por e-mail e devolve."""
    init()
    pt = _clean(body_pt, MAX_REPLY_CHARS)
    en = _clean(body_en, MAX_REPLY_CHARS)
    if not pt or not en:
        raise ValueError("empty_reply")

    conn = db.get_connection()
    try:
        thread = conn.execute(
            "SELECT * FROM lp_threads WHERE id = ?", (int(thread_id),)
        ).fetchone()
        if not thread:
            return None

        now = _now()
        cur = conn.execute(
            "INSERT INTO lp_messages ("
            "thread_id, direction, channel, body, body_pt, body_en, lang, "
            "author_type, author_id, email_status, created_at"
            ") VALUES (?, 'outbound', 'widget+email', ?, ?, ?, 'en', 'team', ?, "
            "'pending', ?)",
            (int(thread_id), en, pt, en, admin_id, _iso(now)),
        )
        message_id = int(cur.lastrowid)
        conn.execute(
            "UPDATE lp_threads SET status = 'replied', updated_at = ?, "
            "last_message_at = ? WHERE id = ?",
            (_iso(now), _iso(now), int(thread_id)),
        )
        _event(conn, int(thread_id), "team_reply", {"message_id": message_id})
        conn.commit()
        email = str(thread["email"] or "")
    finally:
        conn.close()

    email_sent = send_email(
        email,
        "Re: your question about Magic Leads",
        en,
        reply_to=str(getattr(settings, "LP_WIDGET_REPLY_TO", "") or "") or None,
    )

    conn = db.get_connection()
    try:
        conn.execute(
            "UPDATE lp_messages SET email_status = ? WHERE id = ?",
            ("sent" if email_sent else "failed", message_id),
        )
        conn.commit()
    finally:
        conn.close()

    logger.info(
        "[LP-WIDGET] resposta no thread #%s email=%s", thread_id, email_sent
    )
    return {
        "ok": True,
        "message_id": message_id,
        "email_sent": email_sent,
        "thread_id": int(thread_id),
    }

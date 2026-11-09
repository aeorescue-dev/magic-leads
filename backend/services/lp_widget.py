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
import os
import secrets
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx

from ..config import settings
from ..utils.logger import logger
from . import db, lp_ai

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
  trade_code TEXT,
  lead_source TEXT,
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
  user_agent TEXT,
  lead_lang TEXT DEFAULT 'en',
  ai_status TEXT DEFAULT 'pending',
  ai_provider TEXT,
  ai_error TEXT,
  draft_pt TEXT,
  draft_out TEXT,
  draft_out_lang TEXT,
  ai_updated_at TEXT
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

CREATE TABLE IF NOT EXISTS lp_attachments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  thread_id INTEGER NOT NULL,
  message_id INTEGER,
  direction TEXT NOT NULL,
  filename TEXT NOT NULL,
  content_type TEXT,
  size_bytes INTEGER NOT NULL DEFAULT 0,
  storage_path TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lp_attachments_thread
  ON lp_attachments (thread_id, id ASC);
"""

_initialized = False

_THREAD_MIGRATIONS = {
    "trade_code": "TEXT",
    "lead_source": "TEXT",
    "lead_lang": "TEXT DEFAULT 'en'",
    "ai_status": "TEXT DEFAULT 'pending'",
    "ai_provider": "TEXT",
    "ai_error": "TEXT",
    "draft_pt": "TEXT",
    "draft_out": "TEXT",
    "draft_out_lang": "TEXT",
    "ai_updated_at": "TEXT",
}


def _migrate_threads(conn: sqlite3.Connection) -> None:
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(lp_threads)")}
    for name, ddl in _THREAD_MIGRATIONS.items():
        if name not in cols:
            conn.execute(f"ALTER TABLE lp_threads ADD COLUMN {name} {ddl}")


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
            _migrate_threads(conn)
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
    lang = _clean(thread.get("lead_lang"), 8) or "en"
    base = lang[:2]
    sla = int(getattr(settings, "LP_WIDGET_SLA_HOURS", 4) or 4)
    if base == "pt":
        greeting = f"Olá {name}," if name else "Olá,"
        lines = [
            greeting,
            "",
            "Obrigado por contactar a Magic Leads. Recebemos a sua mensagem e "
            "um especialista está a analisá-la.",
            "",
            f"Pode esperar uma resposta em até {sla} horas úteis. A sua "
            f"referência é #LP-{thread.get('id')}.",
        ]
        subject = "Recebemos a sua mensagem — Magic Leads"
    elif base == "es":
        greeting = f"Hola {name}," if name else "Hola,"
        lines = [
            greeting,
            "",
            "Gracias por contactar Magic Leads. Hemos recibido tu mensaje y un "
            "especialista lo está revisando.",
            "",
            f"Puedes esperar una respuesta en un plazo de {sla} horas hábiles. "
            f"Tu referencia es #LP-{thread.get('id')}.",
        ]
        subject = "Hemos recibido tu mensaje — Magic Leads"
    else:
        greeting = f"Hi {name}," if name else "Hi,"
        lines = [
            greeting,
            "",
            "Thanks for reaching out to Magic Leads. We received your message and "
            "a specialist is reviewing it.",
            "",
            f"You can expect a reply within {sla} business hours. Your reference is "
            f"#LP-{thread.get('id')}.",
        ]
        subject = "We received your message — Magic Leads"
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
        subject,
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
    trade_code: str = "",
    lead_source: str = "",
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
    lead_lang = lp_ai.detect_language(message)
    sla_at = now + timedelta(
        hours=max(1, int(getattr(settings, "LP_WIDGET_SLA_HOURS", 4) or 4))
    )

    conn = db.get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO lp_threads ("
            "token_hash, email, name, company, city, trade, trade_code, "
            "lead_source, intent, status, "
            "locale, source_section, consent_email, consent_at, created_at, "
            "updated_at, last_message_at, sla_due_at, ip_hash, user_agent, "
            "lead_lang, ai_status"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'new', ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')",
            (
                _hash_token(token),
                email,
                _clean(name, 80),
                _clean(company, 160),
                _clean(city, 80),
                _clean(trade, 80),
                _clean(trade_code, 60),
                _clean(lead_source, 40),
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
                lead_lang,
            ),
        )
        thread_id = int(cur.lastrowid)
        conn.execute(
            "INSERT INTO lp_messages ("
            "thread_id, direction, channel, body, body_pt, body_en, lang, "
            "author_type, created_at"
            ") VALUES (?, 'inbound', 'widget', ?, NULL, NULL, ?, 'lead', ?)",
            (thread_id, message, lead_lang, _iso(now)),
        )
        _event(conn, thread_id, "thread_created", {"intent": intent})
        conn.commit()
        thread = {
            "id": thread_id,
            "email": email,
            "name": name,
            "lead_lang": lead_lang,
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
            "attachments": [
                dict(row)
                for row in conn.execute(
                    "SELECT id, direction, filename, content_type, size_bytes, "
                    "created_at FROM lp_attachments WHERE thread_id = ? "
                    "ORDER BY id ASC",
                    (thread["id"],),
                ).fetchall()
            ],
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
        lang = lp_ai.detect_language(text)
        sla_at = now + timedelta(
            hours=max(1, int(getattr(settings, "LP_WIDGET_SLA_HOURS", 4) or 4))
        )
        cur = conn.execute(
            "INSERT INTO lp_messages ("
            "thread_id, direction, channel, body, lang, author_type, created_at"
            ") VALUES (?, 'inbound', 'widget', ?, ?, 'lead', ?)",
            (thread["id"], text, lang, _iso(now)),
        )
        conn.execute(
            "UPDATE lp_threads SET status = 'new', updated_at = ?, "
            "last_message_at = ?, sla_due_at = ?, lead_lang = ?, "
            "ai_status = 'pending', ai_error = NULL WHERE id = ?",
            (_iso(now), _iso(now), _iso(sla_at), lang, thread["id"]),
        )
        _event(conn, int(thread["id"]), "lead_message", {"message_id": cur.lastrowid})
        conn.commit()
        return {
            "ok": True,
            "message_id": int(cur.lastrowid),
            "thread_id": int(thread["id"]),
        }
    finally:
        conn.close()


def update_message_translation(
    thread_id: int, message_id: int, body_pt: str
) -> Optional[dict]:
    """Guarda a tradução PT-BR de uma mensagem inbound (revisão humana)."""
    init()
    pt = _clean(body_pt, MAX_REPLY_CHARS)
    if not pt:
        raise ValueError("empty_translation")

    conn = db.get_connection()
    try:
        row = conn.execute(
            "SELECT id FROM lp_messages "
            "WHERE id = ? AND thread_id = ? AND direction = 'inbound'",
            (int(message_id), int(thread_id)),
        ).fetchone()
        if not row:
            return None
        conn.execute(
            "UPDATE lp_messages SET body_pt = ? WHERE id = ?",
            (pt, int(message_id)),
        )
        _event(
            conn,
            int(thread_id),
            "translation_saved",
            {"message_id": int(message_id)},
        )
        conn.commit()
        return {"ok": True, "message_id": int(message_id), "body_pt": pt}
    finally:
        conn.close()


MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
_ALLOWED_ATTACHMENT_TYPES = {
    "application/pdf",
    "text/plain",
    "text/csv",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def _upload_dir(thread_id: int) -> str:
    base = os.environ.get("LP_UPLOAD_DIR") or os.path.join(
        os.environ.get("DATA_DIR", "/data"), "lp_uploads"
    )
    path = os.path.join(base, str(int(thread_id)))
    os.makedirs(path, exist_ok=True)
    return path


def thread_id_for_token(token: str) -> Optional[int]:
    init()
    conn = db.get_connection()
    try:
        row = _thread_by_token(conn, token)
        return int(row["id"]) if row else None
    finally:
        conn.close()


def save_attachment(
    thread_id: int,
    *,
    direction: str,
    filename: str,
    content_type: str,
    data: bytes,
    message_id: Optional[int] = None,
) -> Optional[dict]:
    init()
    if direction not in {"inbound", "outbound"}:
        raise ValueError("invalid_direction")
    payload = data or b""
    if not payload:
        raise ValueError("empty_attachment")
    if len(payload) > MAX_ATTACHMENT_BYTES:
        raise ValueError("attachment_too_large")
    ctype = (content_type or "application/octet-stream").lower()
    if not (ctype.startswith("image/") or ctype in _ALLOWED_ATTACHMENT_TYPES):
        raise ValueError("unsupported_file_type")

    check = db.get_connection()
    try:
        exists = check.execute(
            "SELECT 1 FROM lp_threads WHERE id = ?", (int(thread_id),)
        ).fetchone()
        if not exists:
            return None
    finally:
        check.close()

    safe = os.path.basename(filename or "file")
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in safe)[:120]
    if not safe:
        safe = "file"
    stored = f"{uuid.uuid4().hex[:12]}_{safe}"
    path = os.path.join(_upload_dir(thread_id), stored)
    with open(path, "wb") as handle:
        handle.write(payload)

    conn = db.get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO lp_attachments ("
            "thread_id, message_id, direction, filename, content_type, "
            "size_bytes, storage_path, created_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                int(thread_id),
                int(message_id) if message_id else None,
                direction,
                safe,
                ctype,
                len(payload),
                path,
                _iso(),
            ),
        )
        _event(
            conn,
            int(thread_id),
            "attachment",
            {"attachment_id": cur.lastrowid, "direction": direction},
        )
        conn.commit()
        return {
            "id": int(cur.lastrowid),
            "thread_id": int(thread_id),
            "direction": direction,
            "filename": safe,
            "content_type": ctype,
            "size_bytes": len(payload),
            "created_at": _iso(),
        }
    finally:
        conn.close()


def list_attachments(thread_id: int) -> list[dict]:
    init()
    conn = db.get_connection()
    try:
        rows = conn.execute(
            "SELECT id, thread_id, message_id, direction, filename, "
            "content_type, size_bytes, created_at "
            "FROM lp_attachments WHERE thread_id = ? ORDER BY id ASC",
            (int(thread_id),),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_attachment(thread_id: int, attachment_id: int) -> Optional[dict]:
    init()
    conn = db.get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM lp_attachments "
            "WHERE id = ? AND thread_id = ?",
            (int(attachment_id), int(thread_id)),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def enrich_thread(thread_id: int) -> dict:
    """Traduz a última mensagem do lead e pré-preenche os rascunhos da equipa.

    Idempotente: não sobrescreve traduções ou rascunhos já editados por humanos.
    """
    init()
    conn = db.get_connection()
    try:
        thread = conn.execute(
            "SELECT * FROM lp_threads WHERE id = ?", (int(thread_id),)
        ).fetchone()
        if not thread:
            return {"ok": False, "status": "not_found"}
        message = conn.execute(
            "SELECT * FROM lp_messages "
            "WHERE thread_id = ? AND direction = 'inbound' "
            "ORDER BY id DESC LIMIT 1",
            (int(thread_id),),
        ).fetchone()
        if not message:
            return {"ok": False, "status": "no_message"}

        text = message["body"] or ""
        # O idioma guardado pode vir do locale do site; o texto é a fonte de
        # verdade. Detetamos sempre para suportar EN/PT/ES/FR/DE/IT.
        source = lp_ai.detect_language(text)
        existing_pt = _clean(message["body_pt"], MAX_REPLY_CHARS)
        provider = "existing"

        if existing_pt:
            pt = existing_pt
        else:
            try:
                pt, provider = lp_ai.translate(text, source, "pt")
            except lp_ai.AiNotConfigured as exc:
                conn.execute(
                    "UPDATE lp_threads SET lead_lang = ?, ai_status = 'needs_key', "
                    "ai_error = ?, ai_updated_at = ? WHERE id = ?",
                    (source, str(exc)[:300], _iso(), int(thread_id)),
                )
                conn.commit()
                return {"ok": False, "status": "needs_key", "error": str(exc)}
            except Exception as exc:  # noqa: BLE001
                conn.execute(
                    "UPDATE lp_threads SET lead_lang = ?, ai_status = 'failed', "
                    "ai_error = ?, ai_updated_at = ? WHERE id = ?",
                    (
                        source,
                        f"{type(exc).__name__}: {exc}"[:300],
                        _iso(),
                        int(thread_id),
                    ),
                )
                conn.commit()
                return {"ok": False, "status": "failed", "error": str(exc)}
            conn.execute(
                "UPDATE lp_messages SET body_pt = ?, lang = ? WHERE id = ?",
                (pt, source, int(message["id"])),
            )

        conn.execute(
            "UPDATE lp_messages SET lang = ? WHERE id = ?",
            (source, int(message["id"])),
        )

        suggestion_pt = lp_ai.suggest_reply_pt(
            thread["intent"], thread["city"] or "", thread["trade"] or ""
        )
        draft_pt = _clean(thread["draft_pt"], MAX_REPLY_CHARS) or suggestion_pt
        draft_out = _clean(thread["draft_out"], MAX_REPLY_CHARS)
        out_provider = provider
        if not draft_out:
            try:
                draft_out, out_provider = lp_ai.translate(draft_pt, "pt", source)
            except lp_ai.AiNotConfigured as exc:
                conn.execute(
                    "UPDATE lp_threads SET lead_lang = ?, ai_status = 'needs_key', "
                    "ai_provider = ?, ai_error = ?, draft_pt = ?, draft_out = NULL, "
                    "draft_out_lang = ?, ai_updated_at = ? WHERE id = ?",
                    (
                        source,
                        provider,
                        str(exc)[:300],
                        draft_pt,
                        source,
                        _iso(),
                        int(thread_id),
                    ),
                )
                conn.commit()
                return {
                    "ok": False,
                    "status": "needs_key",
                    "error": str(exc),
                }
            except Exception as exc:  # noqa: BLE001
                conn.execute(
                    "UPDATE lp_threads SET lead_lang = ?, ai_status = 'failed', "
                    "ai_provider = ?, ai_error = ?, draft_pt = ?, draft_out = NULL, "
                    "draft_out_lang = ?, ai_updated_at = ? WHERE id = ?",
                    (
                        source,
                        provider,
                        f"{type(exc).__name__}: {exc}"[:300],
                        draft_pt,
                        source,
                        _iso(),
                        int(thread_id),
                    ),
                )
                conn.commit()
                return {"ok": False, "status": "failed", "error": str(exc)}

        conn.execute(
            "UPDATE lp_threads SET lead_lang = ?, ai_status = 'ready', "
            "ai_provider = ?, ai_error = NULL, draft_pt = ?, draft_out = ?, "
            "draft_out_lang = ?, ai_updated_at = ? WHERE id = ?",
            (
                source,
                out_provider,
                draft_pt,
                draft_out,
                source,
                _iso(),
                int(thread_id),
            ),
        )
        _event(
            conn,
            int(thread_id),
            "ai_enriched",
            {"provider": out_provider, "lead_lang": source},
        )
        conn.commit()
        logger.info(
            "[LP-WIDGET] AI thread #%s provider=%s lang=%s",
            thread_id,
            out_provider,
            source,
        )
        return {
            "ok": True,
            "status": "ready",
            "lead_lang": source,
            "provider": out_provider,
            "draft_pt": draft_pt,
            "draft_out": draft_out,
        }
    finally:
        conn.close()


def translate_draft(thread_id: int, body_pt: str) -> Optional[dict]:
    """Traduz o rascunho PT-BR para o idioma de origem do lead."""
    init()
    pt = _clean(body_pt, MAX_REPLY_CHARS)
    if not pt:
        raise ValueError("empty_reply")

    conn = db.get_connection()
    try:
        thread = conn.execute(
            "SELECT * FROM lp_threads WHERE id = ?", (int(thread_id),)
        ).fetchone()
        if not thread:
            return None
        lead_lang = _clean(thread["lead_lang"], 8) or "en"
        try:
            out, provider = lp_ai.translate(pt, "pt", lead_lang)
        except lp_ai.AiNotConfigured as exc:
            raise ValueError(f"translation_not_configured: {exc}") from exc
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"translation_failed: {exc}") from exc

        conn.execute(
            "UPDATE lp_threads SET draft_pt = ?, draft_out = ?, "
            "draft_out_lang = ?, ai_provider = ?, ai_status = 'ready', "
            "ai_error = NULL, ai_updated_at = ? WHERE id = ?",
            (pt, out, lead_lang, provider, _iso(), int(thread_id)),
        )
        _event(
            conn,
            int(thread_id),
            "draft_translated",
            {"provider": provider, "lang": lead_lang},
        )
        conn.commit()
        return {
            "ok": True,
            "body_out": out,
            "lang": lead_lang,
            "provider": provider,
        }
    finally:
        conn.close()


def list_threads(
    status: str = "", limit: int = 50, period: str = ""
) -> list[dict]:
    init()
    limit = max(1, min(200, int(limit or 50)))
    status = _clean(status, 30)
    period = _clean(period, 20).lower()
    now = _now()
    if period == "today":
        since = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    elif period == "week":
        since = (now - timedelta(days=7)).isoformat()
    elif period == "month":
        since = (now - timedelta(days=30)).isoformat()
    else:
        since = ""
    conn = db.get_connection()
    try:
        rows = conn.execute(
            "SELECT t.id, t.email, t.name, t.company, t.city, t.trade, "
            "t.trade_code, t.lead_source, "
            "t.intent, t.status, t.lead_lang, t.ai_status, t.created_at, "
            "t.last_message_at, t.sla_due_at, "
            "(SELECT body FROM lp_messages m WHERE m.thread_id = t.id "
            " ORDER BY m.id DESC LIMIT 1) AS last_message, "
            "(SELECT COUNT(*) FROM lp_messages m WHERE m.thread_id = t.id) "
            " AS message_count "
            "FROM lp_threads t "
            "WHERE (? = '' OR t.status = ?) "
            "AND (? = '' OR datetime(t.created_at) >= datetime(?)) "
            "ORDER BY COALESCE(t.last_message_at, t.created_at) DESC "
            "LIMIT ?",
            (status, status, since, since, limit),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def set_thread_status(thread_id: int, status: str) -> Optional[dict]:
    """Muda o estado do fio (new/replied/archived)."""
    init()
    status = _clean(status, 30).lower()
    if status not in {"new", "replied", "archived"}:
        raise ValueError("invalid_status")
    conn = db.get_connection()
    try:
        row = conn.execute(
            "SELECT id FROM lp_threads WHERE id = ?", (int(thread_id),)
        ).fetchone()
        if not row:
            return None
        now = _iso()
        conn.execute(
            "UPDATE lp_threads SET status = ?, updated_at = ? WHERE id = ?",
            (status, now, int(thread_id)),
        )
        _event(conn, int(thread_id), "status_changed", {"status": status})
        conn.commit()
        return {"ok": True, "thread_id": int(thread_id), "status": status}
    finally:
        conn.close()


def get_thread_admin(thread_id: int) -> Optional[dict]:
    init()
    conn = db.get_connection()
    try:
        thread = conn.execute(
            "SELECT id, email, name, company, city, trade, trade_code, "
            "lead_source, intent, status, "
            "locale, source_section, lead_lang, ai_status, ai_provider, "
            "ai_error, draft_pt, draft_out, draft_out_lang, ai_updated_at, "
            "created_at, updated_at, last_message_at, sla_due_at "
            "FROM lp_threads WHERE id = ?",
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
        history = conn.execute(
            "SELECT t.id, t.status, t.created_at, t.last_message_at, "
            "(SELECT body FROM lp_messages m WHERE m.thread_id = t.id "
            " ORDER BY m.id DESC LIMIT 1) AS last_message, "
            "(SELECT COUNT(*) FROM lp_messages m WHERE m.thread_id = t.id) "
            " AS message_count "
            "FROM lp_threads t "
            "WHERE t.email = ? AND t.id <> ? "
            "ORDER BY t.created_at DESC LIMIT 10",
            (thread["email"], int(thread_id)),
        ).fetchall()
        result["history"] = [dict(row) for row in history]
        attachments = conn.execute(
            "SELECT id, thread_id, message_id, direction, filename, "
            "content_type, size_bytes, created_at "
            "FROM lp_attachments WHERE thread_id = ? ORDER BY id ASC",
            (int(thread_id),),
        ).fetchall()
        result["attachments"] = [dict(row) for row in attachments]
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
    """Resposta da equipa: guarda PT-BR + versão no idioma do lead e envia."""
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
        lead_lang = _clean(thread["lead_lang"], 8) or "en"
        cur = conn.execute(
            "INSERT INTO lp_messages ("
            "thread_id, direction, channel, body, body_pt, body_en, lang, "
            "author_type, author_id, email_status, created_at"
            ") VALUES (?, 'outbound', 'widget+email', ?, ?, ?, ?, 'team', ?, "
            "'pending', ?)",
            (int(thread_id), en, pt, en, lead_lang, admin_id, _iso(now)),
        )
        message_id = int(cur.lastrowid)
        conn.execute(
            "UPDATE lp_threads SET status = 'replied', updated_at = ?, "
            "last_message_at = ?, draft_pt = NULL, draft_out = NULL, "
            "draft_out_lang = NULL WHERE id = ?",
            (_iso(now), _iso(now), int(thread_id)),
        )
        _event(conn, int(thread_id), "team_reply", {"message_id": message_id})
        conn.commit()
        email = str(thread["email"] or "")
    finally:
        conn.close()

    email_sent = send_email(
        email,
        {
            "pt": "Re: a sua pergunta sobre a Magic Leads",
            "es": "Re: tu pregunta sobre Magic Leads",
        }.get(lead_lang[:2], "Re: your question about Magic Leads"),
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

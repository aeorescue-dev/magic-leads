"""Sincronizacao da caixa de entrada (Gmail readonly): respostas, bounces e
reclamacoes -> supressao automatica.

Requer o scope `https://www.googleapis.com/auth/gmail.readonly` na caixa. Sem
ele o Gmail devolve 403 e o modulo devolve `no_permission` (nunca rebenta).

Deteccao (v1, documentada e conservadora):
  * RECLAMACAO: `Content-Type: message/feedback-report` (ARF) -> extrai o
    destinatario original e suprime + marca a mensagem como falhada.
  * BOUNCE: remetente mailer-daemon/postmaster ou `multipart/report` ->
    extrai `Final-Recipient`/`Original-Rcpt-To` -> suprime + marca falhada.
  * RESPOSTA: remetente igual a um contacto nosso que ja recebeu mensagem ->
    marca `replied_at` (trava a sequencia). Limitacao conhecida: uma resposta
    de outro endereco do mesmo dominio nao e' detetada (exigiria thread_id).
"""

from __future__ import annotations

import base64
import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from ..utils.logger import logger
from .db import get_connection

GMAIL_API = "https://gmail.googleapis.com/gmail/v1"
READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"

_RCPT_RE = re.compile(
    r"(?:Final-Recipient|Original-Rcpt-To|X-Failed-Recipients)\s*:\s*[^;\n]*;\s*([^\s,;<>]+@[^\s,;<>]+)",
    re.I,
)
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

KV_LAST_SYNC = "last_inbox_sync"


# ------------------------------------------------------------------ parsing

def _b64(data: str) -> str:
    try:
        return base64.urlsafe_b64decode(data + "===").decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return ""


def _walk_parts(payload: dict) -> list[dict]:
    parts = [payload]
    for p in payload.get("parts") or []:
        parts.extend(_walk_parts(p))
    return parts


def _body_text(payload: dict, limit: int = 20000) -> str:
    out = []
    for part in _walk_parts(payload):
        data = (part.get("body") or {}).get("data")
        if data:
            out.append(_b64(data))
        if sum(len(x) for x in out) > limit:
            break
    return "\n".join(out)[:limit]


def headers_map(payload: dict) -> dict[str, str]:
    return {
        (h.get("name") or "").lower(): (h.get("value") or "")
        for h in (payload.get("headers") or [])
    }


def parse_report_recipients(text: str) -> list[str]:
    """Extrai destinatarios de um relatorio de bounce/reclamacao."""
    found = [m.group(1).strip().lower() for m in _RCPT_RE.finditer(text or "")]
    if not found:
        found = [e.lower() for e in _EMAIL_RE.findall(text or "")]
    # remove duplicados mantendo a ordem
    seen, out = set(), []
    for e in found:
        if e not in seen:
            seen.add(e)
            out.append(e)
    return out


def classify_message(payload: dict, contact_emails: set[str]) -> tuple[str, Any]:
    """Devolve (kind, detail): kind in {complaint, bounce, reply, other}."""
    hdrs = headers_map(payload)
    ctype = (hdrs.get("content-type") or "").lower()
    sender = (hdrs.get("from") or "").lower()
    body = _body_text(payload)

    if "message/feedback-report" in ctype or "feedback-report" in body[:2000].lower():
        return "complaint", parse_report_recipients(body)

    looks_bounce = (
        "mailer-daemon" in sender
        or "postmaster" in sender
        or "multipart/report" in ctype
        or "undelivered" in (hdrs.get("subject") or "").lower()
        or "delivery status notification" in (hdrs.get("subject") or "").lower()
    )
    if looks_bounce:
        return "bounce", parse_report_recipients(body)

    addr = ""
    m = _EMAIL_RE.search(sender)
    if m:
        addr = m.group(0).lower()
    if addr and addr in contact_emails:
        return "reply", addr
    return "other", None


# ---------------------------------------------------------------- gmail api

def _credentials(mailbox: dict) -> Optional[dict]:
    raw = mailbox.get("auth_ref")
    cid = csec = rt = None
    if raw:
        try:
            d = json.loads(raw)
            cid, csec, rt = d.get("client_id"), d.get("client_secret"), d.get("refresh_token")
        except Exception:  # noqa: BLE001
            pass
    cid = cid or (os.getenv("GMAIL_CLIENT_ID") or "").strip()
    csec = csec or (os.getenv("GMAIL_CLIENT_SECRET") or "").strip()
    # Ambiente > auth_ref (ver gmail._credentials): permite rotacionar tokens
    # sem reescrever a BD.
    local = str(mailbox.get("email") or "").split("@")[0].upper()
    env_rt = (os.getenv(f"GMAIL_REFRESH_TOKEN_{local}") or "").strip()
    if env_rt:
        rt = env_rt
    if not (cid and csec and rt):
        return None
    return {"client_id": cid, "client_secret": csec, "refresh_token": rt}


def _on_mailboxes() -> list[dict]:
    con = get_connection()
    try:
        rows = con.execute(
            "SELECT id, email, auth_ref FROM sending_mailboxes WHERE enabled=1 ORDER BY id"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


async def _access_token(client: httpx.AsyncClient, creds: dict) -> tuple[Optional[str], Optional[str]]:
    """Devolve (token, erro)."""
    try:
        r = await client.post(
            "https://oauth2.googleapis.com/token",
            data={**creds, "grant_type": "refresh_token"},
        )
    except Exception as exc:  # noqa: BLE001
        return None, f"rede: {exc}"
    if r.status_code != 200:
        return None, f"refresh HTTP {r.status_code}"
    return r.json().get("access_token"), None


def _contact_emails() -> tuple[set[str], dict[str, dict]]:
    con = get_connection()
    try:
        rows = con.execute(
            "SELECT id, email, company_name FROM outbound_contacts "
            "WHERE COALESCE(email,'') <> ''"
        ).fetchall()
        by_email = {r["email"].lower(): dict(r) for r in rows}
        return set(by_email), by_email
    finally:
        con.close()


def _mark_replied(contact_id: int) -> None:
    con = get_connection()
    try:
        con.execute(
            "UPDATE outbound_contacts SET replied_at=CURRENT_TIMESTAMP WHERE id=?",
            (contact_id,),
        )
        con.commit()
    finally:
        con.close()


def _suppress(email: str, reason: str) -> None:
    con = get_connection()
    try:
        con.execute(
            "INSERT OR IGNORE INTO suppressions (value, channel, reason) VALUES (?, 'email', ?)",
            (email.lower(), reason),
        )
        con.execute(
            "UPDATE outbound_contacts SET unsubscribed=1 WHERE lower(email)=?",
            (email.lower(),),
        )
        con.execute(
            "UPDATE outbound_messages SET status='failed', error=? "
            "WHERE lower(to_email)=? AND status IN ('queued','sending')",
            (reason, email.lower()),
        )
        con.commit()
    finally:
        con.close()


def _kv_set(key: str, value: str) -> None:
    con = get_connection()
    try:
        con.execute(
            "INSERT INTO system_kv (key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key, value, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")),
        )
        con.commit()
    finally:
        con.close()


# --------------------------------------------------------------------- sync

async def sync_inbox(days: int = 2, max_messages: int = 40) -> dict:
    """Le a inbox e aplica respostas/bounces/reclamacoes. Nunca levanta."""
    mailboxes = _on_mailboxes()
    if not mailboxes:
        return {"status": "skipped", "reason": "sem caixas ativas"}

    emails, by_email = _contact_emails()
    stats = {"mailboxes": 0, "scanned": 0, "replies": 0, "bounces": 0,
             "complaints": 0, "no_permission": 0, "errors": []}

    async with httpx.AsyncClient(timeout=30.0) as client:
        for mb in mailboxes:
            creds = _credentials(mb)
            if not creds:
                stats["errors"].append(f"{mb['email']}: sem credenciais")
                continue
            token, err = await _access_token(client, creds)
            if not token:
                stats["errors"].append(f"{mb['email']}: {err}")
                continue

            stats["mailboxes"] += 1
            try:
                r = await client.get(
                    f"{GMAIL_API}/users/{mb['email']}/messages",
                    headers={"Authorization": f"Bearer {token}"},
                    params={"q": f"in:inbox newer_than:{days}d", "maxResults": max_messages},
                )
            except Exception as exc:  # noqa: BLE001
                stats["errors"].append(f"{mb['email']}: {exc}")
                continue

            if r.status_code == 403:
                stats["no_permission"] += 1
                stats["errors"].append(
                    f"{mb['email']}: sem scope gmail.readonly (reautorizar)"
                )
                continue
            if r.status_code != 200:
                stats["errors"].append(f"{mb['email']}: list HTTP {r.status_code}")
                continue

            for ref in (r.json().get("messages") or []):
                mid = ref.get("id")
                if not mid:
                    continue
                try:
                    mr = await client.get(
                        f"{GMAIL_API}/users/{mb['email']}/messages/{mid}",
                        headers={"Authorization": f"Bearer {token}"},
                        params={"format": "full"},
                    )
                except Exception:  # noqa: BLE001
                    continue
                if mr.status_code != 200:
                    continue
                stats["scanned"] += 1
                payload = (mr.json() or {}).get("payload") or {}
                kind, detail = classify_message(payload, emails)

                if kind == "reply":
                    contact = by_email.get(str(detail))
                    if contact:
                        _mark_replied(contact["id"])
                        stats["replies"] += 1
                elif kind in ("bounce", "complaint"):
                    recipients = detail or []
                    for addr in recipients:
                        if addr in by_email:
                            _suppress(addr, kind)
                            stats["bounces" if kind == "bounce" else "complaints"] += 1

    _kv_set(KV_LAST_SYNC, "ok")
    if stats["replies"] or stats["bounces"] or stats["complaints"]:
        logger.info("[INBOX] sync: %s", stats)
    return {"status": "ok", **stats}

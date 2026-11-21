"""SMS transacional via Telnyx (10DLC) — envio, supressao e inbound.

Regras:
* So envia quando `VOICE_FREEZE` esta desligado e a campanha 10DLC esta
  aprovada/activa; caso contrario devolve o motivo e nao chama a Telnyx.
* Usa sempre o numero SMS (nunca o DID de voz).
* STOP/STOPALL/UNSUBSCRIBE/CANCEL/END/QUIT suprimem o numero; START/YES/UNSTOP
  removem a supressao. HELP/INFO nao gera resposta duplicada (a Telnyx/carrier
  responde com a mensagem da campanha).
* Tudo fica registado em `voice.db` (`sms_messages`, `sms_suppressions`).
"""
from __future__ import annotations

import logging
import re
import sqlite3
import time
from datetime import datetime, timezone
from typing import Optional

import httpx

from ..config import settings
from . import b2b_voice

logger = logging.getLogger(__name__)

API_BASE = "https://api.telnyx.com/v2"

SMS_TEXT = (
    "Magic Leads: here is the link you requested during your call: "
    "https://magicleads.app. Reply STOP to opt out, HELP for help. "
    "Msg&data rates may apply."
)

OPT_OUT_KEYWORDS = {"STOP", "STOPALL", "UNSUBSCRIBE", "CANCEL", "END", "QUIT"}
OPT_IN_KEYWORDS = {"START", "YES", "UNSTOP"}
HELP_KEYWORDS = {"HELP", "INFO"}

_CAMPAIGN_TTL_SECONDS = 300
_campaign_cache: dict = {"at": 0.0, "value": None}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_phone(value: str) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) == 10:
        return "+1" + digits
    if len(digits) == 11 and digits.startswith("1"):
        return "+" + digits
    if 11 <= len(digits) <= 15:
        return "+" + digits
    return ""


def sms_from_number() -> str:
    return normalize_phone(getattr(settings, "TELNYX_SMS_FROM_NUMBER", "") or "")


def profile_id() -> str:
    return str(getattr(settings, "TELNYX_MESSAGING_PROFILE_ID", "") or "").strip()


def campaign_id() -> str:
    return str(getattr(settings, "TELNYX_SMS_CAMPAIGN_ID", "") or "").strip()


def configured() -> bool:
    return bool(
        getattr(settings, "TELNYX_API_KEY", "")
        and sms_from_number()
        and profile_id()
        and campaign_id()
    )


def _auth_headers() -> dict:
    return {
        "Authorization": f"Bearer {settings.TELNYX_API_KEY}",
        "Content-Type": "application/json",
    }


def get_conn() -> sqlite3.Connection:
    b2b_voice.init()
    conn = b2b_voice.get_conn()
    conn.row_factory = sqlite3.Row
    _ensure_schema(conn)
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS sms_messages (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          direction TEXT NOT NULL CHECK (direction IN ('out','in')),
          phone TEXT NOT NULL,
          from_number TEXT,
          body TEXT,
          provider_id TEXT,
          status TEXT,
          error TEXT,
          trigger TEXT,
          created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_sms_messages_phone
          ON sms_messages (phone, created_at DESC);
        CREATE TABLE IF NOT EXISTS sms_suppressions (
          phone TEXT PRIMARY KEY,
          reason TEXT,
          created_at TEXT NOT NULL
        );
        """
    )
    conn.commit()


def is_suppressed(phone: str) -> bool:
    normalized = normalize_phone(phone)
    if not normalized:
        return True
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT 1 FROM sms_suppressions WHERE phone=?", (normalized,)
        ).fetchone()
        if row:
            return True
        return bool(
            conn.execute(
                "SELECT 1 FROM voice_suppressions WHERE value=? AND channel='phone'",
                (normalized,),
            ).fetchone()
        )
    finally:
        conn.close()


def suppress(phone: str, reason: str = "sms_stop") -> dict:
    normalized = normalize_phone(phone)
    if not normalized:
        return {"ok": False, "reason": "invalid_phone"}
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO sms_suppressions (phone, reason, created_at) VALUES (?,?,?) "
            "ON CONFLICT(phone) DO UPDATE SET reason=excluded.reason",
            (normalized, reason, _now()),
        )
        conn.commit()
    finally:
        conn.close()
    try:
        b2b_voice.suppress(normalized, reason=reason)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[SMS] falha ao suprimir na voz: %s", exc)
    return {"ok": True, "phone": normalized, "suppressed": True}


def unsuppress(phone: str) -> dict:
    normalized = normalize_phone(phone)
    if not normalized:
        return {"ok": False, "reason": "invalid_phone"}
    conn = get_conn()
    try:
        conn.execute("DELETE FROM sms_suppressions WHERE phone=?", (normalized,))
        conn.commit()
    finally:
        conn.close()
    try:
        b2b_voice.clear_suppression(normalized)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[SMS] falha ao limpar supressao de voz: %s", exc)
    return {"ok": True, "phone": normalized, "suppressed": False}


def campaign_status(force: bool = False) -> Optional[str]:
    """Estado Telnyx da campanha, com cache curto (None se nao configurada)."""
    cid = campaign_id()
    if not cid or not getattr(settings, "TELNYX_API_KEY", ""):
        return None
    now = time.time()
    if not force and _campaign_cache["value"] and now - _campaign_cache["at"] < _CAMPAIGN_TTL_SECONDS:
        return _campaign_cache["value"]
    try:
        response = httpx.get(
            f"{API_BASE}/10dlc/campaign/{cid}",
            headers=_auth_headers(),
            timeout=15,
        )
        data = response.json() if response.status_code < 300 else {}
        status = str(
            data.get("campaignStatus") or data.get("submissionStatus") or data.get("status") or ""
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[SMS] campanha: leitura falhou: %s", type(exc).__name__)
        status = ""
    _campaign_cache["at"] = now
    _campaign_cache["value"] = status or None
    return _campaign_cache["value"] or None


def campaign_ready() -> bool:
    return str(campaign_status() or "").upper() in {"ACTIVE", "APPROVED", "TCR_APPROVED"}


def _outbound_today() -> int:
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT COUNT(*) c FROM sms_messages "
            "WHERE direction='out' AND status IN ('queued','sent') "
            "AND date(created_at)=date('now')"
        ).fetchone()
        return int(row["c"] or 0)
    finally:
        conn.close()


def _record(
    direction: str,
    phone: str,
    body: str,
    *,
    provider_id: Optional[str] = None,
    status: Optional[str] = None,
    error: Optional[str] = None,
    trigger: Optional[str] = None,
    from_number: Optional[str] = None,
) -> None:
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO sms_messages "
            "(direction, phone, from_number, body, provider_id, status, error, trigger, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                direction,
                normalize_phone(phone) or str(phone or ""),
                from_number,
                body,
                provider_id,
                status,
                error,
                trigger,
                _now(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def send_sms(
    phone: str,
    body: str,
    *,
    trigger: str = "manual",
    bypass_freeze: bool = False,
) -> dict:
    """Envia um SMS unico; nunca levanta excecao para o caller."""
    normalized = normalize_phone(phone)
    if not normalized:
        return {"ok": False, "reason": "invalid_phone"}
    if not configured():
        return {"ok": False, "reason": "not_configured"}
    if bool(getattr(settings, "VOICE_FREEZE", True)) and not bypass_freeze:
        _record(
            "out",
            normalized,
            body,
            status="frozen",
            error="voice_freeze",
            trigger=trigger,
            from_number=sms_from_number(),
        )
        return {"ok": False, "reason": "frozen"}
    if is_suppressed(normalized):
        _record(
            "out",
            normalized,
            body,
            status="suppressed",
            error="suppressed",
            trigger=trigger,
            from_number=sms_from_number(),
        )
        return {"ok": False, "reason": "suppressed"}
    if not campaign_ready():
        _record(
            "out",
            normalized,
            body,
            status="blocked",
            error="campaign_pending",
            trigger=trigger,
            from_number=sms_from_number(),
        )
        return {"ok": False, "reason": "campaign_pending", "campaign": campaign_status()}
    cap = int(getattr(settings, "TELNYX_SMS_MAX_PER_DAY", 50) or 50)
    if _outbound_today() >= cap:
        return {"ok": False, "reason": "daily_cap"}

    payload = {
        "from": sms_from_number(),
        "to": normalized,
        "text": str(body or "")[:1600],
        "messaging_profile_id": profile_id(),
        "type": "SMS",
        "use_profile_webhooks": True,
    }
    try:
        response = httpx.post(
            f"{API_BASE}/messages", json=payload, headers=_auth_headers(), timeout=20
        )
    except Exception as exc:  # noqa: BLE001
        _record(
            "out",
            normalized,
            body,
            status="error",
            error=f"{type(exc).__name__}",
            trigger=trigger,
            from_number=sms_from_number(),
        )
        return {"ok": False, "reason": "network_error"}
    if response.status_code >= 300:
        detail = response.text[:300]
        _record(
            "out",
            normalized,
            body,
            status="error",
            error=f"http_{response.status_code}: {detail}",
            trigger=trigger,
            from_number=sms_from_number(),
        )
        return {"ok": False, "reason": f"http_{response.status_code}", "detail": detail}

    data = (response.json() or {}).get("data", {})
    provider_id = str(data.get("id") or "")
    status = str(data.get("status") or "queued")
    _record(
        "out",
        normalized,
        body,
        provider_id=provider_id,
        status=status,
        trigger=trigger,
        from_number=sms_from_number(),
    )
    return {"ok": True, "id": provider_id, "status": status}


def handle_inbound(payload: dict) -> dict:
    """Processa webhooks de mensagens da Telnyx (inbound e status)."""
    data = payload.get("data") if isinstance(payload, dict) else {}
    data = data if isinstance(data, dict) else {}
    event_type = str(data.get("event_type") or payload.get("event_type") or "").lower()
    body = data.get("payload") if isinstance(data.get("payload"), dict) else {}
    body = body or payload

    if "message.received" not in event_type and "message.finalized" not in event_type:
        return {"ok": True, "action": "ignored", "event_type": event_type}

    from_obj = body.get("from") or {}
    phone = (
        from_obj.get("phone_number")
        if isinstance(from_obj, dict)
        else str(from_obj or "")
    ) or body.get("from_phone_number") or ""
    text = str(body.get("text") or "").strip()
    provider_id = str(body.get("id") or data.get("id") or "")

    if "message.finalized" in event_type:
        _record(
            "out",
            phone,
            text,
            provider_id=provider_id,
            status="sent" if str(body.get("status") or "").upper() in {"SENT", "DELIVERED"} else "finalized",
            trigger="webhook",
            from_number=sms_from_number() or None,
        )
        return {"ok": True, "action": "finalized", "status": body.get("status")}

    _record(
        "in",
        phone,
        text,
        provider_id=provider_id,
        status="received",
        trigger="inbound",
        from_number=sms_from_number() or None,
    )
    keyword = re.sub(r"[^A-Z]", "", text.upper())[:20]
    if keyword in OPT_OUT_KEYWORDS:
        suppress(phone, reason="sms_stop")
        return {"ok": True, "action": "opt_out", "phone": normalize_phone(phone)}
    if keyword in OPT_IN_KEYWORDS:
        unsuppress(phone)
        return {"ok": True, "action": "opt_in", "phone": normalize_phone(phone)}
    if keyword in HELP_KEYWORDS:
        return {"ok": True, "action": "help"}
    return {"ok": True, "action": "stored", "keyword": keyword}


def status() -> dict:
    return {
        "configured": configured(),
        "from": sms_from_number() or None,
        "profile_id": profile_id() or None,
        "campaign_id": campaign_id() or None,
        "campaign_status": campaign_status(force=True),
        "campaign_ready": campaign_ready(),
        "frozen": bool(getattr(settings, "VOICE_FREEZE", True)),
    }

"""Adaptador Telnyx Voice AI — Fase 2A.

Sem `TELNYX_API_KEY`/`TELNYX_CONNECTION_ID`/`TELNYX_FROM_NUMBER`, o adaptador
funciona em dry-run e regista a chamada em `voice_calls` sem gastar dinheiro.

O webhook aceita um segredo partilhado (`?secret=` ou header
`x-webhook-secret`). Em produção deve ser substituído/ complementado pela
verificação Ed25519 da Telnyx.
"""
from __future__ import annotations

import base64
import hmac
import json
import math
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import quote

import httpx

from ..config import settings
from ..utils.logger import logger
from . import b2b_voice, showcase

API_BASE = "https://api.telnyx.com/v2"


def configured() -> bool:
    return bool(
        getattr(settings, "TELNYX_API_KEY", "")
        and getattr(settings, "TELNYX_CONNECTION_ID", "")
        and getattr(settings, "TELNYX_FROM_NUMBER", "")
    )


def _webhook_url() -> str:
    base = (
        getattr(settings, "TELNYX_WEBHOOK_URL", "")
        or f"{getattr(settings, 'PUBLIC_API_URL', '').rstrip('/')}/api/voice/telnyx/webhook"
    )
    secret = getattr(settings, "TELNYX_WEBHOOK_SECRET", "")
    if secret:
        sep = "&" if "?" in base else "?"
        base = f"{base}{sep}secret={quote(secret)}"
    return base


def _encode_state(payload: dict) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.b64encode(raw).decode("ascii")


def _decode_state(value: Any) -> dict:
    if not value:
        return {}
    try:
        raw = base64.b64decode(str(value)).decode("utf-8")
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def create_call(
    company: dict,
    campaign_id: str = "",
    script_id: str = "",
    city: Optional[str] = None,
    trade_code: Optional[str] = None,
    dry_run: bool = False,
) -> dict:
    """Cria uma chamada Telnyx para uma empresa já validada pelo gate."""
    eligibility = b2b_voice.can_call(company)
    if not eligibility["allowed"]:
        return {
            "ok": False,
            "reason": "blocked",
            "reasons": eligibility["reasons"],
            "reason_labels": eligibility["reason_labels"],
        }

    trade = showcase.normalize_trade(trade_code or company.get("trade"))
    call = b2b_voice.create_voice_call(
        company,
        provider="telnyx",
        campaign_id=campaign_id,
        script_id=script_id,
        city=city or company.get("city"),
        trade_code=trade,
    )
    if not configured() or dry_run:
        b2b_voice.update_voice_call(call["id"], status="dry_run")
        return {
            "ok": True,
            "dry_run": True,
            "voice_call_id": call["id"],
            "status": "dry_run",
            "message": (
                "Dry-run forçado pela campanha."
                if dry_run
                else "Telnyx não configurado; chamada registada em dry-run."
            ),
        }

    state = _encode_state(
        {
            "voice_call_id": call["id"],
            "company_id": call["company_id"],
            "city": call.get("city"),
            "trade_code": call.get("trade_code"),
            "campaign_id": campaign_id,
        }
    )
    payload = {
        "connection_id": settings.TELNYX_CONNECTION_ID,
        "to": company["phone"],
        "from": settings.TELNYX_FROM_NUMBER,
        "webhook_url": _webhook_url(),
        "client_state": state,
        "timeout_secs": 30,
    }
    try:
        resp = httpx.post(
            f"{API_BASE}/calls",
            headers={
                "Authorization": f"Bearer {settings.TELNYX_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=20,
        )
    except Exception as exc:  # noqa: BLE001
        b2b_voice.update_voice_call(call["id"], status="failed")
        logger.warning("[TELNYX] Falha de rede ao criar chamada: %s", type(exc).__name__)
        return {"ok": False, "reason": "network_error", "voice_call_id": call["id"]}

    if resp.status_code >= 300:
        b2b_voice.update_voice_call(call["id"], status="failed")
        logger.warning("[TELNYX] HTTP %s ao criar chamada", resp.status_code)
        return {
            "ok": False,
            "reason": f"http_{resp.status_code}",
            "voice_call_id": call["id"],
        }

    data = resp.json() if resp.content else {}
    body = data.get("data") if isinstance(data, dict) else {}
    provider_call_id = (
        (body or {}).get("call_control_id")
        or (body or {}).get("call_leg_id")
        or data.get("call_control_id")
    )
    b2b_voice.update_voice_call(
        call["id"],
        status="dialing",
        provider_call_id=provider_call_id,
    )
    return {
        "ok": True,
        "dry_run": False,
        "voice_call_id": call["id"],
        "provider_call_id": provider_call_id,
        "status": "dialing",
    }


def verify_secret(secret: Optional[str]) -> bool:
    expected = getattr(settings, "TELNYX_WEBHOOK_SECRET", "")
    if not expected:
        # Fail-closed em produção. Em testes, define TELNYX_WEBHOOK_SECRET.
        return bool(getattr(settings, "DEBUG", False))
    return bool(secret) and hmac.compare_digest(str(expected), str(secret))


def handle_webhook(payload: dict) -> dict:
    """Normaliza eventos Telnyx e executa a ação de showcase no DTMF 1."""
    data = payload.get("data") if isinstance(payload, dict) else {}
    data = data if isinstance(data, dict) else {}
    event_type = str(
        data.get("event_type") or payload.get("event_type") or ""
    ).lower()
    body = data.get("payload") if isinstance(data.get("payload"), dict) else {}
    body = body or (payload.get("payload") if isinstance(payload.get("payload"), dict) else {})
    state = _decode_state(
        body.get("client_state") or data.get("client_state") or payload.get("client_state")
    )
    voice_call_id = state.get("voice_call_id")
    if not voice_call_id:
        return {"ok": False, "reason": "missing_voice_call_id", "event_type": event_type}

    try:
        voice_call_id = int(voice_call_id)
    except (TypeError, ValueError):
        return {"ok": False, "reason": "invalid_voice_call_id", "event_type": event_type}

    if "dtmf" in event_type:
        digit = str(body.get("dtmf_digit") or body.get("digit") or "").strip()
        if digit == "1":
            b2b_voice.update_voice_call(
                voice_call_id, intent="showcase", status="in_call"
            )
            sent = send_showcase_for_call(voice_call_id)
            return {
                "ok": True,
                "action": "showcase",
                "voice_call_id": voice_call_id,
                "digit": digit,
                "showcase": sent,
            }
        return {
            "ok": True,
            "action": "dtmf",
            "voice_call_id": voice_call_id,
            "digit": digit,
        }

    if "answered" in event_type:
        b2b_voice.update_voice_call(
            voice_call_id,
            status="in_call",
            answered_at=datetime.now(timezone.utc).isoformat(),
        )
    elif "hangup" in event_type or "call.ended" in event_type or "ended" in event_type:
        current = b2b_voice.get_voice_call(voice_call_id) or {}
        duration = int(body.get("duration_seconds") or 0)
        if not duration:
            millis = body.get("duration_millis") or body.get("duration_ms")
            if millis:
                try:
                    duration = int(round(float(millis) / 1000.0))
                except (TypeError, ValueError):
                    duration = 0
        answered = bool(current.get("answered_at"))
        cost_cents = 0
        if duration > 0:
            cost_cents = (
                math.ceil(duration / 60.0)
                * int(getattr(settings, "TELNYX_COST_PER_MINUTE_CENTS", 2))
            )
        b2b_voice.update_voice_call(
            voice_call_id,
            status="ended",
            ended_at=datetime.now(timezone.utc).isoformat(),
            duration_seconds=duration,
            listen_seconds=duration if answered else 0,
            hangup_cause=str(
                body.get("hangup_cause")
                or body.get("sip_hangup_cause")
                or body.get("cause")
                or ""
            )[:120],
            cost_cents=cost_cents,
        )
    return {"ok": True, "action": "status", "event_type": event_type}


def send_showcase_for_call(
    voice_call_id: int,
    city: Optional[str] = None,
    trade_code: Optional[str] = None,
) -> dict:
    """Cria o link da vitrine e envia o email para a empresa da chamada."""
    call = b2b_voice.get_voice_call(voice_call_id)
    if not call:
        return {"ok": False, "reason": "call_not_found"}
    company = b2b_voice.get_company(call["company_id"])
    if not company:
        return {"ok": False, "reason": "company_not_found"}

    resolved_city = city or call.get("city") or company.get("city")
    resolved_trade = showcase.normalize_trade(
        trade_code or call.get("trade_code") or company.get("trade")
    )
    if not resolved_city or not resolved_trade:
        return {"ok": False, "reason": "missing_city_or_trade"}

    page = showcase.get_page(showcase.slugify(resolved_city), resolved_trade)
    if not page:
        return {"ok": False, "reason": "no_inventory"}

    email = (company.get("email") or "").strip()
    link = showcase.create_link(
        company_id=int(company["id"]),
        email=email,
        city=resolved_city,
        trade_code=resolved_trade,
        company_name=company.get("company_name") or "",
        voice_call_id=voice_call_id,
        campaign_id=str(call.get("campaign_id") or ""),
    )
    page_data = page["page"]
    fallback = page_data.get("fallback")
    email_city = page_data.get("city") or resolved_city
    page_trade = page_data.get("trade_code") or resolved_trade
    scope_label = (
        "active property"
        if fallback == "city"
        else showcase.trade_label(page_trade)
    )
    email_result = showcase.send_showcase_email(
        to_email=email,
        company_name=company.get("company_name") or "",
        city=email_city,
        trade_code=page_trade,
        count=int(page_data["count"]),
        link_url=link["url"],
        scope_label=scope_label,
    )
    b2b_voice.update_voice_call(
        voice_call_id, showcase_link_id=link["link_id"], status="showcase_sent"
    )
    return {
        "ok": True,
        "link": link,
        "email": email_result,
        "page": page["page"],
    }

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
import re
import time
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import quote

import httpx

from ..config import settings
from ..utils.logger import logger
from . import b2b_voice, showcase

API_BASE = "https://api.telnyx.com/v2"


def configured() -> bool:
    if bool(getattr(settings, "VOICE_STAGING_MODE", False)):
        return False
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
    eligibility = b2b_voice.can_call(
        company, allow_international=(campaign_id == "test_call")
    )
    if not eligibility["allowed"]:
        return {
            "ok": False,
            "reason": "blocked",
            "reasons": eligibility["reasons"],
            "reason_labels": eligibility["reason_labels"],
        }

    trade = showcase.normalize_trade(trade_code or company.get("trade"))
    from . import voice_scripts

    script = (
        voice_scripts.approved_for_trade(
            trade, city or company.get("city") or "", company.get("state") or ""
        )
        if trade
        else None
    )
    assistant_id = (script or {}).get("assistant_id") or ""
    staging = bool(getattr(settings, "VOICE_STAGING_MODE", False))
    if configured() and not dry_run:
        if not script:
            return {
                "ok": False,
                "reason": "script_not_approved",
                "message": "Roteiro aprovado é obrigatório para chamadas reais.",
            }
        if not assistant_id:
            return {
                "ok": False,
                "reason": "assistant_missing",
                "message": (
                    "Roteiro aprovado sem assistant_id Telnyx; sincroniza o "
                    "assistant antes de ligar."
                ),
            }
    call = b2b_voice.create_voice_call(
        company,
        provider="telnyx",
        campaign_id=campaign_id,
        script_id=(script or {}).get("trade_code") or script_id,
        city=city or company.get("city"),
        trade_code=trade,
        assistant_id=assistant_id,
    )
    if not configured() or dry_run:
        b2b_voice.update_voice_call(call["id"], status="dry_run")
        return {
            "ok": True,
            "dry_run": True,
            "voice_call_id": call["id"],
            "status": "dry_run",
            "message": (
                "Staging mode: chamada registada em dry-run."
                if staging
                else (
                    "Dry-run forçado pela campanha."
                    if dry_run
                    else "Telnyx não configurado; chamada registada em dry-run."
                )
            ),
        }

    state = _encode_state(
        {
            "voice_call_id": call["id"],
            "company_id": call["company_id"],
            "company_name": company.get("company_name") or "",
            "city": call.get("city"),
            "state": company.get("state") or "",
            "permit_count": int(company.get("permit_count") or 0),
            "trade_code": call.get("trade_code"),
            "campaign_id": campaign_id,
            "assistant_id": assistant_id,
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


def verify_signature(
    signature: str, timestamp: str, raw_body: bytes, tolerance_seconds: int = 300
) -> bool:
    """Verifica a assinatura Ed25519 oficial da Telnyx.

    A Telnyx assina `"{timestamp}|{raw_body}"` e envia os headers
    `telnyx-signature-ed25519` e `telnyx-timestamp`.
    """
    public_key = str(getattr(settings, "TELNYX_PUBLIC_KEY", "") or "").strip()
    if not public_key or not signature or not timestamp:
        return False
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PublicKey,
        )

        ts = int(str(timestamp).strip())
        if abs(time.time() - ts) > int(tolerance_seconds):
            return False
        key = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key))
        key.verify(
            base64.b64decode(signature),
            str(timestamp).strip().encode("ascii") + b"|" + raw_body,
        )
        return True
    except Exception:  # noqa: BLE001
        return False


def webhook_authorized(
    shared_secret: Optional[str],
    signature: str = "",
    timestamp: str = "",
    raw_body: bytes = b"",
) -> bool:
    """Aceita assinatura Ed25519 quando configurada; senão, segredo partilhado."""
    if str(getattr(settings, "TELNYX_PUBLIC_KEY", "") or "").strip():
        if verify_signature(signature, timestamp, raw_body):
            return True
        # Tool calls e testes internos continuam a usar o segredo partilhado.
        return verify_secret(shared_secret)
    return verify_secret(shared_secret)


def _call_action(call_control_id: str, action: str, payload: dict) -> dict:
    if not configured() or not call_control_id:
        return {"ok": False, "reason": "not_configured"}
    try:
        response = httpx.post(
            f"{API_BASE}/calls/{call_control_id}/actions/{action}",
            headers={
                "Authorization": f"Bearer {settings.TELNYX_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=15,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[TELNYX] ação %s falhou: %s", action, type(exc).__name__)
        return {"ok": False, "reason": "network_error"}
    if response.status_code >= 300:
        logger.warning(
            "[TELNYX] ação %s HTTP %s", action, response.status_code
        )
        return {"ok": False, "reason": f"http_{response.status_code}"}
    return {"ok": True}


def start_ai_assistant(
    call_control_id: str,
    assistant_id: str,
    *,
    instructions: str = "",
    greeting: str = "",
    voice: str = "",
    dynamic_variables: Optional[dict] = None,
) -> dict:
    """Arranca o assistant com o script já renderizado para esta chamada."""
    if not assistant_id:
        return {"ok": False, "reason": "missing_assistant_id"}
    assistant: dict[str, Any] = {"id": assistant_id}
    if instructions:
        assistant["instructions"] = instructions[:12000]
    if greeting:
        assistant["greeting"] = greeting[:3000]
    if voice:
        assistant["voice_settings"] = {"voice": voice}
    if dynamic_variables:
        assistant["dynamic_variables"] = dynamic_variables
    return _call_action(
        call_control_id, "ai_assistant_start", {"assistant": assistant}
    )


def hangup_call(call_control_id: str) -> dict:
    return _call_action(call_control_id, "hangup", {})


def _render_for_call(current: dict, client_state: dict) -> dict:
    """Renderiza o script aprovado para esta chamada (override incluído)."""
    from . import voice_scripts

    trade = (
        current.get("trade_code")
        or client_state.get("trade_code")
        or ""
    )
    if not trade:
        return {}
    company_id = current.get("company_id") or client_state.get("company_id")
    company = b2b_voice.get_company(company_id) if company_id else {}
    company = company or {}
    company_name = (
        company.get("company_name")
        or client_state.get("company_name")
        or ""
    )
    city = current.get("city") or client_state.get("city") or company.get("city") or ""
    state = company.get("state") or client_state.get("state") or ""
    permit_count = int(
        company.get("permit_count") or client_state.get("permit_count") or 0
    )
    try:
        return voice_scripts.render(
            trade,
            company=company_name,
            city=city,
            permit_count=permit_count,
            state=state,
            email=str(company.get("email") or ""),
        )
    except ValueError:
        return {}


def _valid_email(value: Any) -> str:
    email = str(value or "").strip().lower()
    if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        return email
    return ""


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in ("1", "true", "yes", "y")


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
            # O assistant recebe o DTMF como texto e pergunta o email; o envio
            # acontece na tool capture_email para não duplicar emails.
            b2b_voice.update_voice_call(voice_call_id, intent="showcase")
            return {
                "ok": True,
                "action": "dtmf_yes",
                "voice_call_id": voice_call_id,
                "digit": digit,
            }
        return {
            "ok": True,
            "action": "dtmf",
            "voice_call_id": voice_call_id,
            "digit": digit,
        }

    if "answered" in event_type:
        current = b2b_voice.get_voice_call(voice_call_id) or {}
        b2b_voice.update_voice_call(
            voice_call_id,
            status="in_call",
            answered_at=datetime.now(timezone.utc).isoformat(),
        )
        call_control_id = str(
            body.get("call_control_id") or current.get("provider_call_id") or ""
        )
        assistant_id = str(current.get("assistant_id") or "")
        assistant_result = None
        if configured() and call_control_id:
            if assistant_id:
                rendered = _render_for_call(current, state)
                assistant_result = start_ai_assistant(
                    call_control_id,
                    assistant_id,
                    instructions=str(rendered.get("instructions") or ""),
                    greeting=str(rendered.get("greeting") or ""),
                    voice=str(rendered.get("voice_id") or ""),
                )
                if not assistant_result.get("ok"):
                    b2b_voice.update_voice_call(
                        voice_call_id,
                        status="ended",
                        hangup_cause="assistant_start_failed",
                    )
                    hangup_call(call_control_id)
            else:
                # Segurança: nunca deixar uma chamada real em silêncio.
                b2b_voice.update_voice_call(
                    voice_call_id,
                    status="ended",
                    hangup_cause="missing_assistant",
                )
                hangup_call(call_control_id)
        return {
            "ok": True,
            "action": "answered",
            "voice_call_id": voice_call_id,
            "assistant_started": bool(
                assistant_result and assistant_result.get("ok")
            ),
        }
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
    email: Optional[str] = None,
) -> dict:
    """Cria o link da vitrine e envia o email para a empresa da chamada."""
    call = b2b_voice.get_voice_call(voice_call_id)
    if not call:
        return {"ok": False, "reason": "call_not_found"}
    company = (
        b2b_voice.get_company(call["company_id"])
        if call.get("company_id")
        else None
    )
    company = company or {}

    resolved_city = city or call.get("city") or company.get("city")
    resolved_trade = showcase.normalize_trade(
        trade_code or call.get("trade_code") or company.get("trade")
    )
    if not resolved_city or not resolved_trade:
        return {"ok": False, "reason": "missing_city_or_trade"}

    page = showcase.get_page(showcase.slugify(resolved_city), resolved_trade)
    if not page:
        return {"ok": False, "reason": "no_inventory"}

    to_email = _valid_email(email) or _valid_email(company.get("email"))
    if not to_email:
        return {
            "ok": False,
            "reason": "email_required",
            "message": "Ask the caller for the best email address.",
        }

    link = showcase.create_link(
        company_id=int(call.get("company_id") or 0),
        email=to_email,
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
        to_email=to_email,
        company_name=company.get("company_name") or "",
        city=email_city,
        trade_code=page_trade,
        count=int(page_data["count"]),
        link_url=link["url"],
        scope_label=scope_label,
    )
    b2b_voice.update_voice_call(
        voice_call_id,
        showcase_link_id=link["link_id"],
        status="showcase_sent",
        intent="showcase",
    )
    campaign_id = str(call.get("campaign_id") or "")
    if campaign_id.isdigit():
        # Mantem a metrica da campanha mesmo com o envio pos-consentimento.
        b2b_voice.bump_campaign(int(campaign_id), 0, 1, 0)
    return {
        "ok": True,
        "link": link,
        "email": email_result,
        "page": page["page"],
    }


def handle_tool_call(
    tool_name: str, payload: dict, call_control_id: str
) -> dict:
    """Executa os webhook tools do assistant, correlacionados pelo call id."""
    call = b2b_voice.get_voice_call_by_provider_id(call_control_id)
    if not call:
        return {
            "ok": False,
            "error": "call_not_found",
            "message": "This call is not registered.",
        }
    voice_call_id = int(call["id"])
    company_id = int(call.get("company_id") or 0)
    name = str(tool_name or "").strip()

    if name == "mark_acceptance":
        b2b_voice.update_voice_call(voice_call_id, intent="showcase")
        return {"ok": True, "message": "Acceptance recorded."}

    if name == "send_showcase_link":
        company = b2b_voice.get_company(company_id) if company_id else {}
        on_file = _valid_email((company or {}).get("email"))
        if not on_file:
            return {
                "ok": False,
                "reason": "email_required",
                "message": (
                    "There is no email on file. Ask the caller for the best "
                    "email address, read it back, and use capture_email."
                ),
            }
        confirmed = _valid_email(payload.get("confirmed_email"))
        if confirmed != on_file:
            return {
                "ok": False,
                "reason": "email_confirmation_mismatch",
                "email_on_file": on_file,
                "message": (
                    f"The email on file is {on_file}. Confirm that exact "
                    "address with the caller before sending."
                ),
            }
        result = send_showcase_for_call(voice_call_id)
        if result.get("ok"):
            return {
                "ok": True,
                "message": "The showcase link was sent to the confirmed email.",
            }
        if result.get("reason") == "email_required":
            return {
                "ok": False,
                "reason": "email_required",
                "message": "Ask the caller for the best email address.",
            }
        return {
            "ok": False,
            "reason": str(result.get("reason") or "send_failed"),
            "message": "I could not send the link automatically.",
        }

    if name == "capture_email":
        email = _valid_email(payload.get("email") or payload.get("address"))
        if not email:
            return {
                "ok": False,
                "reason": "invalid_email",
                "message": (
                    "That email did not sound valid. Ask the caller to repeat "
                    "it slowly."
                ),
            }
        if not _truthy(payload.get("confirmed")):
            return {
                "ok": False,
                "reason": "email_not_confirmed",
                "email": email,
                "message": (
                    "Read the address back and ask \"Is that correct?\" before "
                    "saving or sending."
                ),
            }
        if company_id:
            b2b_voice.set_company_email(company_id, email)
        result = send_showcase_for_call(voice_call_id, email=email)
        return {
            "ok": bool(result.get("ok")),
            "email": email,
            "message": (
                "The showcase link is on its way to that email."
                if result.get("ok")
                else "The email was saved, but the link could not be sent."
            ),
        }

    if name == "remove_from_list":
        b2b_voice.update_voice_call(voice_call_id, intent="opt_out")
        if company_id:
            phone = str((b2b_voice.get_company(company_id) or {}).get("phone") or "")
            if phone:
                b2b_voice.suppress(phone, reason="caller_opt_out")
            b2b_voice.mark_company_do_not_call(company_id)
        return {
            "ok": True,
            "message": "The number was removed from the calling list.",
        }

    return {"ok": False, "error": "unknown_tool", "message": "Unknown tool."}


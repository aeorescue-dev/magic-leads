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
import threading
import time
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import quote

import httpx

from ..config import settings
from ..utils.logger import logger
from . import b2b_voice, showcase, voice_taxonomy

API_BASE = "https://api.telnyx.com/v2"


def configured() -> bool:
    if bool(getattr(settings, "VOICE_STAGING_MODE", False)):
        return False
    return bool(
        getattr(settings, "TELNYX_API_KEY", "")
        and getattr(settings, "TELNYX_CONNECTION_ID", "")
        and getattr(settings, "TELNYX_FROM_NUMBER", "")
    )


def static_script_mode() -> bool:
    """True = gather_using_speak + DTMF; False = AI Assistant/Callie."""
    return (
        str(getattr(settings, "VOICE_SCRIPT_MODE", "assistant") or "")
        .strip()
        .lower()
        == "static"
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
    from_number: Optional[str] = None,
) -> dict:
    """Cria uma chamada Telnyx para uma empresa já validada pelo gate."""
    if (
        configured()
        and not dry_run
        and str(campaign_id or "") != "test_call"
    ):
        campaign_key = str(campaign_id or "")
        if campaign_key.isdigit():
            campaign_status = b2b_voice.campaign_budget_status(
                int(campaign_key)
            )
            if (
                campaign_status.get("ok")
                and campaign_status.get("blocked_reason")
            ):
                return {
                    "ok": False,
                    "reason": campaign_status["blocked_reason"],
                    "message": campaign_status.get("blocked_detail") or "",
                    "campaign_budget": campaign_status,
                }
        usage = b2b_voice.voice_daily_usage()
        estimate = max(
            0, int(getattr(settings, "VOICE_ESTIMATED_CALL_COST_CENTS", 25) or 0)
        )
        budget_cents = int(usage.get("budget_cents") or 0)
        if (
            budget_cents > 0
            and int(usage.get("estimated_total_cents") or 0) + estimate
            > budget_cents
        ):
            return {
                "ok": False,
                "reason": "daily_budget_reached",
                "message": "Limite diário de orçamento de voz atingido.",
                "usage": usage,
            }
        max_calls = int(usage.get("max_calls_per_day") or 0)
        if max_calls > 0 and int(usage.get("calls") or 0) >= max_calls:
            return {
                "ok": False,
                "reason": "daily_calls_reached",
                "message": "Limite diário de chamadas de voz atingido.",
                "usage": usage,
            }
    eligibility = b2b_voice.can_call(
        company, allow_international=(campaign_id == "test_call")
    )
    if not eligibility["allowed"]:
        reasons = list(eligibility.get("reasons") or [])
        # Fora da janela local e' transitorio: pausa a campanha em vez de
        # marcar a empresa como saltada para sempre.
        reason = (
            "outside_hours"
            if reasons and all(item == "outside_hours" for item in reasons)
            else "blocked"
        )
        return {
            "ok": False,
            "reason": reason,
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
    guard: dict = {}
    if configured() and not dry_run:
        if not script:
            return {
                "ok": False,
                "reason": "script_not_approved",
                "message": "Roteiro aprovado é obrigatório para chamadas reais.",
            }
        if not assistant_id and not static_script_mode():
            return {
                "ok": False,
                "reason": "assistant_missing",
                "message": (
                    "Roteiro aprovado sem assistant_id Telnyx; sincroniza o "
                    "assistant antes de ligar."
                ),
            }
        # Guardrail duro: nunca discar para um segmento sem vitrine fresca e
        # com contagem suficiente. Evita dizer "0 opportunities" ou prometer
        # dados velhos. Test calls ficam isentos.
        if str(campaign_id or "") != "test_call":
            guard = voice_scripts.showcase_guard(
                trade or company.get("trade") or "",
                city or company.get("city") or "",
            )
            if not guard["ready"]:
                return {
                    "ok": False,
                    "reason": "showcase_unavailable",
                    "message": guard.get("reason") or "showcase_unavailable",
                    "showcase": guard,
                }
    call_trade = trade or company.get("trade") or ""
    call = b2b_voice.create_voice_call(
        company,
        provider="telnyx",
        campaign_id=campaign_id,
        script_id=(script or {}).get("trade_code") or script_id,
        city=city or company.get("city"),
        trade_code=trade,
        assistant_id=assistant_id,
        category_code=voice_taxonomy.category_for_trade(call_trade) or "",
        script_scope=str(guard.get("scope") or ""),
        from_number=from_number,
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
    amd_mode = (
        str(getattr(settings, "TELNYX_AMD_MODE", "standard") or "standard")
        .strip()
        .lower()
    )
    if amd_mode not in {"premium", "standard", "disabled"}:
        amd_mode = "standard"
    # Telnyx chama ao modo standard "detect"; "standard" e' invalido (422).
    amd_wire = "detect" if amd_mode == "standard" else amd_mode
    payload = {
        "connection_id": settings.TELNYX_CONNECTION_ID,
        "to": company["phone"],
        "from": str(from_number or settings.TELNYX_FROM_NUMBER),
        "webhook_url": _webhook_url(),
        "client_state": state,
        "timeout_secs": 30,
    }
    if amd_mode != "disabled":
        payload["answering_machine_detection"] = amd_wire
        if amd_mode == "premium":
            payload["answering_machine_detection_config"] = {
                "total_analysis_time_millis": 5000
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


def fallback_audio_url() -> str:
    """URL publica do MP3 deterministico do fallback (voz Callie)."""
    configured = str(
        getattr(settings, "VOICE_FALLBACK_AUDIO_URL", "") or ""
    ).strip()
    if configured:
        return configured
    base = str(getattr(settings, "PUBLIC_API_URL", "") or "").rstrip("/")
    return f"{base}/api/voice/fallback.mp3"


def stop_assistant_for_fallback(call_control_id: str) -> dict:
    """Para o assistant antes de tocar o MP3 (sem sobrepor vozes)."""
    if not call_control_id:
        return {"ok": False, "reason": "missing_call_control_id"}
    return _call_action(call_control_id, "ai_assistant_stop", {})


def start_fallback_playback(
    voice_call_id: int, call_control_id: str
) -> dict:
    """Toca o MP3 exato depois de o assistant parar; fallback para speak."""
    from .voice_scripts import FALLBACK_SCRIPT

    if not call_control_id:
        return {"ok": False, "reason": "missing_call_control_id"}
    current = b2b_voice.get_voice_call(voice_call_id) or {}
    if current.get("intent") != "website_redirect":
        return {"ok": False, "reason": "not_website_redirect"}
    if not b2b_voice.claim_fallback_playback(voice_call_id):
        return {"ok": False, "reason": "already_started"}
    play = _call_action(
        call_control_id,
        "playback_start",
        {
            "audio_url": fallback_audio_url(),
            "audio_type": "mp3",
            "cache_audio": True,
            "stop": "all",
        },
    )
    if play.get("ok"):
        return {"ok": True, "mode": "playback", "play": play}
    speak = _call_action(
        call_control_id,
        "speak",
        {
            "payload": FALLBACK_SCRIPT,
            "voice": "female",
            "language": "en-US",
        },
    )
    return {
        "ok": bool(speak.get("ok")),
        "mode": "speak",
        "play": play,
        "speak": speak,
    }


def schedule_fallback_playback(
    voice_call_id: int, call_control_id: str, delay_seconds: float = 2
) -> None:
    """Se conversation.ended nao chegar, toca o MP3 2s depois do stop."""

    def _run() -> None:
        time.sleep(delay_seconds)
        current = b2b_voice.get_voice_call(voice_call_id) or {}
        if (
            current.get("intent") == "website_redirect"
            and not current.get("fallback_audio_started_at")
        ):
            start_fallback_playback(voice_call_id, call_control_id)

    threading.Thread(target=_run, daemon=True).start()


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


def _start_static_script_for_call(
    voice_call_id: int, call_control_id: str, client_state: dict
) -> dict:
    """V3 low-cost: TTS + gather DTMF 2, sem AI Assistant/Krisp."""
    if not configured() or not call_control_id:
        return {"ok": False, "reason": "not_configured"}
    current = b2b_voice.get_voice_call(voice_call_id) or {}
    if not b2b_voice.claim_assistant_start(voice_call_id):
        return {"ok": False, "reason": "already_started"}
    try:
        rendered = _render_for_call(current, client_state)
    except ValueError as exc:
        b2b_voice.update_voice_call(
            voice_call_id,
            status="ended",
            hangup_cause=f"render_failed:{str(exc)[:80]}",
        )
        hangup_call(call_control_id)
        return {"ok": False, "reason": "render_failed", "detail": str(exc)[:200]}
    greeting = str(rendered.get("greeting") or "").strip()
    voice = str(rendered.get("voice_id") or "").strip() or "female"
    timeout_ms = max(
        1000,
        int(getattr(settings, "TELNYX_STATIC_GATHER_TIMEOUT_MS", 10000) or 10000),
    )
    result = _call_action(
        call_control_id,
        "gather_using_speak",
        {
            "payload": greeting[:3000],
            "voice": voice,
            "language": "en-US",
            "minimum_digits": 1,
            "maximum_digits": 1,
            "maximum_tries": 1,
            "timeout_millis": timeout_ms,
            "valid_digits": "2",
            "client_state": _encode_state(client_state),
        },
    )
    if result.get("ok"):
        b2b_voice.update_voice_call(voice_call_id, status="in_call")
    else:
        b2b_voice.update_voice_call(
            voice_call_id, status="ended", hangup_cause="static_tts_failed"
        )
        hangup_call(call_control_id)
    return result


def _start_assistant_for_call(
    voice_call_id: int, call_control_id: str, client_state: dict
) -> dict:
    """Arranca o assistant apenas depois do AMD confirmar humano."""
    if static_script_mode():
        return _start_static_script_for_call(
            voice_call_id, call_control_id, client_state
        )
    if not configured() or not call_control_id:
        return {"ok": False, "reason": "not_configured"}
    current = b2b_voice.get_voice_call(voice_call_id) or {}
    assistant_id = str(current.get("assistant_id") or "")
    if not assistant_id:
        b2b_voice.update_voice_call(
            voice_call_id, status="ended", hangup_cause="missing_assistant"
        )
        hangup_call(call_control_id)
        return {"ok": False, "reason": "missing_assistant"}
    if not b2b_voice.claim_assistant_start(voice_call_id):
        return {"ok": False, "reason": "already_started"}
    rendered = _render_for_call(current, client_state)
    result = start_ai_assistant(
        call_control_id,
        assistant_id,
        instructions=str(rendered.get("instructions") or ""),
        greeting=str(rendered.get("greeting") or ""),
        voice=str(rendered.get("voice_id") or ""),
    )
    if result.get("ok"):
        b2b_voice.update_voice_call(voice_call_id, status="in_call")
    else:
        b2b_voice.update_voice_call(
            voice_call_id, status="ended", hangup_cause="assistant_start_failed"
        )
        hangup_call(call_control_id)
    return result


def _schedule_assistant_fallback(
    voice_call_id: int,
    call_control_id: str,
    client_state: dict,
    delay_seconds: int = 8,
) -> None:
    """Se o AMD nao chegar, arranca o assistant ao fim de 8s (fail-open)."""

    def _run() -> None:
        time.sleep(delay_seconds)
        current = b2b_voice.get_voice_call(voice_call_id) or {}
        if current.get("status") == "assistant_pending":
            _start_assistant_for_call(
                voice_call_id, call_control_id, client_state
            )

    threading.Thread(target=_run, daemon=True).start()


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
    if "machine" in event_type and (
        "detection.ended" in event_type or "greeting.ended" in event_type
    ):
        # AMD premium: maquina/voicemail -> desliga; humano/silencio/not_sure
        # seguem. "silence" NAO e maquina: um humano pode estar calado.
        result = str(body.get("result") or data.get("result") or "").lower()
        logger.info(
            "[TELNYX] AMD result=%s event=%s voice_call=%s",
            result,
            event_type,
            voice_call_id,
        )
        call_control_id = str(
            body.get("call_control_id") or data.get("call_control_id") or ""
        )
        if not voice_call_id and call_control_id:
            found = b2b_voice.get_voice_call_by_provider_id(call_control_id)
            if found:
                voice_call_id = found["id"]
        is_machine = (
            result in {"machine", "fax_detected"}
            or "beep" in result
            or "greeting.ended" in event_type
        )
        if is_machine:
            if voice_call_id:
                b2b_voice.update_voice_call(
                    voice_call_id,
                    intent="voicemail",
                    hangup_cause="voicemail_detected",
                    amd_result=result,
                )
            if call_control_id:
                hangup_call(call_control_id)
            return {
                "ok": True,
                "action": "voicemail_hangup",
                "voice_call_id": voice_call_id,
                "result": result,
                "event_type": event_type,
            }
        if voice_call_id:
            b2b_voice.update_voice_call(voice_call_id, amd_result=result)
            _start_assistant_for_call(
                voice_call_id, call_control_id, state
            )
        return {
            "ok": True,
            "action": "amd_human",
            "voice_call_id": voice_call_id,
            "result": result,
            "event_type": event_type,
        }
    if "gather.ended" in event_type:
        digits = str(
            body.get("digits") or body.get("dtmf_digits") or ""
        ).strip()
        call_control_id = str(
            body.get("call_control_id") or data.get("call_control_id") or ""
        )
        if not voice_call_id and call_control_id:
            found = b2b_voice.get_voice_call_by_provider_id(call_control_id)
            if found:
                voice_call_id = found["id"]
        if voice_call_id and digits == "2":
            opt_out_voice_call(voice_call_id)
            speak = _call_action(
                call_control_id,
                "speak",
                {
                    "payload": "You've been removed from our list. Goodbye.",
                    "voice": "female",
                    "language": "en-US",
                },
            )
            if not speak.get("ok"):
                hangup_call(call_control_id)
            return {
                "ok": True,
                "action": "gather_opt_out",
                "voice_call_id": voice_call_id,
                "digits": digits,
            }
        if call_control_id:
            hangup_call(call_control_id)
        return {
            "ok": True,
            "action": "gather_ended",
            "voice_call_id": voice_call_id,
            "digits": digits,
        }

    if "conversation.ended" in event_type:
        # O assistant parou; se foi a tecla 2, toca o MP3 agora (sem overlap).
        call_control_id = str(
            body.get("call_control_id") or data.get("call_control_id") or ""
        )
        if not voice_call_id and call_control_id:
            found = b2b_voice.get_voice_call_by_provider_id(call_control_id)
            if found:
                voice_call_id = found["id"]
        if voice_call_id:
            current = b2b_voice.get_voice_call(voice_call_id) or {}
            if (
                current.get("intent") == "website_redirect"
                and not current.get("fallback_audio_started_at")
            ):
                start_fallback_playback(voice_call_id, call_control_id)
        return {
            "ok": True,
            "action": "conversation_ended",
            "voice_call_id": voice_call_id,
            "event_type": event_type,
        }
    if "playback.ended" in event_type or "speak.ended" in event_type:
        # Alguns eventos de media não trazem client_state; correlaciona pelo
        # call_control_id antes de exigir voice_call_id.
        call_control_id = str(
            body.get("call_control_id") or data.get("call_control_id") or ""
        )
        if not voice_call_id and call_control_id:
            found = b2b_voice.get_voice_call_by_provider_id(call_control_id)
            if found:
                voice_call_id = found["id"]
        if call_control_id:
            hangup_call(call_control_id)
        return {
            "ok": True,
            "action": "media_ended_hangup",
            "voice_call_id": voice_call_id,
            "event_type": event_type,
        }
    if not voice_call_id:
        return {"ok": False, "reason": "missing_voice_call_id", "event_type": event_type}

    try:
        voice_call_id = int(voice_call_id)
    except (TypeError, ValueError):
        return {"ok": False, "reason": "invalid_voice_call_id", "event_type": event_type}

    if "dtmf" in event_type:
        digit = str(body.get("dtmf_digit") or body.get("digit") or "").strip()
        if digit == "2":
            # Opt-out deterministico: suppression + DNC antes de qualquer
            # audio. O assistant e parado para nao sobrepor a confirmacao.
            current = b2b_voice.get_voice_call(voice_call_id) or {}
            call_control_id = str(
                body.get("call_control_id")
                or current.get("provider_call_id")
                or ""
            )
            opted_out = opt_out_voice_call(voice_call_id)
            stop = stop_assistant_for_fallback(call_control_id)
            speak = _call_action(
                call_control_id,
                "speak",
                {
                    "payload": "You've been removed from our list. Goodbye.",
                    "voice": "female",
                    "language": "en-US",
                },
            )
            if not speak.get("ok"):
                hangup_call(call_control_id)
            return {
                "ok": True,
                "action": "opt_out",
                "voice_call_id": voice_call_id,
                "digit": digit,
                "opt_out": opted_out,
                "stop": stop,
                "confirmation": speak,
            }
        if digit == "1":
            # A V3 nao oferece tecla 1. Se o caller pressionar por habito,
            # repetimos o unico caminho de conversao (website) sem email.
            current = b2b_voice.get_voice_call(voice_call_id) or {}
            call_control_id = str(
                body.get("call_control_id")
                or current.get("provider_call_id")
                or ""
            )
            b2b_voice.update_voice_call(voice_call_id, intent="website_reminder")
            stop = stop_assistant_for_fallback(call_control_id)
            speak = _call_action(
                call_control_id,
                "speak",
                {
                    "payload": (
                        "Visit MagicLeads dot app to see this week's active "
                        "opportunities."
                    ),
                    "voice": "female",
                    "language": "en-US",
                },
            )
            if not speak.get("ok"):
                hangup_call(call_control_id)
            return {
                "ok": True,
                "action": "website_reminder",
                "voice_call_id": voice_call_id,
                "digit": digit,
                "stop": stop,
                "confirmation": speak,
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
            status="assistant_pending",
            answered_at=datetime.now(timezone.utc).isoformat(),
        )
        call_control_id = str(
            body.get("call_control_id") or current.get("provider_call_id") or ""
        )
        assistant_id = str(current.get("assistant_id") or "")
        if configured() and call_control_id and not assistant_id:
            # Seguranca: nunca deixar uma chamada real em silencio.
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
                "assistant_started": False,
                "waiting_for_amd": False,
                "reason": "missing_assistant",
            }
        if configured() and call_control_id:
            # Nao fala antes do AMD. O evento AMD humano arranca o assistant;
            # se o AMD nao chegar em 8s, o timer arranca (fail-open).
            _schedule_assistant_fallback(
                voice_call_id, call_control_id, state
            )
        return {
            "ok": True,
            "action": "answered",
            "voice_call_id": voice_call_id,
            "assistant_started": False,
            "waiting_for_amd": bool(configured() and call_control_id),
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
        if not duration and current.get("answered_at"):
            # O call.hangup da Telnyx nem sempre traz a duracao; sem este
            # fallback a chamada ficava com 0s e custo 0.
            try:
                answered_dt = datetime.fromisoformat(
                    str(current["answered_at"])
                )
                if answered_dt.tzinfo is None:
                    answered_dt = answered_dt.replace(tzinfo=timezone.utc)
                duration = max(
                    0,
                    int(
                        (
                            datetime.now(timezone.utc) - answered_dt
                        ).total_seconds()
                    ),
                )
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
                or current.get("hangup_cause")
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
    force: bool = False,
) -> dict:
    """Cria o link da vitrine e envia o email para a empresa da chamada."""
    call = b2b_voice.get_voice_call(voice_call_id)
    if not call:
        return {"ok": False, "reason": "call_not_found"}
    if call.get("showcase_link_id") and not force:
        return {
            "ok": True,
            "duplicate": True,
            "link_id": call.get("showcase_link_id"),
            "message": "showcase already sent for this call",
        }
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


def opt_out_voice_call(voice_call_id: int) -> dict:
    """Suprime o número e marca DNC para um opt-out determinístico."""
    call = b2b_voice.get_voice_call(int(voice_call_id)) or {}
    company_id = int(call.get("company_id") or 0)
    company = b2b_voice.get_company(company_id) if company_id else {}
    phone = str((company or {}).get("phone") or call.get("phone") or "").strip()
    if phone:
        b2b_voice.suppress(phone, reason="caller_opt_out")
    if company_id:
        b2b_voice.mark_company_do_not_call(company_id)
    b2b_voice.update_voice_call(
        int(voice_call_id),
        intent="opt_out",
        status="opt_out",
    )
    return {
        "ok": True,
        "company_id": company_id,
        "phone": phone,
        "suppressed": bool(phone),
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

    if name == "send_showcase_link":
        b2b_voice.update_voice_call(voice_call_id, intent="showcase")
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
        b2b_voice.update_voice_call(voice_call_id, intent="showcase")
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
        opt_out_voice_call(voice_call_id)
        return {
            "ok": True,
            "message": "The number was removed from the calling list.",
        }

    return {"ok": False, "error": "unknown_tool", "message": "Unknown tool."}


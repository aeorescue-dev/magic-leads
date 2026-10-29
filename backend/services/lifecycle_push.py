"""Push dos avisos de ciclo de vida (B2, opt-in).

Os avisos de 30 min / 15 min / 24 h / 2 h ja existem in-app (watchdog). Aqui
sao promovidos a push para quem ativou `lifecycle_push_enabled`. O aviso
critico `reveal_urgent` (15 min para o lead voltar ao pool) e o unico que
pode furar o silencio noturno — e a reserva paga do cliente que esta em jogo.
"""
from datetime import datetime, timezone

from ..utils.logger import logger
from .access import is_access_active
from .alert_planner import _is_quiet_hours
from .db import db_service
from .push_click import sign_click
from .push_service import push_service

_ICON = "https://magicleads-oficial.vercel.app/icons/magicleads-brand.svg"

_ACTION_LABELS = {
    "pt": ("Ver lead", "Dispensar"),
    "en": ("View lead", "Dismiss"),
    "es": ("Ver lead", "Descartar"),
}


async def dispatch_lifecycle_pushes(limit: int = 50) -> int:
    """Envia push para avisos de ciclo de vida ainda nao enviados."""
    try:
        rows = await db_service.get_unpushed_lifecycle_notifications(limit)
    except Exception as e:
        logger.warning("[LIFECYCLE-PUSH] query falhou: %s", e)
        return 0
    if not rows:
        return 0

    quiet = _is_quiet_hours()
    sent = 0
    for n in rows:
        ntype = str(n.get("type") or "")
        # Silencio: so o aviso critico de 15 min passa.
        if quiet and ntype != "reveal_urgent":
            continue
        if not is_access_active(n.get("subscription_status"), n.get("plan_until")):
            continue
        try:
            nid = int(n["id"])
            sig = sign_click(nid)
            lead_id = n.get("lead_id")
            url = f"/dashboard?lead={lead_id}&src=push&nid={nid}&sig={sig}"
            labels = _ACTION_LABELS.get(
                str(n.get("locale") or "pt").split("-")[0], _ACTION_LABELS["pt"]
            )
            payload = {
                "title": n.get("title") or "Magic Leads",
                "body": n.get("message") or "",
                "icon": _ICON,
                "badge": _ICON,
                "tag": f"lifecycle_{nid}",
                "renotify": True,
                "silent": False,
                "leadId": lead_id,
                "nid": nid,
                "sig": sig,
                "url": url,
                "actions": [
                    {"action": "open", "title": labels[0]},
                    {"action": "dismiss", "title": labels[1]},
                ],
                "vibrate": [180, 90, 180] if ntype == "reveal_urgent" else [120, 80, 120],
                "requireInteraction": ntype == "reveal_urgent",
                "timestamp": int(datetime.now(timezone.utc).timestamp() * 1000),
            }
            ok = await push_service.send_to_user(
                int(n["user_id"]),
                payload,
                "lifecycle",
                ttl=3600,
                urgency="high" if ntype == "reveal_urgent" else "normal",
            )
            if ok:
                await db_service.mark_notification_pushed(nid)
                sent += 1
        except Exception as e:
            logger.error("[LIFECYCLE-PUSH] notificacao %s falhou: %s", n.get("id"), e)
    return sent

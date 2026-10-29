"""Assinatura HMAC do clique de push (B1).

O Service Worker nao tem acesso ao token da sessao (localStorage nao existe
no contexto do SW). Em vez de expor um endpoint aberto, o payload leva um
`nid` assinado: so quem recebeu a notificacao consegue registar o clique.
"""
import hashlib
import hmac

from ..config import settings

_FALLBACK_SECRET = "magic-leads-push-click-v1"


def _secret() -> str:
    return (
        getattr(settings, "PUSH_CLICK_SECRET", "")
        or getattr(settings, "CRON_SECRET", "")
        or _FALLBACK_SECRET
    )


def sign_click(notification_id: int) -> str:
    message = f"push-click:{int(notification_id)}".encode("utf-8")
    return hmac.new(_secret().encode("utf-8"), message, hashlib.sha256).hexdigest()[:24]


def verify_click(notification_id: int, signature: str) -> bool:
    if not signature:
        return False
    return hmac.compare_digest(sign_click(notification_id), str(signature))

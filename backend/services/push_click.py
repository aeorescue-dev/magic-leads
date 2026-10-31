"""Assinatura HMAC do clique de push (B1).

O Service Worker nao tem acesso ao token da sessao (localStorage nao existe
no contexto do SW). Em vez de expor um endpoint aberto, o payload leva um
`nid` assinado: so quem recebeu a notificacao consegue registar o clique.
"""
import hashlib
import hmac

from ..config import settings


def _secret() -> str:
    """Segredo HMAC obrigatório. Sem segredo, cliques ficam fail-closed.

    O fallback hardcoded antigo permitia forjar `sig` para qualquer nid. Se o
    ambiente não definir PUSH_CLICK_SECRET nem CRON_SECRET, não se assina nada
    (o clique não é registado, mas também não é falsificável).
    """
    return (
        getattr(settings, "PUSH_CLICK_SECRET", "")
        or getattr(settings, "CRON_SECRET", "")
        or ""
    )


def sign_click(notification_id: int) -> str:
    secret = _secret()
    if not secret:
        return ""
    message = f"push-click:{int(notification_id)}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()[:24]


def verify_click(notification_id: int, signature: str) -> bool:
    secret = _secret()
    if not secret or not signature:
        return False
    expected = sign_click(notification_id)
    if not expected:
        return False
    return hmac.compare_digest(expected, str(signature))

"""Web Push Notification Service for Magic Leads.

Envia notificações push via Web Push Protocol (VAPID) para subscriptions salvas.
"""
import asyncio
import json
import random
import time
from typing import Dict, Optional

import anyio
from pywebpush import WebPushException, webpush

from ..config import settings
from ..utils.logger import logger
from .db import db_service
from .metrics import push_metrics

MAX_RETRIES = 3
BASE_BACKOFF = 1.0  # seconds
MAX_BACKOFF = 30.0  # seconds

# --------------------------------------------------------------- Fase 2
# Taxonomia das entregas de push.
#
# A distincao que importa: 'accepted' NAO e entrega. Significa apenas que o
# servico de push aceitou a mensagem. Se o browser estava fechado, a
# notificacao fica no store do servico e morre la. Confirmar entrega exige
# telemetria do service worker, que fica fora desta fase - e por isso que o
# painel diz "aceites", nunca "entregues".
#
# 'expired' (404/410) e o outcome com peso operacional: e uma subscricao
# morta, que o servico remove logo a seguir. A frequencia mede quantas
# notificacoes estavam a ir para o vazio antes de serem limpas.

_PUSH_TIMEOUT_MARKERS = ("timeout", "timed out", "etimedout")

# 401/403 com estes indícios significam que a subscription foi criada com uma
# chave VAPID diferente da nossa (ex.: FCM `VapidPkHashMismatch` ou "the VAPID
# credentials ... do not correspond to the credentials used to create the
# subscriptions") ou que o auth secret é inválido. A subscription está morta E
# irrecuperável: retry nunca resolve, só a remoção.
_VAPID_DEAD_MARKERS = (
    "vapidpk hashmismatch",
    "hashmismatch",
    "vapid",
    "unauthorizedregistration",
    "badjsonwebkey",
    "do not correspond to the credentials",
)


def _is_dead_subscription(status_code: Optional[int], response_text: Optional[str]) -> bool:
    """True quando um 401/403 indica subscription VAPID inválida (remover).

    Um 401/403 do serviço de push é uma falha de AUTENTICAÇÃO determinística
    para aquela subscription: repetir nunca resolve. Removemos quando:

      * o corpo traz um indício VAPID explícito (marcadores acima); ou
      * o corpo vem VAZIO — o endpoint rejeitou a credencial sem dar detalhe
        (é o padrão observado em produção nos 401 vazios, que de outro modo
        ficavam presos a ser tentados para sempre como "rejected").
    """
    if status_code not in (401, 403):
        return False
    text = (response_text or "").strip().lower()
    if not text:
        return True
    return any(marker in text for marker in _VAPID_DEAD_MARKERS)


def classify_push_outcome(status_code: Optional[int], error: Optional[str] = None) -> str:
    """Normaliza o resultado de uma entrega de push num outcome estavel.

    401/403 de VAPID inválido são classificados antes deste ponto (ramo
    `rejected_dead` em `_send_single`). Aqui caem só os restantes 400-499
    genéricos, que NÃO removem a subscription.
    """
    if status_code is not None:
        if status_code in (404, 410):
            return "expired"
        if status_code == 429:
            return "rate_limited"
        if 400 <= status_code < 500:
            return "rejected"
        if status_code >= 500:
            return "error"

    err = (error or "").strip().lower()
    if not err:
        return "error"
    if any(marker in err for marker in _PUSH_TIMEOUT_MARKERS):
        return "timeout"
    return "error"

# Prefixos padronizados para títulos
PREFIXES = {
    "new_lead": "⚡ [NOVO LEAD]",
    "status_change": "🔄 [STATUS]",
    "digest": "📋 [RESUMO]",
    "system_alert": "🚨 [ALERTA SISTEMA]",
    "anomaly": "[AVISO]️ [ANOMALIA]",
    "circuit_breaker": "🔴 [CIRCUIT BREAKER]",
    "test": "🧪 [TESTE]",
}

ICON_URL = "https://magicleads-oficial.vercel.app/icons/magicleads-brand.svg"
BADGE_URL = "https://magicleads-oficial.vercel.app/icons/magicleads-brand.svg"


def _build_payload(title: str, body: str, tag: str, lead_id: int = None, url: str = None, category: str = None, extra: dict = None) -> dict:
    """Constrói payload padronizado com urgency, sound, icon, badge, prefixos."""
    payload = {
        "title": title,
        "body": body,
        "sound": "default",
        "icon": ICON_URL,
        "badge": BADGE_URL,
        "tag": tag,
    }
    if lead_id is not None:
        payload["leadId"] = lead_id
    if url is not None:
        payload["url"] = url
    if category is not None:
        payload["category"] = category
    if extra:
        payload.update(extra)
    return payload


class PushService:
    def __init__(self):
        self._configured = False
        self._vapid_public_key = None
        self._vapid_private_key = None
        self._vapid_claims = None
        self._load_config()

    def _load_config(self):
        self._vapid_public_key = settings.VAPID_PUBLIC_KEY
        self._vapid_private_key = settings.VAPID_PRIVATE_KEY
        self._vapid_claims = {
            "sub": settings.VAPID_CLAIMS_SUB
        }

        if not self._vapid_public_key or not self._vapid_private_key:
            logger.warning("VAPID keys not configured - push notifications disabled")
            self._configured = False
        else:
            self._configured = True
            logger.info("VAPID keys loaded - push notifications enabled")

    def reload_config(self):
        """Recarrega a configuração (útil após mudanças no .env)."""
        self._load_config()

    def is_configured(self) -> bool:
        return self._configured

    async def _send_single(self, subscription: Dict, payload: Dict, kind: str = "custom",
                           user_id: Optional[int] = None):
        """Envia push para uma única subscription com retry exponencial.

        `kind` é apenas rótulo para telemetria (lead_alert, status_change,
        broadcast...). `user_id` é o destinatário explícito: se a subscription
        não trouxer `user_id` (ex.: caminho antigo), usa este para que a
        telemetria nunca fique órfã. O valor de retorno é True, False ou um
        sentinel de subscrição morta (`"expired"` para 404/410, `"rejected_dead"`
        para 401/403 de VAPID inválido) — os callers removem os dois da BD.
        """
        if not self.is_configured():
            # Bug operacional silencioso: sem VAPID nada é entregue e o
            # utilizador recebe um "enviado com sucesso" do mesmo jeito.
            # Este outcome torna-o visível no painel.
            push_metrics.record(
                outcome="not_configured", attempts=0, kind=kind,
                user_id=subscription.get("user_id") or user_id,
                error="VAPID keys not configured",
            )
            return False

        started = time.monotonic()
        last_error = None
        last_status: Optional[int] = None
        # Destinatário explícito: a subscrição é a fonte primária, o parâmetro
        # é a rede de segurança (torna a telemetria auditável por utilizador).
        recipient_id = subscription.get("user_id") or user_id

        def _record(outcome: str, attempts: int) -> None:
            try:
                push_metrics.record(
                    outcome=outcome,
                    attempts=attempts,
                    latency_ms=int((time.monotonic() - started) * 1000),
                    http_status=last_status,
                    user_id=recipient_id,
                    kind=kind,
                    error=None if outcome == "accepted" else (str(last_error) if last_error else outcome),
                )
            except Exception:  # pragma: no cover - telemetria nunca quebra o envio
                logger.debug("Falha ao registar telemetria de push", exc_info=True)

        for attempt in range(MAX_RETRIES):
            try:
                # webpush() é I/O de rede BLOQUEANTE — roda em thread para não travar o event loop.
                await anyio.to_thread.run_sync(
                    lambda: webpush(
                        subscription_info={
                            "endpoint": subscription["endpoint"],
                            "keys": {
                                "p256dh": subscription["p256dh"],
                                "auth": subscription["auth"]
                            }
                        },
                        data=json.dumps(payload),
                        vapid_private_key=self._vapid_private_key,
                        vapid_claims=dict(self._vapid_claims),
                        headers={"Urgency": "high"},
                    )
                )
                _record("accepted", attempt + 1)
                return True
            except WebPushException as e:
                last_error = e
                last_status = e.response.status_code if e.response is not None else None
                # Subscription expirada ou inválida - não retry, marca para remoção
                if last_status in (404, 410):
                    logger.info(f"Push subscription expired/invalid: {subscription['endpoint'][:50]}...")
                    _record("expired", attempt + 1)
                    return "expired"
                # VAPID inválido (401/403): subscription morta, sem retry —
                # é marcada para remoção pelo caller.
                resp_text = e.response.text if e.response is not None else None
                if _is_dead_subscription(last_status, resp_text):
                    logger.info(
                        f"Push subscription VAPID inválida (HTTP {last_status}): "
                        f"{subscription['endpoint'][:50]}... — marcada para remoção"
                    )
                    _record("rejected_dead", attempt + 1)
                    return "rejected_dead"
                # Rate limiting - retry com backoff
                if last_status == 429:
                    retry_after = e.response.headers.get("Retry-After")
                    wait_time = int(retry_after) if retry_after and retry_after.isdigit() else min(BASE_BACKOFF * (2 ** attempt) + random.uniform(0, 1), MAX_BACKOFF)
                    logger.warning(f"Rate limited (429), aguardando {wait_time:.1f}s antes de retry {attempt + 1}/{MAX_RETRIES}")
                    await asyncio.sleep(wait_time)
                    continue
                # Outros erros HTTP - retry
                if attempt < MAX_RETRIES - 1:
                    wait_time = min(BASE_BACKOFF * (2 ** attempt) + random.uniform(0, 1), MAX_BACKOFF)
                    logger.warning(f"WebPush error (tentativa {attempt + 1}/{MAX_RETRIES}): {e}. Retry em {wait_time:.1f}s")
                    await asyncio.sleep(wait_time)
                    continue
                logger.warning(f"WebPush error após {MAX_RETRIES} tentativas: {e}")
                _record(classify_push_outcome(last_status, str(e)), attempt + 1)
                return False
            except Exception as e:
                last_error = e
                if attempt < MAX_RETRIES - 1:
                    wait_time = min(BASE_BACKOFF * (2 ** attempt) + random.uniform(0, 1), MAX_BACKOFF)
                    logger.warning(f"Unexpected push error (tentativa {attempt + 1}/{MAX_RETRIES}): {e}. Retry em {wait_time:.1f}s")
                    await asyncio.sleep(wait_time)
                    continue
                logger.error(f"Unexpected push error após {MAX_RETRIES} tentativas: {e}")
                _record(classify_push_outcome(None, str(e)), attempt + 1)
                return False

        # Se chegou aqui, todas as tentativas falharam
        logger.error(f"Push falhou após {MAX_RETRIES} tentativas: {last_error}")
        # Classifica em vez de assumir "error": o 429 faz `continue` em todas
        # as tentativas e chega aqui pelo fim do loop, não pela via do
        # `attempt < MAX_RETRIES - 1`. Sem esta classificação uma subscrição
        # sob rate limiting do serviço aparecia como erro nosso.
        _record(
            classify_push_outcome(last_status, str(last_error) if last_error else None),
            MAX_RETRIES,
        )
        return False

    async def send_to_user(self, user_id: int, payload: Dict, kind: str = "custom") -> int:
        """Envia push para todas as subscriptions de um usuário."""
        if not self.is_configured():
            # Registado aqui e não em _send_single: este early return
            # impede que a subscripção chegue a ser lida. Sem este record o
            # "push desligado" é invisível — e é o modo de falha mais
            # silencioso que existe (tudo devolve 0, nada aparece no log).
            push_metrics.record(
                outcome="not_configured", attempts=0, user_id=user_id,
                kind=kind, error="VAPID keys not configured",
            )
            return 0

        # Guarda server-side: nunca despachar push para quem tem o flag
        # desligado. É defesa em profundidade — o fan-out já filtra — mas o
        # choke point é aqui, onde todas as vias de envio convergem.
        if not await db_service.is_push_enabled(user_id):
            push_metrics.record(
                outcome="push_disabled", attempts=0, user_id=user_id,
                kind=kind, error="push_enabled is false",
            )
            return 0

        subscriptions = await db_service.get_user_push_subscriptions(user_id)
        if not subscriptions:
            # Utilizador com push ligado mas SEM dispositivo subscrito: o segundo
            # modo de falha invisivel (o primeiro e `not_configured`). Sem este
            # record o painel mostra "0 entregas" e nunca explica a causa.
            push_metrics.record(
                outcome="no_subscriptions", attempts=0, user_id=user_id,
                kind=kind, error="user has no push subscriptions",
            )
            # Sanitização: um flag push_enabled=1 sem subscription é um estado
            # zumbi. Desliga-o para que a próxima varredura não volte a tentar
            # enviar para o vazio.
            try:
                await db_service.disable_push_if_no_subscriptions(user_id)
            except Exception:  # pragma: no cover - nunca quebra o envio
                logger.debug("Falha ao sanitizar push_enabled user=%s", user_id, exc_info=True)
            return 0

        sent = 0
        expired_endpoints = []

        for sub in subscriptions:
            result = await self._send_single(sub, payload, kind, user_id=user_id)
            if result is True:
                sent += 1
            elif result in ("expired", "rejected_dead"):
                expired_endpoints.append(sub["endpoint"])

        # Remove expired/dead subscriptions
        for endpoint in expired_endpoints:
            await db_service.remove_push_subscription(user_id, endpoint)

        # Sanitização: se todas as subs morreram/expiraram, o flag fica ligado
        # apontando para o vazio. Desliga-o para não gerar no_subscriptions
        # repetidos nos próximos runs.
        if expired_endpoints:
            try:
                await db_service.disable_push_if_no_subscriptions(user_id)
            except Exception:  # pragma: no cover - nunca quebra o envio
                logger.debug("Falha ao sanitizar push_enabled user=%s", user_id, exc_info=True)

        return sent

    async def send_to_all(self, payload: Dict) -> int:
        """Envia push para todas as subscriptions ativas (broadcast)."""
        if not self.is_configured():
            push_metrics.record(
                outcome="not_configured", attempts=0, kind="broadcast",
                error="VAPID keys not configured",
            )
            return 0

        subscriptions = await db_service.get_all_push_subscriptions()
        if not subscriptions:
            return 0

        # Group by user_id
        by_user = {}
        for sub in subscriptions:
            by_user.setdefault(sub["user_id"], []).append(sub)

        total_sent = 0
        for user_id, subs in by_user.items():
            sent = 0
            expired_endpoints = []
            for sub in subs:
                result = await self._send_single(sub, payload, "broadcast", user_id=user_id)
                if result is True:
                    sent += 1
                elif result in ("expired", "rejected_dead"):
                    expired_endpoints.append(sub["endpoint"])

            for endpoint in expired_endpoints:
                await db_service.remove_push_subscription(user_id, endpoint)

            # Sanitização do estado zumbi após remoção de subs mortas.
            if expired_endpoints:
                try:
                    await db_service.disable_push_if_no_subscriptions(user_id)
                except Exception:  # pragma: no cover - nunca quebra o envio
                    logger.debug("Falha ao sanitizar push_enabled user=%s", user_id, exc_info=True)

            total_sent += sent

        return total_sent

    def _send_single_debug(self, subscription: Dict, payload: Dict, ttl: int = 3600) -> Dict:
        """Como _send_single, mas retorna {ok, error} com detalhes para debug."""
        if not self.is_configured():
            return {"ok": False, "error": "Push not configured"}

        try:
            webpush(
                subscription_info={
                    "endpoint": subscription["endpoint"],
                    "keys": {
                        "p256dh": subscription["p256dh"],
                        "auth": subscription["auth"]
                    }
                },
                data=json.dumps(payload),
                vapid_private_key=self._vapid_private_key,
                vapid_claims=dict(self._vapid_claims),
                ttl=ttl,
                headers={"Urgency": "high"},
            )
            return {"ok": True}
        except WebPushException as e:
            status = e.response.status_code if e.response is not None else None
            detail = str(e)
            if status in (404, 410):
                return {"ok": False, "error": f"expired (HTTP {status})", "expired": True, "detail": detail}
            resp_text = e.response.text if e.response is not None else None
            if _is_dead_subscription(status, resp_text):
                return {
                    "ok": False,
                    "error": f"rejected_dead (HTTP {status})",
                    "expired": True,
                    "dead": True,
                    "detail": detail,
                }
            return {"ok": False, "error": f"WebPushException (HTTP {status}): {detail}"}
        except Exception as e:
            return {"ok": False, "error": f"Unexpected: {type(e).__name__}: {e}"}

    async def send_to_all_debug(self, payload: Dict, ttl: int = 3600) -> Dict:
        """Broadcast retornando erros detalhados por subscription (para teste)."""
        results = {
            "configured": self.is_configured(),
            "subscriptions_found": 0,
            "sent": 0,
            "errors": []
        }
        if not self.is_configured():
            results["errors"].append("VAPID keys not configured")
            return results

        subscriptions = await db_service.get_all_push_subscriptions()
        results["subscriptions_found"] = len(subscriptions)
        for sub in subscriptions:
            res = await anyio.to_thread.run_sync(self._send_single_debug, sub, payload, ttl)
            if res.get("ok"):
                results["sent"] += 1
                results["errors"].append({
                    "user_id": sub["user_id"],
                    "endpoint_prefix": (sub["endpoint"] or "<vazia>")[:60],
                    "p256dh_empty": not bool(sub.get("p256dh")),
                    "auth_empty": not bool(sub.get("auth")),
                    "created_at": sub.get("created_at"),
                    "status": "sent"
                })
            else:
                if res.get("expired"):
                    await db_service.remove_push_subscription(sub["user_id"], sub["endpoint"])
                results["errors"].append({
                    "user_id": sub["user_id"],
                    "endpoint_prefix": (sub["endpoint"] or "<vazia>")[:60],
                    "p256dh_empty": not bool(sub.get("p256dh")),
                    "auth_empty": not bool(sub.get("auth")),
                    "created_at": sub.get("created_at"),
                    "error": res.get("error")
                })
        return results

push_service = PushService()

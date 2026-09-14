"""Web Push Notification Service for Magic Leads.

Envia notificações push via Web Push Protocol (VAPID) para subscriptions salvas.
"""
import os
import json
import asyncio
from typing import List, Dict, Optional
from pywebpush import webpush, WebPushException
from .db import db_service
from ..config import settings
from ..utils.logger import logger


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

    def _send_single(self, subscription: Dict, payload: Dict) -> bool:
        """Envia push para uma única subscription."""
        if not self.is_configured():
            return False
            
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
                vapid_claims=self._vapid_claims
            )
            return True
        except WebPushException as e:
            # Subscription expirada ou inválida - marcar para remoção
            if e.response and e.response.status_code in (404, 410):
                logger.info(f"Push subscription expired/invalid: {subscription['endpoint'][:50]}...")
                return "expired"
            logger.warning(f"WebPush error: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected push error: {e}")
            return False

    async def send_to_user(self, user_id: int, payload: Dict) -> int:
        """Envia push para todas as subscriptions de um usuário."""
        if not self.is_configured():
            return 0
            
        subscriptions = await db_service.get_user_push_subscriptions(user_id)
        if not subscriptions:
            return 0
            
        sent = 0
        expired_endpoints = []
        
        for sub in subscriptions:
            result = self._send_single(sub, payload)
            if result is True:
                sent += 1
            elif result == "expired":
                expired_endpoints.append(sub["endpoint"])
        
        # Remove expired subscriptions
        for endpoint in expired_endpoints:
            await db_service.remove_push_subscription(user_id, endpoint)
            
        return sent

    async def send_to_category(self, category: str, payload: Dict) -> int:
        """Envia push para todos usuários interessados na categoria."""
        if not self.is_configured():
            return 0
            
        users = await db_service.get_users_interested_in(category)
        if not users:
            return 0
            
        total_sent = 0
        for user in users:
            sent = await self.send_to_user(user["id"], payload)
            total_sent += sent
            
        return total_sent

    async def send_to_all(self, payload: Dict) -> int:
        """Envia push para todas as subscriptions ativas (broadcast)."""
        if not self.is_configured():
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
                result = self._send_single(sub, payload)
                if result is True:
                    sent += 1
                elif result == "expired":
                    expired_endpoints.append(sub["endpoint"])

            for endpoint in expired_endpoints:
                await db_service.remove_push_subscription(user_id, endpoint)

            total_sent += sent

        return total_sent

    def _send_single_debug(self, subscription: Dict, payload: Dict) -> Dict:
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
                vapid_claims=self._vapid_claims
            )
            return {"ok": True}
        except WebPushException as e:
            status = e.response.status_code if e.response is not None else None
            detail = str(e)
            if status in (404, 410):
                return {"ok": False, "error": f"expired (HTTP {status})", "expired": True, "detail": detail}
            return {"ok": False, "error": f"WebPushException (HTTP {status}): {detail}"}
        except Exception as e:
            return {"ok": False, "error": f"Unexpected: {type(e).__name__}: {e}"}

    async def send_to_all_debug(self, payload: Dict) -> Dict:
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
            res = self._send_single_debug(sub, payload)
            if res.get("ok"):
                results["sent"] += 1
            else:
                if res.get("expired"):
                    await db_service.remove_push_subscription(sub["user_id"], sub["endpoint"])
                results["errors"].append({
                    "user_id": sub["user_id"],
                    "endpoint_prefix": (sub["endpoint"] or "<vazia>")[:60],
                    "p256dh_empty": not bool(sub.get("p256dh")),
                    "auth_empty": not bool(sub.get("auth")),
                    "error": res.get("error")
                })
        return results

    async def send_new_lead_alert(self, lead: dict, category: str) -> int:
        """Envia alerta de novo lead para usuários interessados na categoria."""
        payload = {
            "title": "Nova oportunidade",
            "body": f"{category}: {lead.get('address', 'Endereço não informado')} — {lead.get('city', '')}",
            "tag": f"new_lead_{lead.get('id')}",
            "leadId": lead.get("id"),
            "url": f"/dashboard?lead={lead.get('id')}",
            "category": category,
            "timestamp": lead.get("date_reported")
        }
        return await self.send_to_category(category, payload)

    async def send_status_change_alert(self, lead: dict, new_status: str, category: str) -> int:
        """Envia alerta de mudança de status."""
        payload = {
            "title": "Status atualizado",
            "body": f"O lead {lead.get('address', '')} — {lead.get('city', '')} agora está '{new_status}' ({category})",
            "tag": f"status_{lead.get('id')}_{new_status}",
            "leadId": lead.get("id"),
            "url": f"/dashboard?lead={lead.get('id')}",
            "category": category,
            "status": new_status
        }
        return await self.send_to_category(category, payload)


push_service = PushService()
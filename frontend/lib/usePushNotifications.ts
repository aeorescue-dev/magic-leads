"use client";

import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";
import { getToken } from "@/lib/api-client";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "";

export type PushPermissionState = "default" | "granted" | "denied";

function isPushSupported(): boolean {
  if (typeof window === "undefined") return false;
  return (
    "serviceWorker" in navigator &&
    "PushManager" in window &&
    typeof Notification !== "undefined" &&
    "requestPermission" in Notification
  );
}

function apiFetch(path: string, options: RequestInit = {}) {
  const token = getToken();
  return fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    },
  });
}

function urlBase64ToUint8Array(base64String: string): Uint8Array {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const rawData = window.atob(base64);
  const outputArray = new Uint8Array(rawData.length);
  for (let i = 0; i < rawData.length; ++i) {
    outputArray[i] = rawData.charCodeAt(i);
  }
  return outputArray;
}

function arrayBufferToBase64(buffer: ArrayBuffer | null): string {
  if (!buffer) return "";
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (let i = 0; i < bytes.length; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary);
}

function toUrlBase64(base64: string): string {
  return base64.replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export function usePushNotifications() {
  const { user } = useAuth();
  const [supported, setSupported] = useState(false);
  const [permission, setPermission] = useState<PushPermissionState>("default");
  const [subscribed, setSubscribed] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const supported = isPushSupported();
    setSupported(supported);
    if (supported) {
      setPermission(Notification.permission);
    }
  }, []);

  const checkSubscription = useCallback(async () => {
    if (!user?.id || !getToken()) return;
    try {
      const [res, swSub] = await Promise.all([
        apiFetch("/api/push/subscriptions"),
        navigator.serviceWorker.ready.then((reg) => reg.pushManager.getSubscription()),
      ]);
      if (res.ok) {
        const data = await res.json();
        const subs = data.subscriptions || [];
        // Só considera "ativado" se o endpoint do browser ATUAL está no backend.
        // Subs de outros browsers/dispositivos não devem esconder o botão de ativar.
        const currentEndpoint = swSub?.endpoint || "";
        setSubscribed(!!currentEndpoint && subs.some((s: { endpoint: string }) => s.endpoint === currentEndpoint));
      }
    } catch (e) {
      console.error("Error checking subscription:", e);
    }
  }, [user?.id]);

  useEffect(() => {
    if (user?.id) {
      checkSubscription();
    }
  }, [user?.id, checkSubscription]);

  const subscribe = useCallback(async () => {
    if (!user?.id || !supported || loading) return;
    setLoading(true);
    setError(null);

    try {
      // Permission already denied by the browser: instruct how to re-enable.
      if (Notification.permission === "denied") {
        setPermission("denied");
        setError("Notification permission is blocked");
        return;
      }

      let granted: boolean;
      try {
        // requestPermission can resolve a value, reject, or (legacy) accept a callback.
        const result: NotificationPermission | void = await Notification.requestPermission();
        granted = result === "granted";
      } catch (requestErr) {
        console.error("requestPermission error:", requestErr);
        granted = Notification.permission === "granted";
      }
      setPermission(Notification.permission);

      if (!granted) {
        setError("Notification permission is blocked");
        return;
      }

      // Register service worker (idempotent if already registered).
      const registration = await navigator.serviceWorker.register("/sw.js");
      await navigator.serviceWorker.ready;
      console.log("[push] SW registered:", registration.scope);

      // Fetch VAPID public key (endpoint works with or without auth).
      const keyRes = await apiFetch("/api/push/vapid-public-key");
      let publicKey = "";
      if (keyRes.ok) {
        const data = await keyRes.json();
        publicKey = data.public_key || "";
      }
      if (!publicKey) {
        setError("Push service unavailable");
        return;
      }
      console.log("[push] VAPID public key obtida:", publicKey.length, "chars");

      const existingSubscription = await registration.pushManager.getSubscription();
      const applicationServerKey = urlBase64ToUint8Array(publicKey);

      let subscription: PushSubscription;
      try {
        if (existingSubscription) {
          // Re-subscribe if the application server key changed.
          const existingKey = existingSubscription.options.applicationServerKey;
          if (existingKey && toUrlBase64(arrayBufferToBase64(existingKey)) === publicKey) {
            console.log("[push] Reusando subscription existente");
            subscription = existingSubscription;
          } else {
            console.log("[push] Chave VAPID mudou — resubscribe");
            await existingSubscription.unsubscribe();
            subscription = await registration.pushManager.subscribe({
              userVisibleOnly: true,
              applicationServerKey: applicationServerKey as any,
            });
          }
        } else {
          console.log("[push] Criando nova PushSubscription...");
          subscription = await registration.pushManager.subscribe({
            userVisibleOnly: true,
            applicationServerKey: applicationServerKey as any,
          });
        }
        console.log("[push] PushSubscription criada:", subscription.endpoint);
      } catch (subscribeErr) {
        console.error("[push] FALHA em pushManager.subscribe():", subscribeErr);
        setError(
          subscribeErr instanceof Error
            ? `Push browser error: ${subscribeErr.name}: ${subscribeErr.message}`
            : "Push browser error"
        );
        return;
      }

      const subData = {
        endpoint: subscription.endpoint,
        p256dh: arrayBufferToBase64(subscription.getKey("p256dh")),
        auth: arrayBufferToBase64(subscription.getKey("auth")),
      };

      if (!subData.p256dh || !subData.auth) {
        setError("Browser keys unavailable");
        return;
      }

      // Envio assintrono ao backend com tratamento de erro isolado.
      try {
        const subRes = await apiFetch("/api/push/subscribe", {
          method: "POST",
          body: JSON.stringify(subData),
        });

        if (!subRes.ok) {
          const detail = await subRes.json().catch(() => null);
          console.error("[push] Backend rejeitou subscription:", subRes.status, detail);
          setError(detail?.detail || "Push registration failed");
          return;
        }

        console.log("[push] Subscription registrada no backend");
      } catch (backendErr) {
        console.error("[push] Erro ao salvar subscription no backend:", backendErr);
        setError(backendErr instanceof Error ? backendErr.message : "Push registration failed");
        return;
      }

      // So ativa a UI apos sucesso confirmado no backend.
      setSubscribed(true);
      setError(null);
    } catch (err) {
      console.error("[push] Subscribe error:", err);
      setError(err instanceof Error ? err.message : "Push error");
    } finally {
      setLoading(false);
    }
  }, [user?.id, supported, loading]);

  const unsubscribe = useCallback(async () => {
    if (!user?.id) return;
    setLoading(true);
    setError(null);
    try {
      const registration = await navigator.serviceWorker.ready;
      const subscription = await registration.pushManager.getSubscription();

      if (subscription) {
        await subscription.unsubscribe();
        await apiFetch("/api/push/unsubscribe", {
          method: "POST",
          body: JSON.stringify({ endpoint: subscription.endpoint }),
        });
      }

      setSubscribed(false);
    } catch (err) {
      console.error("Unsubscribe error:", err);
      setError(err instanceof Error ? err.message : "Push error");
    } finally {
      setLoading(false);
    }
  }, [user?.id]);

  return {
    supported,
    permission,
    subscribed,
    loading,
    error,
    hasUser: !!user?.id,
    subscribe,
    unsubscribe,
    clearError: () => setError(null),
  };
}

export default usePushNotifications;
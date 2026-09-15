"use client";

import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";
import { getToken, setPushEnabled, fetchPushEnabled } from "@/lib/api-client";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "";

export type PushPermissionState = "default" | "granted" | "denied";

export function isIOSDevice(): boolean {
  if (typeof navigator === "undefined") return false;
  const ua = navigator.userAgent || "";
  return (
    /iPad|iPhone|iPod/.test(ua) ||
    ((navigator.platform === "MacIntel" || /Mac/.test(ua)) &&
      typeof navigator.maxTouchPoints === "number" &&
      navigator.maxTouchPoints > 1)
  );
}

export function isStandaloneMode(): boolean {
  if (typeof window === "undefined") return false;
  try {
    const iosStandalone =
      (window.navigator as unknown as { standalone?: boolean }).standalone === true;
    const displayMode = window.matchMedia?.("(display-mode: standalone)")?.matches ?? false;
    return iosStandalone || displayMode;
  } catch {
    return false;
  }
}

export function isIOSPWA(): boolean {
  return isIOSDevice() && isStandaloneMode();
}

export function isIOSNeedsInstall(): boolean {
  return isIOSDevice() && !isStandaloneMode();
}

function isPushSupported(): boolean {
  if (typeof window === "undefined") return false;
  const hasSW = "serviceWorker" in navigator;
  const hasPushManager = "PushManager" in window;
  const hasNotification = typeof Notification !== "undefined";
  const hasRequestPermission = "requestPermission" in Notification;

  // iOS (qualquer navegador) fora do modo PWA: PushManager nunca existe.
  // Returnamos true para que a UI decida exibir o tutorial de instalação.
  if (isIOSNeedsInstall()) {
    return hasSW && hasNotification && hasRequestPermission;
  }

  return hasSW && hasPushManager && hasNotification && hasRequestPermission;
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
  // SSR/hydration safety: browser props (navigator, window, Notification)
  // are ONLY read inside useEffect, never during render.
  const [mounted, setMounted] = useState(false);
  const [supported, setSupported] = useState(false);
  const [permission, setPermission] = useState<PushPermissionState>("default");
  const [subscribed, setSubscribed] = useState(false);
  const [pushEnabling, setPushEnabling] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isIOS, setIsIOS] = useState(false);
  const [isStandalone, setIsStandalone] = useState(false);
  const [isIOSNeedsInstall, setIsIOSNeedsInstall] = useState(false);

  useEffect(() => {
    setMounted(true);
    const ios = isIOSDevice();
    const standalone = isStandaloneMode();
    setIsIOS(ios);
    setIsStandalone(standalone);
    setIsIOSNeedsInstall(ios && !standalone);
  }, []);

  useEffect(() => {
    const supported = isPushSupported();
    setSupported(supported);
    if (supported) {
      setPermission(Notification.permission);
    }
    // Sincroniza o flag push_enabled do backend com o estado local.
    if (user?.id) {
      fetchPushEnabled()
        .then((enabled) => setPushEnabling(enabled))
        .catch(() => setPushEnabling(!!user.push_enabled));
    }
  }, [user?.id]);

  const checkSubscription = useCallback(async () => {
    if (!user?.id || !getToken()) return;
    try {
      // iOS fora do PWA: PushManager não existe — nada a verificar.
      if (!("PushManager" in window)) {
        setSubscribed(false);
        return;
      }
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

  // Auto-reconexão silenciosa: se o usuário já tinha push_enabled=true e a
  // permissão do browser está 'granted', reativa o Service Worker em segundo
  // plano (sem modais) na volta do usuário.
  useEffect(() => {
    const hasPushFlag =
      (typeof user?.push_enabled === "boolean" && user.push_enabled) ||
      pushEnabling;
    if (!user?.id || !hasPushFlag || !isStandaloneMode()) return;
    if (typeof Notification !== "undefined" && Notification.permission !== "granted") return;
    if (!("serviceWorker" in navigator)) return;

    let cancelled = false;
    (async () => {
      try {
        const registration = await navigator.serviceWorker.register("/sw.js");
        await navigator.serviceWorker.ready;
        if (cancelled) return;
        const sub = await registration.pushManager.getSubscription();
        setSubscribed(!!sub);
        console.log("[push] Reconnect silencioso concluído:", registration.scope);
      } catch (e) {
        console.warn("[push] Reconnect silencioso ignorado:", e);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [user?.id, pushEnabling, user?.push_enabled]);

  const subscribe = useCallback(async (): Promise<boolean> => {
    if (!user?.id || !supported || loading) return false;
    setLoading(true);
    setError(null);

    try {
      // iOS fora do PWA: PushManager não existe — exige instalação.
      if (!("PushManager" in window)) {
        setError("iOS: adicione à Tela Inicial para ativar notificações nativas");
        return false;
      }

      // Permission already denied by the browser: instruct how to re-enable.
      if (Notification.permission === "denied") {
        setPermission("denied");
        setError("Notification permission is blocked");
        return false;
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
        return false;
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
        return false;
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
        return false;
      }

      const subData = {
        endpoint: subscription.endpoint,
        p256dh: arrayBufferToBase64(subscription.getKey("p256dh")),
        auth: arrayBufferToBase64(subscription.getKey("auth")),
      };

      if (!subData.p256dh || !subData.auth) {
        setError("Browser keys unavailable");
        return false;
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
          return false;
        }

        console.log("[push] Subscription registrada no backend");
      } catch (backendErr) {
        console.error("[push] Erro ao salvar subscription no backend:", backendErr);
        setError(backendErr instanceof Error ? backendErr.message : "Push registration failed");
        return false;
      }

      // So ativa a UI apos sucesso confirmado no backend.
      setSubscribed(true);
      setPushEnabling(true);
      setError(null);
      // Persiste push_enabled=true no backend (propriedade da tabela users).
      try {
        await setPushEnabled(true);
      } catch (e) {
        console.warn("[push] Não foi possível persistir push_enabled:", e);
      }
      return true;
    } catch (err) {
      console.error("[push] Subscribe error:", err);
      setError(err instanceof Error ? err.message : "Push error");
      return false;
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
      setPushEnabling(false);
      // Persiste push_enabled=false no backend.
      try {
        await setPushEnabled(false);
      } catch (e) {
        console.warn("[push] Não foi possível limpar push_enabled:", e);
      }
    } catch (err) {
      console.error("Unsubscribe error:", err);
      setError(err instanceof Error ? err.message : "Push error");
    } finally {
      setLoading(false);
    }
  }, [user?.id]);

  return {
    mounted,
    supported,
    permission,
    subscribed,
    pushEnabling,
    loading,
    error,
    hasUser: !!user?.id,
    isIOS,
    isStandalone,
    isIOSPWA: isIOS && isStandalone,
    isIOSNeedsInstall,
    subscribe,
    unsubscribe,
    clearError: () => setError(null),
  };
}

export default usePushNotifications;
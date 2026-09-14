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
      const res = await apiFetch("/api/push/subscriptions");
      if (res.ok) {
        const data = await res.json();
        setSubscribed(data.subscriptions && data.subscriptions.length > 0);
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

      const existingSubscription = await registration.pushManager.getSubscription();
      const applicationServerKey = urlBase64ToUint8Array(publicKey);

      let subscription: PushSubscription;
      if (existingSubscription) {
        // Re-subscribe if the application server key changed.
        const existingKey = existingSubscription.options.applicationServerKey;
        if (existingKey && arrayBufferToBase64(existingKey) === publicKey) {
          subscription = existingSubscription;
        } else {
          await existingSubscription.unsubscribe();
          subscription = await registration.pushManager.subscribe({
            userVisibleOnly: true,
            applicationServerKey: applicationServerKey as any,
          });
        }
      } else {
        subscription = await registration.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: applicationServerKey as any,
        });
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

      const subRes = await apiFetch("/api/push/subscribe", {
        method: "POST",
        body: JSON.stringify(subData),
      });

      if (!subRes.ok) {
        const detail = await subRes.json().catch(() => null);
        setError(detail?.detail || "Push registration failed");
        return;
      }

      setSubscribed(true);
      setError(null);
    } catch (err) {
      console.error("Subscribe error:", err);
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
"use client";

import { useEffect } from "react";

// Registra o Service Worker de forma segura: em contextos restritos
// (iframe do iOS, WebKit sem permissão), o próprio acesso ao getter
// navigator.serviceWorker pode lançar SecurityError — nunca deve quebrar
// a árvore do React.
export default function ServiceWorkerRegistration() {
  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      if (!("serviceWorker" in navigator)) return;
      navigator.serviceWorker
        .register("/sw.js")
        .then((registration) => {
          console.log("SW registered:", registration.scope);
        })
        .catch((error) => {
          console.error("SW registration failed:", error);
        });
    } catch (error) {
      console.warn("SW registration interrupted:", error);
    }
  }, []);

  return null;
}

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

      // Recarrega uma única vez quando um SW novo assume o controlo
      // (o antecedente tem de existir — numa 1.ª instalação não forçamos
      // reload para não interromper o utilizador).
      const hadController = !!navigator.serviceWorker.controller;
      let refreshing = false;
      navigator.serviceWorker.addEventListener("controllerchange", () => {
        if (!hadController || refreshing) return;
        refreshing = true;
        window.location.reload();
      });

      navigator.serviceWorker
        .register("/sw.js")
        .then((registration) => {
          console.log("SW registered:", registration.scope);
          // Verifica uma versão nova a cada carregamento (o sw.js é servido
          // com `max-age=0`), para que correções do deep link ativem sem
          // esperar o ciclo automático do browser.
          registration.update().catch(() => {});
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

"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { fetchMe, getToken } from "@/lib/api-client";

/**
 * Quando o app abre como PWA standalone (ícone de Tela de Início do iOS /
 * atalho instalado no Android/Desktop) e já existe sessão salva, redireciona
 * IMEDIATAMENTE para o /dashboard em vez de mostrar a landing/login.
 *
 * O iOS Safari compartilha localStorage/cookies com a instância PWA do mesmo
 * origin, então o token persistido no login continua disponível aqui.
 */
export function PwaSessionRedirect() {
  const router = useRouter();

  useEffect(() => {
    const redirect = async () => {
      // Standalone = aberto pelo ícone instalado (não numa aba do navegador).
      let standalone = false;
      try {
        standalone =
          (window.navigator as unknown as { standalone?: boolean }).standalone === true ||
          (window.matchMedia?.("(display-mode: standalone)")?.matches ?? false);
      } catch {
        /* ignore */
      }

      const token = getToken();
      if (!standalone || !token) return;

      // Sessão válida? Valida com /me (reaproveita o helper do api-client,
      // que já aponta para o backend correto e envia o token no header).
      try {
        await fetchMe();
        router.replace("/dashboard");
      } catch {
        /* token expirado/sessão inválida → mantém na landing */
      }
    };
    redirect();
    // Só roda uma vez no load inicial.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Sem renderização visível: só faz o redirect quando aplicável.
  return null;
}
"use client";

import { SWRConfig } from "swr";

/**
 * Cache de dados do dashboard (Fase 23).
 *
 * O layout persiste entre `/dashboard`, `/dashboard/settings`, etc., pelo que
 * o cache SWR sobrevive à troca de rota: a página abre com os dados anteriores
 * (stale) e revalida em segundo plano (stale-while-revalidate).
 *
 * `revalidateOnFocus: false` porque o dashboard já tem refreshInterval por
 * recurso; revalidar no foco duplicaria os pedidos.
 */
const SWR_OPTIONS = {
  revalidateOnFocus: false,
  dedupingInterval: 5000,
  keepPreviousData: true,
  shouldRetryOnError: false,
};

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <SWRConfig value={SWR_OPTIONS}>{children}</SWRConfig>;
}

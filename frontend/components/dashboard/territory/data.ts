import rawSnapshot from "./territory-sample.json";

import type { NicheCount, TerritorySnapshot, Zone } from "./types";

/**
 * Snapshot real (read-only) usado apenas no preview.
 * Produção substitui isto por `GET /api/opportunities/territories`.
 */
export const TERRITORY_SNAPSHOT = rawSnapshot as unknown as TerritorySnapshot;

export const CITY_ORDER = ["Boston", "Dallas", "NYC", "Chicago"] as const;

export const CITY_LABELS: Record<string, string> = {
  Boston: "Boston",
  Dallas: "Dallas",
  NYC: "New York",
  Chicago: "Chicago",
};

interface NicheMeta {
  labelKey: string;
  color: string;
}

/**
 * Cores e rótulos vêm do vocabulário já aprovado do dashboard
 * (`dashboard.cat.*`). Nada de termos de fonte na UI.
 */
export const NICHE_META: Record<string, NicheMeta> = {
  Structure: { labelKey: "dashboard.cat.estrutura", color: "#6366f1" },
  Plumbing: { labelKey: "dashboard.cat.encanamento", color: "#0ea5e9" },
  Roof: { labelKey: "dashboard.cat.telhado", color: "#a78bfa" },
  Electrical: { labelKey: "dashboard.cat.electrical", color: "#fbbf24" },
  Permit_Rejected: { labelKey: "dashboard.cat.obras", color: "#ec4899" },
  Heating: { labelKey: "dashboard.cat.heating", color: "#ef4444" },
  Gas: { labelKey: "dashboard.cat.gas", color: "#f97316" },
  Debris: { labelKey: "dashboard.cat.debris", color: "#64748b" },
  Rodent: { labelKey: "dashboard.cat.rodent", color: "#84cc16" },
  Door_Window: { labelKey: "dashboard.cat.door_window", color: "#14b8a6" },
  Unsanitary: { labelKey: "dashboard.cat.unsanitary", color: "#f43f5e" },
  Mold: { labelKey: "dashboard.cat.mold", color: "#06b6d4" },
  Elevator: { labelKey: "dashboard.cat.elevator", color: "#8b5cf6" },
  Paint: { labelKey: "dashboard.cat.pintura", color: "#f59e0b" },
  Grass: { labelKey: "dashboard.cat.mato", color: "#22c55e" },
  Lead: { labelKey: "dashboard.cat.lead", color: "#a855f7" },
  Unclassified: { labelKey: "dashboard.cat.unclassified", color: "#94a3b8" },
};

export function nicheColor(key: string): string {
  return NICHE_META[key]?.color ?? "#5eead4";
}

export function nicheLabel(key: string, t: (key: string) => string): string {
  const meta = NICHE_META[key];
  if (!meta) return key;
  const value = t(meta.labelKey);
  return value === meta.labelKey ? key : value;
}

export function zoneTitle(zone: Zone, t: (key: string) => string): string {
  if (zone.label) return zone.label;
  return `${t("dashboard.territory.zone_prefix")} ${zone.zip}`;
}

/** Total de um nicho dentro da lista de zonas (respeita filtros ativos). */
export function nicheTotal(zones: Zone[], key: string): number {
  return zones.reduce(
    (sum, zone) => sum + (zone.niches.find((n) => n.key === key)?.n ?? 0),
    0
  );
}

export function topNiches(zones: Zone[], limit = 8): NicheCount[] {
  const totals = new Map<string, number>();
  for (const zone of zones) {
    for (const niche of zone.niches) {
      totals.set(niche.key, (totals.get(niche.key) ?? 0) + niche.n);
    }
  }
  return Array.from(totals.entries())
    .map(([key, n]) => ({ key, n }))
    .sort((a, b) => b.n - a.n)
    .slice(0, limit);
}

export function formatSnapshotDate(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "UTC",
  }).format(date);
}

export function formatDeadline(value: string | null): string | null {
  if (!value) return null;
  const date = new Date(`${value.slice(0, 10)}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  }).format(date);
}

export function daysUntil(value: string | null, now: Date): number | null {
  if (!value) return null;
  const date = new Date(`${value.slice(0, 10)}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) return null;
  return Math.round((date.getTime() - now.getTime()) / 86_400_000);
}

// Tipos e helpers do System Health (Fase 27).
//
// Puro (sem React/SWR): pode ser testado por vitest e reutilizado pela página
// /admin/system-health. O backend é a fonte de verdade dos scores.

export type HealthStatus = "ok" | "warn" | "fail" | "unknown";

export type LayerKey =
  | "ingest"
  | "enrichment"
  | "outreach"
  | "push"
  | "quotas"
  | "infra"
  | "alerts";

export interface HealthMetric {
  key: string;
  label: string;
  value: number | string | null;
  unit: string;
  status: HealthStatus;
  threshold: string;
}

export interface HealthLayer {
  key: LayerKey;
  label: string;
  status: HealthStatus;
  status_label: string;
  score: number;
  headline: string;
  reasons: string[];
  metrics: HealthMetric[];
  detail: Record<string, any>;
}

export interface HealthHistoryPoint {
  captured_at: string;
  status: HealthStatus;
  score: number;
  layers: Record<string, number>;
}

export interface SystemHealth {
  generated_at: string;
  window_hours: number;
  overall: {
    status: HealthStatus;
    status_label: string;
    score: number;
    reasons: string[];
  };
  layers: Record<LayerKey, HealthLayer>;
  history: HealthHistoryPoint[];
}

export const LAYER_ORDER: LayerKey[] = [
  "ingest",
  "enrichment",
  "outreach",
  "push",
  "quotas",
  "infra",
  "alerts",
];

export const LAYER_HINTS: Record<LayerKey, string> = {
  ingest: "Frescura por cidade, runs e inserções",
  enrichment: "Backlog, prontos e quotas de descoberta",
  outreach: "Fila, caixas, bounce e disjuntor",
  push: "Entregas, subscrições mortas e cliques",
  quotas: "Brave e Searchbug vs orçamento",
  infra: "Worker, backup, disco e tokens",
  alerts: "Alertas abertos e idade",
};

export function scoreTone(score: number): HealthStatus {
  if (score >= 90) return "ok";
  if (score >= 60) return "warn";
  return "fail";
}

export function scoreClasses(score: number): {
  text: string;
  bar: string;
  ring: string;
  soft: string;
} {
  const tone = scoreTone(score);
  if (tone === "ok") {
    return {
      text: "text-emerald-400",
      bar: "bg-emerald-400",
      ring: "stroke-emerald-400",
      soft: "bg-emerald-500/10 text-emerald-300",
    };
  }
  if (tone === "warn") {
    return {
      text: "text-amber-400",
      bar: "bg-amber-400",
      ring: "stroke-amber-400",
      soft: "bg-amber-500/10 text-amber-300",
    };
  }
  return {
    text: "text-rose-400",
    bar: "bg-rose-400",
    ring: "stroke-rose-400",
    soft: "bg-rose-500/10 text-rose-300",
  };
}

export function statusClasses(status: HealthStatus): string {
  if (status === "ok") return "bg-emerald-500/15 text-emerald-300 border-emerald-500/30";
  if (status === "warn") return "bg-amber-500/15 text-amber-300 border-amber-500/30";
  if (status === "fail") return "bg-rose-500/15 text-rose-300 border-rose-500/30";
  return "bg-slate-500/15 text-slate-300 border-slate-500/30";
}

export function fmtAge(hours: number | null | undefined): string {
  if (hours == null || Number.isNaN(Number(hours))) return "—";
  const value = Number(hours);
  if (value < 1) return `${Math.round(value * 60)} min`;
  if (value < 48) return `${value.toFixed(1)} h`;
  return `${(value / 24).toFixed(1)} d`;
}

export function fmtWhen(iso: string | null | undefined): string {
  if (!iso) return "—";
  const dt = new Date(iso);
  if (Number.isNaN(dt.getTime())) return "—";
  return `${dt.toLocaleString("pt-PT", {
    timeZone: "UTC",
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  })} UTC`;
}

export function fmtValue(
  value: number | string | null | undefined,
  unit = ""
): string {
  if (value == null || value === "") return "—";
  const text =
    typeof value === "number"
      ? Number.isInteger(value)
        ? String(value)
        : value.toFixed(1)
      : String(value);
  if (!unit) return text;
  if (unit === "%") return `${text}%`;
  if (unit === "$") return `$${text}`;
  if (unit === "min") return `${text} min`;
  return `${text} ${unit}`;
}

/** Série pronta para um sparkline SVG (0–100 no eixo Y). */
export function sparkPoints(
  values: number[],
  width = 120,
  height = 32
): string {
  if (!values.length) return "";
  const step = values.length > 1 ? width / (values.length - 1) : width;
  return values
    .map((value, index) => {
      const x = index * step;
      const y = height - (Math.max(0, Math.min(100, value)) / 100) * height;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
}

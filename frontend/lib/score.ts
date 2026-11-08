/**
 * Escala do Scoring V2.
 *
 * O modelo atual observado vai até 64,22; usamos 65 como teto de exibição.
 * snapshot). A UI antiga assumia 0–100 e pintava tudo de cinzento porque
 * ninguém chegava aos 70. Estes helpers são a única fonte de verdade para
 * barras, cores e filtros.
 */
export const SCORE_MAX = 65;

export type ScoreBand =
  | "elite"
  | "strong"
  | "developing"
  | "low"
  | "unknown";

export interface ScoreRange {
  id: string;
  label: string;
  min: number | null;
  max: number | null;
}

export const SCORE_RANGES: ScoreRange[] = [
  { id: "all", label: "Todos", min: null, max: null },
  { id: "elite", label: "55+", min: 55, max: null },
  { id: "strong", label: "40–54", min: 40, max: 54 },
  { id: "developing", label: "25–39", min: 25, max: 39 },
  { id: "low", label: "0–24", min: 0, max: 24 },
];

export function clampScore(score: number): number {
  if (!Number.isFinite(score)) return 0;
  return Math.max(0, Math.min(SCORE_MAX, score));
}

export function scorePercent(score: number): number {
  return Math.round((clampScore(score) / SCORE_MAX) * 1000) / 10;
}

export function scoreBand(score: number | null | undefined): ScoreBand {
  if (score === null || score === undefined || !Number.isFinite(Number(score))) {
    return "unknown";
  }
  const value = Number(score);
  if (value >= 55) return "elite";
  if (value >= 40) return "strong";
  if (value >= 25) return "developing";
  return "low";
}

export const SCORE_BAND_META: Record<
  ScoreBand,
  { label: string; bar: string; text: string; chip: string; dot: string }
> = {
  elite: {
    label: "Elite",
    bar: "bg-gradient-to-r from-emerald-400 to-teal-300",
    text: "text-emerald-300",
    chip: "border-emerald-400/30 bg-emerald-500/10 text-emerald-200",
    dot: "bg-emerald-400",
  },
  strong: {
    label: "Forte",
    bar: "bg-gradient-to-r from-sky-400 to-cyan-300",
    text: "text-sky-300",
    chip: "border-sky-400/30 bg-sky-500/10 text-sky-200",
    dot: "bg-sky-400",
  },
  developing: {
    label: "Em desenvolvimento",
    bar: "bg-gradient-to-r from-amber-400 to-yellow-300",
    text: "text-amber-300",
    chip: "border-amber-400/30 bg-amber-500/10 text-amber-200",
    dot: "bg-amber-400",
  },
  low: {
    label: "Baixo",
    bar: "bg-gradient-to-r from-rose-500 to-orange-400",
    text: "text-rose-300",
    chip: "border-rose-400/30 bg-rose-500/10 text-rose-200",
    dot: "bg-rose-400",
  },
  unknown: {
    label: "Sem score",
    bar: "bg-slate-600",
    text: "text-slate-400",
    chip: "border-white/10 bg-white/5 text-slate-300",
    dot: "bg-slate-500",
  },
};

export function formatScore(score: number | null | undefined): string {
  if (score === null || score === undefined || !Number.isFinite(Number(score))) {
    return "–";
  }
  const value = Number(score);
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}

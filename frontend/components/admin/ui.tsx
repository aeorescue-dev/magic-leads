"use client";

import type { ReactNode } from "react";
import { scoreBand, scorePercent, formatScore, SCORE_BAND_META } from "@/lib/score";

export function cn(...values: Array<string | false | null | undefined>) {
  return values.filter(Boolean).join(" ");
}

/* ------------------------------------------------------------------ surface */

export function Surface({
  children,
  className,
  glow = "none",
}: {
  children: ReactNode;
  className?: string;
  glow?: "none" | "emerald" | "sky" | "amber" | "rose";
}) {
  const glowClass = {
    none: "",
    emerald: "shadow-[0_0_80px_-40px_rgba(16,185,129,0.45)]",
    sky: "shadow-[0_0_80px_-40px_rgba(56,189,248,0.45)]",
    amber: "shadow-[0_0_80px_-40px_rgba(245,158,11,0.45)]",
    rose: "shadow-[0_0_80px_-40px_rgba(244,63,94,0.45)]",
  }[glow];
  return (
    <section
      className={cn(
        "relative overflow-hidden rounded-2xl border border-white/[0.07] bg-[#0e1118]/90 backdrop-blur-xl",
        "shadow-[0_24px_80px_-48px_rgba(0,0,0,0.95)]",
        glowClass,
        className
      )}
    >
      <div className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-white/15 to-transparent" />
      {children}
    </section>
  );
}

/* -------------------------------------------------------------- metric card */

const TONE = {
  emerald: {
    icon: "border-emerald-400/20 bg-emerald-500/10 text-emerald-300",
    value: "text-emerald-200",
    line: "from-emerald-400/70 via-emerald-400/20 to-transparent",
  },
  sky: {
    icon: "border-sky-400/20 bg-sky-500/10 text-sky-300",
    value: "text-sky-200",
    line: "from-sky-400/70 via-sky-400/20 to-transparent",
  },
  amber: {
    icon: "border-amber-400/20 bg-amber-500/10 text-amber-300",
    value: "text-amber-200",
    line: "from-amber-400/70 via-amber-400/20 to-transparent",
  },
  rose: {
    icon: "border-rose-400/20 bg-rose-500/10 text-rose-300",
    value: "text-rose-200",
    line: "from-rose-400/70 via-rose-400/20 to-transparent",
  },
  violet: {
    icon: "border-violet-400/20 bg-violet-500/10 text-violet-300",
    value: "text-violet-200",
    line: "from-violet-400/70 via-violet-400/20 to-transparent",
  },
  slate: {
    icon: "border-white/10 bg-white/5 text-slate-300",
    value: "text-slate-100",
    line: "from-slate-400/60 via-slate-400/10 to-transparent",
  },
};

export type MetricTone = keyof typeof TONE;

export function MetricCard({
  label,
  value,
  sub,
  icon,
  tone = "slate",
  footer,
  className,
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  icon?: ReactNode;
  tone?: MetricTone;
  footer?: ReactNode;
  className?: string;
}) {
  const t = TONE[tone];
  return (
    <div
      className={cn(
        "group relative overflow-hidden rounded-2xl border border-white/[0.07] bg-white/[0.025] p-4",
        "transition duration-300 hover:-translate-y-0.5 hover:border-white/15 hover:bg-white/[0.04]",
        className
      )}
    >
      <div
        className={cn(
          "absolute inset-x-0 top-0 h-px bg-gradient-to-r opacity-70",
          t.line
        )}
      />
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">
            {label}
          </p>
          <p className={cn("mt-2 text-2xl font-black tracking-tight", t.value)}>
            {value}
          </p>
          {sub ? (
            <p className="mt-1 text-[11px] leading-relaxed text-slate-500">{sub}</p>
          ) : null}
        </div>
        {icon ? (
          <span
            className={cn(
              "flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border",
              t.icon
            )}
          >
            {icon}
          </span>
        ) : null}
      </div>
      {footer ? <div className="mt-3">{footer}</div> : null}
    </div>
  );
}

/* --------------------------------------------------------------- status pill */

const PILL = {
  ok: "border-emerald-400/25 bg-emerald-500/10 text-emerald-200",
  warn: "border-amber-400/25 bg-amber-500/10 text-amber-200",
  fail: "border-rose-400/25 bg-rose-500/10 text-rose-200",
  info: "border-sky-400/25 bg-sky-500/10 text-sky-200",
  neutral: "border-white/10 bg-white/5 text-slate-300",
};

export function StatusPill({
  state = "neutral",
  children,
  pulse = false,
  className,
}: {
  state?: keyof typeof PILL;
  children: ReactNode;
  pulse?: boolean;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[10px] font-bold uppercase tracking-wide",
        PILL[state],
        className
      )}
    >
      <span className="relative flex h-1.5 w-1.5">
        {pulse ? (
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-current opacity-60" />
        ) : null}
        <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-current" />
      </span>
      {children}
    </span>
  );
}

/* ----------------------------------------------------------------- score ui */

export function ScoreBar({
  score,
  showLabel = true,
  compact = false,
}: {
  score: number | null | undefined;
  showLabel?: boolean;
  compact?: boolean;
}) {
  const band = scoreBand(score);
  const meta = SCORE_BAND_META[band];
  const pct = scorePercent(Number(score ?? 0));
  return (
    <div className="flex min-w-[110px] items-center gap-2">
      <div
        className={cn(
          "relative flex-1 overflow-hidden rounded-full bg-white/[0.06]",
          compact ? "h-1.5" : "h-2"
        )}
      >
        <div
          className={cn("h-full rounded-full transition-all duration-500", meta.bar)}
          style={{ width: `${pct}%` }}
        />
      </div>
      {showLabel ? (
        <span className={cn("w-8 text-right text-[10px] font-bold tabular-nums", meta.text)}>
          {formatScore(score)}
        </span>
      ) : null}
    </div>
  );
}

export function ScoreBadge({ score }: { score: number | null | undefined }) {
  const band = scoreBand(score);
  const meta = SCORE_BAND_META[band];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[10px] font-bold",
        meta.chip
      )}
    >
      <span className={cn("h-1.5 w-1.5 rounded-full", meta.dot)} />
      {formatScore(score)}
    </span>
  );
}

export function ScoreHistogram({
  buckets,
  total,
  className,
}: {
  buckets: Array<{ bucket: number; label: string; n: number }>;
  total: number;
  className?: string;
}) {
  const max = Math.max(1, ...buckets.map((b) => b.n));
  const colors = [
    "from-rose-500/80 to-rose-400/30",
    "from-orange-500/80 to-orange-400/30",
    "from-amber-400/80 to-amber-300/30",
    "from-sky-400/80 to-sky-300/30",
    "from-emerald-400/80 to-emerald-300/30",
    "from-teal-400/80 to-teal-300/30",
    "from-cyan-400/80 to-cyan-300/30",
  ];
  return (
    <div className={cn("space-y-2", className)}>
      <div className="flex h-28 items-end gap-1.5">
        {buckets.map((bucket, index) => (
          <div key={bucket.bucket} className="group flex h-full flex-1 flex-col justify-end">
            <div className="relative">
              <div
                className={cn(
                  "w-full rounded-t-md bg-gradient-to-t transition-all duration-500 group-hover:opacity-90",
                  colors[index % colors.length]
                )}
                style={{ height: `${Math.max(4, (bucket.n / max) * 100)}%` }}
                title={`${bucket.label}: ${bucket.n}`}
              />
            </div>
            <span className="mt-1 text-center text-[9px] tabular-nums text-slate-500">
              {bucket.bucket}
            </span>
          </div>
        ))}
      </div>
      <div className="flex items-center justify-between text-[10px] text-slate-500">
        <span>distribuição por faixa</span>
        <span className="tabular-nums">
          {total.toLocaleString("pt-PT")} prospects
        </span>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ filters */

export function FilterChip({
  active,
  children,
  onClick,
  className,
}: {
  active: boolean;
  children: ReactNode;
  onClick: () => void;
  className?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "rounded-full border px-3 py-1.5 text-[10px] font-bold uppercase tracking-wide transition",
        active
          ? "border-emerald-400/40 bg-emerald-500/15 text-emerald-200 shadow-[0_0_24px_-12px_rgba(16,185,129,0.8)]"
          : "border-white/10 bg-white/[0.03] text-slate-400 hover:border-white/20 hover:text-slate-200",
        className
      )}
    >
      {children}
    </button>
  );
}

export function SelectField({
  value,
  onChange,
  options,
  placeholder,
  className,
  ariaLabel,
}: {
  value: string;
  onChange: (value: string) => void;
  options: Array<{ value: string; label: string }>;
  placeholder?: string;
  className?: string;
  ariaLabel?: string;
}) {
  return (
    <select
      aria-label={ariaLabel}
      value={value}
      onChange={(event) => onChange(event.target.value)}
      className={cn(
        "h-9 rounded-xl border border-white/10 bg-[#0b0e14] px-3 text-[11px] font-semibold text-slate-200",
        "outline-none transition focus:border-emerald-400/40 focus:ring-2 focus:ring-emerald-400/10",
        className
      )}
    >
      {placeholder ? <option value="">{placeholder}</option> : null}
      {options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  );
}

export function DateField({
  value,
  onChange,
  label,
}: {
  value: string;
  onChange: (value: string) => void;
  label: string;
}) {
  return (
    <label className="flex items-center gap-1.5 rounded-xl border border-white/10 bg-[#0b0e14] px-2.5 py-1.5 text-[10px] font-semibold text-slate-400">
      <span className="uppercase tracking-wide text-slate-600">{label}</span>
      <input
        type="date"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="bg-transparent text-[11px] text-slate-200 outline-none [color-scheme:dark]"
      />
    </label>
  );
}

/* ------------------------------------------------------------------ helpers */

export function SectionHeader({
  eyebrow,
  title,
  description,
  icon,
  action,
}: {
  eyebrow: string;
  title: string;
  description?: string;
  icon?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-4">
      <div className="flex items-start gap-3">
        {icon ? (
          <span className="mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl border border-emerald-400/20 bg-gradient-to-br from-emerald-400/15 to-sky-400/5 text-emerald-300">
            {icon}
          </span>
        ) : null}
        <div>
          <p className="text-[10px] font-bold uppercase tracking-[0.22em] text-emerald-300/80">
            {eyebrow}
          </p>
          <h2 className="text-xl font-black tracking-tight text-white">{title}</h2>
          {description ? (
            <p className="mt-1 max-w-3xl text-xs leading-relaxed text-slate-400">
              {description}
            </p>
          ) : null}
        </div>
      </div>
      {action}
    </div>
  );
}

export function EmptyState({
  icon,
  title,
  description,
}: {
  icon?: ReactNode;
  title: string;
  description?: string;
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-white/10 bg-white/[0.02] px-6 py-10 text-center">
      {icon ? <div className="mb-2 text-slate-600">{icon}</div> : null}
      <p className="text-sm font-semibold text-slate-300">{title}</p>
      {description ? (
        <p className="mt-1 max-w-md text-xs text-slate-500">{description}</p>
      ) : null}
    </div>
  );
}

export function ProgressRing({
  value,
  max = 100,
  size = 64,
  stroke = 7,
  tone = "emerald",
  label,
}: {
  value: number;
  max?: number;
  size?: number;
  stroke?: number;
  tone?: "emerald" | "sky" | "amber" | "rose";
  label?: ReactNode;
}) {
  const pct = Math.max(0, Math.min(100, (value / Math.max(1, max)) * 100));
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const color = {
    emerald: "#34d399",
    sky: "#38bdf8",
    amber: "#fbbf24",
    rose: "#fb7185",
  }[tone];
  return (
    <div className="relative inline-flex items-center justify-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          stroke="rgba(255,255,255,0.07)"
          strokeWidth={stroke}
          fill="none"
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          stroke={color}
          strokeWidth={stroke}
          strokeLinecap="round"
          fill="none"
          strokeDasharray={`${(pct / 100) * circumference} ${circumference}`}
          className="transition-all duration-700"
        />
      </svg>
      <span className="absolute text-sm font-black text-white">{label ?? Math.round(pct)}</span>
    </div>
  );
}

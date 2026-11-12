"use client";

import type { LucideIcon } from "lucide-react";

export interface KpiSatellite {
  label: string;
  value: number;
  delta: string;
  icon: LucideIcon;
  tone?: "accent" | "urgent" | "warn" | "info";
  progress?: number;
  onClick?: () => void;
}

const toneColor: Record<NonNullable<KpiSatellite["tone"]>, string> = {
  accent: "var(--sd-accent)",
  urgent: "var(--sd-urgent)",
  warn: "var(--sd-warn)",
  info: "var(--sd-info)",
};

function KpiCard({
  label,
  value,
  delta,
  icon: Icon,
  color,
  progress,
  onClick,
  hero = false,
}: {
  label: string;
  value: number;
  delta: string;
  icon: LucideIcon;
  color: string;
  progress?: number;
  onClick?: () => void;
  hero?: boolean;
}) {
  const body = (
    <>
      <div className="flex items-start justify-between gap-3">
        <span className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[var(--sd-muted)]">
          {label}
        </span>
        <span
          className="grid h-8 w-8 shrink-0 place-items-center rounded-xl"
          style={{
            color,
            background: `color-mix(in srgb, ${color} 12%, transparent)`,
          }}
        >
          <Icon className="h-4 w-4" />
        </span>
      </div>
      <div className="mt-4">
        <div
          className="sd-tabular text-3xl font-semibold tracking-[-0.04em] text-[var(--sd-text)] md:text-4xl"
          aria-live="polite"
        >
          {Number(value || 0).toLocaleString()}
        </div>
        <div className="mt-2 flex items-center gap-1.5 text-[10.5px] text-[var(--sd-muted)]">
          <span className="h-1.5 w-1.5 rounded-full" style={{ background: color }} />
          <span className="truncate">{delta}</span>
        </div>
        {typeof progress === "number" && (
          <div className="mt-3 h-1 overflow-hidden rounded-full bg-[var(--sd-border)]">
            <div
              className="h-full rounded-full"
              style={{ width: `${Math.max(0, Math.min(100, progress))}%`, background: color }}
            />
          </div>
        )}
      </div>
    </>
  );

  const className = `relative min-w-0 overflow-hidden rounded-2xl border border-[var(--sd-border)] bg-[var(--sd-surface)] p-5 text-left ${
    onClick ? "sd-focus transition hover:border-[var(--sd-border-strong)] hover:bg-[var(--sd-surface-2)]" : ""
  } ${hero ? "ring-1 ring-[var(--sd-border-strong)]" : ""}`;

  return onClick ? (
    <button type="button" onClick={onClick} className={className}>
      {body}
    </button>
  ) : (
    <div className={className}>{body}</div>
  );
}

export function KpiPulse({
  hero,
  satellites,
  onHero,
}: {
  hero: { label: string; value: number; delta: string; icon: LucideIcon };
  satellites: KpiSatellite[];
  onHero?: () => void;
}) {
  return (
    <section
      aria-label="Resumo de oportunidades"
      className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4"
    >
      <KpiCard
        label={hero.label}
        value={hero.value}
        delta={hero.delta}
        icon={hero.icon}
        color="var(--sd-accent)"
        onClick={onHero}
        hero
      />
      {satellites.map((item) => (
        <KpiCard
          key={item.label}
          label={item.label}
          value={item.value}
          delta={item.delta}
          icon={item.icon}
          color={toneColor[item.tone || "accent"]}
          progress={item.progress}
          onClick={item.onClick}
        />
      ))}
    </section>
  );
}

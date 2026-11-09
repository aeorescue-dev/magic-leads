"use client";

import type { LucideIcon } from "lucide-react";

export interface KpiSatellite {
  label: string;
  value: number;
  delta: string;
  icon: LucideIcon;
  tone?: "accent" | "urgent" | "warn" | "info";
  onClick?: () => void;
}

const toneColor: Record<NonNullable<KpiSatellite["tone"]>, string> = {
  accent: "var(--sd-accent)",
  urgent: "var(--sd-urgent)",
  warn: "var(--sd-warn)",
  info: "var(--sd-info)",
};

export function KpiPulse({
  hero,
  satellites,
  onHero,
}: {
  hero: { label: string; value: number; delta: string; icon: LucideIcon };
  satellites: KpiSatellite[];
  onHero?: () => void;
}) {
  const HeroIcon = hero.icon;

  return (
    <section
      aria-label="Resumo de oportunidades"
      className="overflow-hidden rounded-2xl border border-[var(--sd-border)] bg-[var(--sd-surface)]"
    >
      <div className="grid grid-cols-1 md:grid-cols-[1.15fr_2fr]">
        <button
          type="button"
          onClick={onHero}
          className="sd-focus group relative flex flex-col justify-between border-b border-[var(--sd-border)] p-5 text-left transition hover:bg-[var(--sd-surface-2)] md:border-b-0 md:border-r"
        >
          <div className="flex items-center justify-between gap-3">
            <span className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[var(--sd-muted)]">
              {hero.label}
            </span>
            <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-[var(--sd-accent-soft)] text-[var(--sd-accent)]">
              <HeroIcon className="h-4 w-4" />
            </span>
          </div>
          <div className="mt-4">
            <div
              className="sd-tabular text-4xl font-semibold tracking-[-0.04em] text-[var(--sd-text)] md:text-5xl"
              aria-live="polite"
            >
              {Number(hero.value || 0).toLocaleString()}
            </div>
            <div className="mt-2 flex items-center gap-1.5 text-[11px] text-[var(--sd-muted)]">
              <span className="h-1.5 w-1.5 rounded-full bg-[var(--sd-accent)]" />
              {hero.delta}
            </div>
          </div>
        </button>

        <div className="grid grid-cols-3 divide-x divide-[var(--sd-border)]">
          {satellites.map((item) => {
            const Icon = item.icon;
            const color = toneColor[item.tone || "accent"];
            const content = (
              <>
                <div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-[var(--sd-muted)]">
                  <Icon className="h-3.5 w-3.5" style={{ color }} />
                  <span className="truncate">{item.label}</span>
                </div>
                <div className="mt-3">
                  <div
                    className="sd-tabular text-xl font-semibold tracking-tight text-[var(--sd-text)] md:text-2xl"
                    style={{ color }}
                  >
                    {Number(item.value || 0).toLocaleString()}
                  </div>
                  <div className="mt-1 truncate text-[10px] text-[var(--sd-faint)]">
                    {item.delta}
                  </div>
                </div>
              </>
            );
            const className = `flex min-w-0 flex-col justify-between p-4 text-left transition ${
              item.onClick ? "sd-focus hover:bg-[var(--sd-surface-2)]" : ""
            }`;
            return item.onClick ? (
              <button key={item.label} type="button" onClick={item.onClick} className={className}>
                {content}
              </button>
            ) : (
              <div key={item.label} className={className}>
                {content}
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}

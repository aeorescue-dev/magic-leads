"use client";

import type { LucideIcon } from "lucide-react";

export interface KpiSatellite {
  label: string;
  value: number;
  delta: string;
  icon: LucideIcon;
  tone?: "accent" | "urgent" | "warn" | "info";
  progress?: number;
  series?: number[];
  sub?: string;
  prefix?: string;
  suffix?: string;
  onClick?: () => void;
  dark?: boolean;
}

const toneColor: Record<NonNullable<KpiSatellite["tone"]>, string> = {
  accent: "var(--sd-accent)",
  urgent: "var(--sd-urgent)",
  warn: "var(--sd-warn)",
  info: "var(--sd-info)",
};

function Sparkline({ series, color }: { series?: number[]; color: string }) {
  const bars = (series && series.length ? series : [0, 0, 0, 0, 0, 0, 0, 0, 0, 0]).slice(-10);
  const max = Math.max(...bars, 1);
  return (
    <div className="mt-3 flex h-6 items-end gap-[3px]" aria-hidden="true">
      {bars.map((value, index) => {
        const height = Math.max(8, Math.round((value / max) * 100));
        const active = index === bars.length - 1;
        return (
          <span
            key={index}
            className="min-w-0 flex-1 rounded-t-[3px]"
            style={{
              height: `${height}%`,
              background: active ? color : `color-mix(in srgb, ${color} 26%, var(--sd-border))`,
            }}
          />
        );
      })}
    </div>
  );
}

function KpiCard({
  label,
  value,
  delta,
  sub,
  series,
  prefix,
  suffix,
  icon: Icon,
  color,
  progress,
  onClick,
  hero = false,
  dark = false,
}: {
  label: string;
  value: number;
  delta: string;
  sub?: string;
  series?: number[];
  prefix?: string;
  suffix?: string;
  icon: LucideIcon;
  color: string;
  progress?: number;
  onClick?: () => void;
  hero?: boolean;
  dark?: boolean;
}) {
  const body = (
    <>
      <div className="relative z-[1] flex items-start justify-between gap-3">
        <span
          className={`text-[10px] font-semibold uppercase tracking-[0.14em] ${
            dark ? "text-white/45" : "text-[var(--sd-muted)]"
          }`}
        >
          {label}
        </span>
        <span
          className="grid h-8 w-8 shrink-0 place-items-center rounded-xl"
          style={{
            color: dark ? "var(--sd-accent)" : color,
            background: dark
              ? "color-mix(in srgb, var(--sd-accent) 16%, transparent)"
              : `color-mix(in srgb, ${color} 12%, transparent)`,
          }}
        >
          <Icon className="h-4 w-4" />
        </span>
      </div>
      <div className="relative z-[1] mt-4">
        <div
          className={`sd-tabular text-3xl font-semibold tracking-[-0.04em] md:text-4xl ${
            dark ? "text-white" : "text-[var(--sd-text)]"
          }`}
          aria-live="polite"
        >
          {prefix ? <span className="mr-0.5 text-[0.55em] font-bold align-top">{prefix}</span> : null}
          {Number(value || 0).toLocaleString()}
          {suffix ? <span className="ml-0.5 text-[0.55em] font-bold">{suffix}</span> : null}
        </div>
        <div
          className={`mt-2 flex items-center gap-1.5 text-[10.5px] ${
            dark ? "text-white/55" : "text-[var(--sd-muted)]"
          }`}
        >
          <span className="h-1.5 w-1.5 rounded-full" style={{ background: color }} />
          <span className="truncate">{delta}</span>
        </div>
        {sub ? (
          <div
            className={`mt-1 truncate text-[10px] font-semibold ${
              dark ? "text-white/40" : "text-[var(--sd-faint)]"
            }`}
          >
            {sub}
          </div>
        ) : null}
        {typeof progress === "number" && (
          <div
            className={`mt-3 h-1 overflow-hidden rounded-full ${
              dark ? "bg-white/10" : "bg-[var(--sd-border)]"
            }`}
          >
            <div
              className="h-full rounded-full"
              style={{ width: `${Math.max(0, Math.min(100, progress))}%`, background: color }}
            />
          </div>
        )}
        <Sparkline series={series} color={dark ? "var(--sd-accent)" : color} />
      </div>
    </>
  );

  const className = `relative min-w-0 overflow-hidden rounded-2xl border p-5 text-left ${
    dark
      ? "bg-[linear-gradient(145deg,#0a1c19,#08131a_58%,#070c14)] text-white"
      : "border-[var(--sd-border)] bg-[var(--sd-surface)]"
  } ${onClick ? "sd-focus transition hover:border-[var(--sd-border-strong)] hover:bg-[var(--sd-surface-2)]" : ""} ${
    hero && !dark ? "ring-1 ring-[var(--sd-border-strong)]" : ""
  }`;
  const cardStyle = dark
    ? { borderColor: "color-mix(in srgb, var(--sd-accent) 30%, transparent)" }
    : undefined;

  return onClick ? (
    <button type="button" onClick={onClick} className={className} style={cardStyle}>
      {dark ? (
        <span
          aria-hidden="true"
          className="pointer-events-none absolute -right-12 -top-16 h-40 w-40 rounded-full bg-[var(--sd-accent)] opacity-20 blur-3xl"
        />
      ) : null}
      {body}
    </button>
  ) : (
    <div className={className} style={cardStyle}>
      {dark ? (
        <span
          aria-hidden="true"
          className="pointer-events-none absolute -right-12 -top-16 h-40 w-40 rounded-full bg-[var(--sd-accent)] opacity-20 blur-3xl"
        />
      ) : null}
      {body}
    </div>
  );
}

export function KpiPulse({
  hero,
  satellites,
  onHero,
}: {
  hero: {
    label: string;
    value: number;
    delta: string;
    sub?: string;
    series?: number[];
    prefix?: string;
    suffix?: string;
    icon: LucideIcon;
  };
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
        sub={hero.sub}
        series={hero.series}
        prefix={hero.prefix}
        suffix={hero.suffix}
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
          sub={item.sub}
          series={item.series}
          prefix={item.prefix}
          suffix={item.suffix}
          icon={item.icon}
          color={toneColor[item.tone || "accent"]}
          progress={item.progress}
          onClick={item.onClick}
          dark={item.dark}
        />
      ))}
    </section>
  );
}

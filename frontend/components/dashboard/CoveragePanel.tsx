"use client";

import { Activity, Clock, MapPin, ShieldCheck } from "lucide-react";
import { useI18n } from "@/lib/i18n";

const CITY_LABELS: Record<string, string> = {
  NYC: "New York",
  Chicago: "Chicago",
  Dallas: "Dallas",
  Boston: "Boston",
};

function parseServerTime(value?: string | null): number | null {
  if (!value) return null;
  const normalized = /Z$|[+-]\d{2}:?\d{2}$/.test(value) ? value : `${value}Z`;
  const ms = Date.parse(normalized);
  return Number.isFinite(ms) ? ms : null;
}

function formatAgo(value?: string | null): string {
  const ms = parseServerTime(value);
  if (ms === null) return "—";
  const minutes = Math.max(0, Math.round((Date.now() - ms) / 60000));
  if (minutes < 1) return "0 min";
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest ? `${hours}h ${rest}m` : `${hours}h`;
}

export function CoveragePanel({
  byCity,
  coverage,
  withContactPct,
  activeZips,
  tradesCount,
  finishedAt,
}: {
  byCity: Record<string, number>;
  coverage?: Record<string, { active: number; owners: number; pct: number }>;
  withContactPct: number;
  activeZips: number;
  tradesCount: number;
  finishedAt?: string | null;
}) {
  const { t } = useI18n();
  const rows = Object.entries(byCity)
    .filter(([city]) => CITY_LABELS[city])
    .map(([city, active]) => ({
      city: CITY_LABELS[city],
      active,
      pct: coverage?.[city]?.pct ?? 0,
    }))
    .sort((a, b) => b.active - a.active);
  const max = rows[0]?.active || 1;
  const updated = formatAgo(finishedAt);

  return (
    <section className="grid gap-3 lg:grid-cols-[1.55fr_1fr]">
      <div className="rounded-2xl border border-[var(--sd-border)] bg-[var(--sd-surface)] p-5">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <h2 className="text-[14px] font-semibold tracking-tight text-[var(--sd-text)]">
              {t("dashboard.coverage.title") || "Cobertura por praça"}
            </h2>
            <p className="mt-1 text-[10.5px] text-[var(--sd-muted)]">
              {t("dashboard.coverage.sub") || "Oportunidades ativas e proprietário identificado"}
            </p>
          </div>
          <div className="flex flex-col items-end gap-1">
            <span className="rounded-full border border-[var(--sd-border)] px-2 py-0.5 text-[8px] font-bold uppercase tracking-[0.12em] text-[var(--sd-muted)]">
              {t("dashboard.coverage.days") || "7 dias"}
            </span>
            <span className="inline-flex items-center gap-1 text-[9px] text-[var(--sd-faint)]">
              <Clock className="h-3 w-3" />
              {t("dashboard.coverage.updated").replace("{time}", updated)}
            </span>
          </div>
        </div>

        <div className="mt-4 space-y-3">
          {rows.map((row) => {
            const width = Math.max(6, Math.round((row.active / max) * 100));
            return (
              <div
                key={row.city}
                className="grid grid-cols-[96px_1fr_56px_44px] items-center gap-2.5"
              >
                <span className="inline-flex min-w-0 items-center gap-1.5 text-[11px] font-semibold text-[var(--sd-text)]">
                  <MapPin className="h-3 w-3 shrink-0 text-[var(--sd-accent)]" />
                  <span className="truncate">{row.city}</span>
                </span>
                <span className="hidden h-1.5 overflow-hidden rounded-full bg-[var(--sd-border)] sm:block">
                  <span
                    className="block h-full rounded-full bg-[var(--sd-accent)]"
                    style={{ width: `${width}%` }}
                  />
                </span>
                <span className="sd-tabular text-right text-[11.5px] font-semibold text-[var(--sd-text)]">
                  {row.active.toLocaleString()}
                </span>
                <span className="sd-tabular text-right text-[10px] font-semibold text-[var(--sd-info)]">
                  {row.pct}%
                </span>
              </div>
            );
          })}
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-1">
        {[
          {
            icon: ShieldCheck,
            value: `${withContactPct}%`,
            label: t("dashboard.coverage.owner") || "com dono",
            color: "var(--sd-info)",
          },
          {
            icon: MapPin,
            value: activeZips.toLocaleString(),
            label: t("dashboard.coverage.zips") || "ZIPs cobertos",
            color: "var(--sd-accent)",
          },
          {
            icon: Activity,
            value: String(tradesCount),
            label: t("dashboard.coverage.trades") || "ofícios ativos",
            color: "var(--sd-accent)",
          },
        ].map((item) => (
          <div
            key={item.label}
            className="flex items-center gap-3 rounded-2xl border border-[var(--sd-border)] bg-[var(--sd-surface)] px-4 py-3"
          >
            <span
              className="grid h-8 w-8 shrink-0 place-items-center rounded-xl"
              style={{
                color: item.color,
                background: `color-mix(in srgb, ${item.color} 12%, transparent)`,
              }}
            >
              <item.icon className="h-4 w-4" />
            </span>
            <div className="min-w-0">
              <p
                className="sd-tabular text-[15px] font-semibold leading-none"
                style={{ color: item.color }}
              >
                {item.value}
              </p>
              <p className="mt-1 truncate text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--sd-muted)]">
                {item.label}
              </p>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

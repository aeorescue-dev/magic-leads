"use client";

import { ArrowUpRight, BarChart3, Clock, MapPin } from "lucide-react";
import { useI18n } from "@/lib/i18n";

export interface RailDeadline {
  id: number | string;
  address: string;
  city?: string | null;
  severity?: string | null;
  days_left: number;
}

export interface RailSeverity {
  critical: number;
  high: number;
  medium: number;
  routine: number;
}

export function FeedRail({
  deadlines,
  severity,
  zips,
  onOpenDeadline,
  onSeeAll,
  onOpenMap,
}: {
  deadlines: RailDeadline[];
  severity: RailSeverity;
  zips: Array<{ zip: string; count: number }>;
  onOpenDeadline?: (id: number | string) => void;
  onSeeAll?: () => void;
  onOpenMap?: () => void;
}) {
  const { t } = useI18n();
  const total = severity.critical + severity.high + severity.medium + severity.routine;
  const zipMax = Math.max(...zips.map((item) => item.count), 1);

  const severityRows: Array<{ key: keyof RailSeverity; color: string; label: string }> = [
    { key: "critical", color: "#ef4444", label: t("dashboard.severity.critical") },
    { key: "high", color: "#f59e0b", label: t("dashboard.severity.high") },
    { key: "medium", color: "#2563eb", label: t("dashboard.severity.medium") },
    { key: "routine", color: "#cbd5e1", label: t("dashboard.severity.routine") },
  ];

  return (
    <aside className="space-y-3 self-start xl:sticky xl:top-4">
      <section className="rounded-2xl border border-[var(--sd-border)] bg-[var(--sd-surface)] p-3.5">
        <div className="flex items-center justify-between gap-2">
          <h3 className="flex items-center gap-1.5 text-[11px] font-bold tracking-[-0.01em] text-[var(--sd-text)]">
            <Clock className="h-3.5 w-3.5 text-[var(--sd-faint)]" />
            {t("dashboard.rail.deadlines")}
          </h3>
          <button
            type="button"
            onClick={onSeeAll}
            className="text-[9px] font-bold uppercase tracking-[0.07em] text-[var(--sd-accent)] hover:underline"
          >
            {t("dashboard.rail.see_all")}
          </button>
        </div>

        {deadlines.length === 0 ? (
          <p className="mt-3 text-[11px] text-[var(--sd-faint)]">{t("dashboard.rail.empty_deadlines")}</p>
        ) : (
          <div className="mt-2 divide-y divide-dashed divide-[var(--sd-border)]">
            {deadlines.map((item) => {
              const tone = item.days_left <= 2 ? "critical" : item.days_left <= 7 ? "soon" : "later";
              const toneClass =
                tone === "critical"
                  ? "border-red-500/40 bg-red-500/10 text-red-500"
                  : tone === "soon"
                    ? "border-amber-500/40 bg-amber-500/10 text-amber-500"
                    : "border-[var(--sd-border)] bg-[var(--sd-surface-2)] text-[var(--sd-muted)]";
              return (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => onOpenDeadline?.(item.id)}
                  className="flex w-full items-center gap-2 py-2 text-left last:pb-0.5"
                >
                  <span
                    className={`grid h-8 w-8 shrink-0 place-items-center rounded-lg border text-[11px] font-black leading-none ${toneClass}`}
                  >
                    {item.days_left}
                    <small className="block text-[5.5px] font-bold uppercase tracking-[0.06em]">
                      {item.days_left === 1 ? t("dashboard.rail.day_short") : t("dashboard.rail.days_short")}
                    </small>
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[10.5px] font-bold text-[var(--sd-text)]">
                      {item.address}
                    </span>
                    <span className="mt-0.5 block truncate text-[9px] text-[var(--sd-faint)]">
                      {item.city ? `${item.city} · ` : ""}
                      {t("dashboard.rail.deadline_meta")}
                    </span>
                  </span>
                  <ArrowUpRight className="h-3.5 w-3.5 shrink-0 text-[var(--sd-faint)]" />
                </button>
              );
            })}
          </div>
        )}
      </section>

      <section className="rounded-2xl border border-[var(--sd-border)] bg-[var(--sd-surface)] p-3.5">
        <h3 className="flex items-center gap-1.5 text-[11px] font-bold tracking-[-0.01em] text-[var(--sd-text)]">
          <BarChart3 className="h-3.5 w-3.5 text-[var(--sd-faint)]" />
          {t("dashboard.rail.severity")}
        </h3>
        <div className="mt-3 flex h-2 overflow-hidden rounded-full bg-[var(--sd-border)]">
          {severityRows.map((row) =>
            severity[row.key] > 0 ? (
              <span
                key={row.key}
                style={{
                  width: `${(severity[row.key] / Math.max(total, 1)) * 100}%`,
                  background: row.color,
                }}
              />
            ) : null,
          )}
        </div>
        <div className="mt-2.5 grid grid-cols-2 gap-x-3 gap-y-1.5">
          {severityRows.map((row) => (
            <span
              key={row.key}
              className="flex items-center gap-1.5 text-[9px] font-semibold text-[var(--sd-muted)]"
            >
              <i className="h-1.5 w-1.5 shrink-0 rounded-[2px]" style={{ background: row.color }} />
              <span className="truncate">{row.label}</span>
              <b className="ml-auto text-[var(--sd-text)]">{severity[row.key]}</b>
            </span>
          ))}
        </div>
      </section>

      <section className="rounded-2xl border border-[var(--sd-border)] bg-[var(--sd-surface)] p-3.5">
        <div className="flex items-center justify-between gap-2">
          <h3 className="flex items-center gap-1.5 text-[11px] font-bold tracking-[-0.01em] text-[var(--sd-text)]">
            <MapPin className="h-3.5 w-3.5 text-[var(--sd-faint)]" />
            {t("dashboard.rail.zips")}
          </h3>
          <button
            type="button"
            onClick={onOpenMap}
            className="text-[9px] font-bold uppercase tracking-[0.07em] text-[var(--sd-accent)] hover:underline"
          >
            {t("dashboard.rail.map")}
          </button>
        </div>
        {zips.length === 0 ? (
          <p className="mt-3 text-[11px] text-[var(--sd-faint)]">{t("dashboard.rail.empty_zips")}</p>
        ) : (
          <div className="mt-2.5 space-y-2">
            {zips.map((item) => (
              <div key={item.zip} className="grid grid-cols-[42px_1fr_24px] items-center gap-2">
                <b className="text-[10px] font-black text-[var(--sd-text)]">{item.zip}</b>
                <span className="h-1.5 overflow-hidden rounded-full bg-[var(--sd-border)]">
                  <span
                    className="block h-full rounded-full bg-[var(--sd-accent)]"
                    style={{ width: `${Math.max(12, (item.count / zipMax) * 100)}%` }}
                  />
                </span>
                <span className="text-right text-[10px] font-bold text-[var(--sd-muted)]">{item.count}</span>
              </div>
            ))}
          </div>
        )}
      </section>
    </aside>
  );
}

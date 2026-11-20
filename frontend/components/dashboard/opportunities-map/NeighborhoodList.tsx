"use client";

import { MapPin, Sparkles } from "lucide-react";

import { useI18n } from "@/lib/i18n";

import { formatDistance } from "./neighborhoods";

export interface ZoneListItem {
  name: string;
  count: number;
  /** Oportunidades frescas (<24 h). */
  fresh?: number;
}

export interface NeighborhoodRow {
  item: ZoneListItem;
  distance: number | null;
}

export function NeighborhoodList({
  rows,
  total,
  activeName,
  onSelect,
  onView,
  hasUser,
  sort,
  onSortChange,
  freshOnly,
  onFreshOnlyChange,
  freshCount,
  city,
  unmapped = 0,
}: {
  rows: NeighborhoodRow[];
  total: number;
  activeName: string | null;
  onSelect: (name: string) => void;
  onView: (name: string) => void;
  hasUser: boolean;
  sort: "leads" | "nearest";
  onSortChange: (value: "leads" | "nearest") => void;
  freshOnly: boolean;
  onFreshOnlyChange: (value: boolean) => void;
  freshCount: number;
  city: string;
  unmapped?: number;
}) {
  const { t } = useI18n();

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="border-b border-[var(--sd-border)] px-4 py-3">
        <div className="flex items-center justify-between gap-2">
          <p className="text-[12.5px] font-bold text-[var(--sd-text)]">
            {t("dashboard.oppmap.count")
              .replace("{n}", total.toLocaleString("en-US"))
              .replace("{m}", String(rows.length))}
          </p>
          {hasUser ? (
            <div className="flex shrink-0 items-center gap-0.5 rounded-md bg-[var(--sd-surface-2)] p-0.5">
              {(["nearest", "leads"] as const).map((value) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => onSortChange(value)}
                  className={`rounded px-1.5 py-0.5 text-[9.5px] font-bold ${
                    sort === value
                      ? "bg-[var(--sd-surface-3)] text-[var(--sd-text)]"
                      : "text-[var(--sd-muted)]"
                  }`}
                >
                  {value === "nearest"
                    ? t("dashboard.oppmap.sort.nearest")
                    : t("dashboard.oppmap.sort.leads")}
                </button>
              ))}
            </div>
          ) : null}
        </div>
        {freshCount > 0 ? (
          <div className="mt-2 flex items-center gap-1.5">
            <button
              type="button"
              onClick={() => onFreshOnlyChange(!freshOnly)}
              aria-pressed={freshOnly}
              className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-bold transition ${
                freshOnly
                  ? "border-amber-400 bg-amber-400/15 text-amber-300"
                  : "border-[var(--sd-border)] text-[var(--sd-muted)] hover:text-[var(--sd-text)]"
              }`}
            >
              <Sparkles className="h-2.5 w-2.5" />
              {t("dashboard.oppmap.fresh_only")}
              <span
                className={`rounded-full px-1 text-[9.5px] ${
                  freshOnly
                    ? "bg-amber-400/25 text-amber-200"
                    : "bg-[var(--sd-surface-3)] text-[var(--sd-text)]"
                }`}
              >
                {freshCount.toLocaleString("en-US")}
              </span>
            </button>
          </div>
        ) : null}
      </div>

      {rows.length === 0 ? (
        <div className="flex flex-1 items-center justify-center px-6 text-center">
          <div>
            <MapPin className="mx-auto h-6 w-6 text-[var(--sd-faint)]" />
            <p className="mt-2 text-[12px] font-bold text-[var(--sd-text)]">
              {unmapped > 0
                ? t("dashboard.oppmap.unmapped_empty").replace(
                    "{n}",
                    unmapped.toLocaleString("en-US")
                  )
                : t("dashboard.oppmap.empty").replace("{city}", city)}
            </p>
          </div>
        </div>
      ) : (
        <div className="min-h-0 flex-1 overflow-y-auto">
          <ul className="divide-y divide-[var(--sd-border)]">
            {rows.map(({ item, distance }) => {
              const active = item.name === activeName;
              return (
                <li key={item.name}>
                  <div
                    role="button"
                    tabIndex={0}
                    onClick={() => onSelect(item.name)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        onSelect(item.name);
                      }
                    }}
                    className={`group flex cursor-pointer items-center gap-3 px-4 py-3 transition ${
                      active
                        ? "bg-[var(--sd-surface-2)] shadow-[inset_2px_0_0_var(--sd-accent)]"
                        : "hover:bg-[var(--sd-surface-2)]"
                    }`}
                  >
                    <div className="min-w-0 flex-1">
                      <div className="flex min-w-0 items-center gap-1.5">
                        <span className="truncate text-[15px] font-bold leading-tight text-[var(--sd-text)]">
                          {item.name}
                        </span>
                        {(item.fresh ?? 0) > 0 ? (
                          <span
                            data-fresh="1"
                            className="inline-flex shrink-0 items-center gap-0.5 rounded-full border border-amber-400/50 bg-amber-400/15 px-1.5 py-0.5 text-[9px] font-extrabold uppercase tracking-wide text-amber-300"
                            title={t("dashboard.oppmap.fresh_tip")}
                          >
                            <Sparkles className="h-2.5 w-2.5" />
                            {t("dashboard.oppmap.fresh_badge")}
                            <span className="opacity-80">
                              {(item.fresh ?? 0).toLocaleString("en-US")}
                            </span>
                          </span>
                        ) : null}
                      </div>
                      <div className="mt-0.5 flex items-center gap-1.5 text-[12px] text-[var(--sd-muted)]">
                        <span>
                          {item.count.toLocaleString("en-US")}{" "}
                          {item.count === 1
                            ? t("dashboard.oppmap.opportunity")
                            : t("dashboard.oppmap.opportunities")}
                        </span>
                        {distance !== null ? (
                          <>
                            <span className="text-[var(--sd-faint)]">·</span>
                            <span className="font-semibold text-[var(--sd-accent)]">
                              {formatDistance(distance)}
                            </span>
                          </>
                        ) : null}
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={(event) => {
                        event.stopPropagation();
                        onView(item.name);
                      }}
                      className="shrink-0 rounded-lg border border-[var(--sd-border-strong)] px-2.5 py-1.5 text-[11px] font-bold text-[var(--sd-text)] transition group-hover:border-[var(--sd-accent)] group-hover:text-[var(--sd-accent)]"
                    >
                      {t("dashboard.oppmap.view")}
                    </button>
                  </div>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}

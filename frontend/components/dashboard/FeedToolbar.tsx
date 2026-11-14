"use client";

import { Search, SlidersHorizontal, X } from "lucide-react";
import type { Ref } from "react";
import { useI18n } from "@/lib/i18n";
import { TRADE_CATEGORIES } from "@/lib/categories";

export interface FeedTab {
  key: string;
  label: string;
  count: number;
}

const SEVERITY_OPTIONS = ["critical", "high", "medium", "routine"] as const;

export function FeedToolbar({
  tabs,
  activeTab,
  onTabChange,
  cities,
  city,
  onCityChange,
  category,
  onCategoryChange,
  severity,
  onSeverityChange,
  onlyDeadline,
  onToggleDeadline,
  showPreventiveFilters,
  deadlineWindow,
  onDeadlineWindowChange,
  withFines,
  onToggleFines,
  search,
  onSearchChange,
  resultCount,
  resultLabel,
  onOpenAdvanced,
  onClear,
  advancedButtonRef,
}: {
  tabs: FeedTab[];
  activeTab: string;
  onTabChange: (key: string) => void;
  cities: string[];
  city: string;
  onCityChange: (value: string) => void;
  category: string;
  onCategoryChange: (value: string) => void;
  severity: string;
  onSeverityChange: (value: string) => void;
  onlyDeadline: boolean;
  onToggleDeadline: () => void;
  showPreventiveFilters?: boolean;
  deadlineWindow?: string;
  onDeadlineWindowChange?: (value: string) => void;
  withFines?: boolean;
  onToggleFines?: () => void;
  search: string;
  onSearchChange: (value: string) => void;
  resultCount: number;
  resultLabel: string;
  onOpenAdvanced?: () => void;
  onClear: () => void;
  advancedButtonRef?: Ref<HTMLButtonElement>;
}) {
  const { t } = useI18n();

  return (
    <section className="overflow-hidden rounded-2xl border border-[var(--sd-border)] bg-[var(--sd-surface)]">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--sd-border)] px-4 py-2.5">
        <div className="sd-scroll-x flex min-w-0 items-center gap-1 overflow-x-auto">
          {tabs.map((tab) => {
            const active = tab.key === activeTab;
            return (
              <button
                key={tab.key}
                type="button"
                onClick={() => onTabChange(tab.key)}
                aria-pressed={active}
                className={`inline-flex shrink-0 items-center gap-1.5 rounded-lg px-3 py-1.5 text-[11.5px] font-bold transition ${
                  active
                    ? "bg-[var(--sd-accent-soft)] text-[var(--sd-accent)]"
                    : "text-[var(--sd-muted)] hover:bg-[var(--sd-surface-2)] hover:text-[var(--sd-text)]"
                }`}
              >
                {tab.label}
                <span
                  className={`rounded-full px-1.5 py-0.5 text-[9px] font-black ${
                    active
                      ? "bg-[var(--sd-accent)] text-[var(--sd-accent-text)]"
                      : "bg-[var(--sd-surface-2)] text-[var(--sd-faint)]"
                  }`}
                >
                  {tab.count}
                </span>
              </button>
            );
          })}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <span className="text-[10px] font-semibold text-[var(--sd-muted)]">
            {resultCount} {resultLabel}
          </span>
          {onOpenAdvanced ? (
            <button
              ref={advancedButtonRef}
              type="button"
              onClick={onOpenAdvanced}
              className="sd-focus inline-flex items-center gap-1.5 rounded-lg border border-[var(--sd-border)] px-2.5 py-1.5 text-[10px] font-bold text-[var(--sd-muted)] transition hover:text-[var(--sd-text)]"
            >
              <SlidersHorizontal className="h-3 w-3" />
              {t("dashboard.filter.open")}
            </button>
          ) : null}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2 px-4 py-2.5">
        <div className="sd-scroll-x flex items-center gap-1.5 overflow-x-auto">
          <CityChip active={city === "all"} onClick={() => onCityChange("all")} label={t("dashboard.filter.all_cities")} />
          {cities.map((name) => (
            <CityChip key={name} active={city === name} onClick={() => onCityChange(name)} label={name} />
          ))}
        </div>

        <select
          value={category}
          onChange={(event) => onCategoryChange(event.target.value)}
          aria-label={t("dashboard.filter.specialty")}
          className="h-8 rounded-lg border border-[var(--sd-border)] bg-[var(--sd-surface)] px-2 text-[11px] font-semibold text-[var(--sd-muted)]"
        >
          <option value="all">{t("dashboard.filter.all_specialties")}</option>
          {TRADE_CATEGORIES.map((item) => (
            <option key={item.key} value={item.key}>
              {t(item.labelKey)}
            </option>
          ))}
        </select>

        <select
          value={severity}
          onChange={(event) => onSeverityChange(event.target.value)}
          aria-label={t("dashboard.filter.severity")}
          className="h-8 rounded-lg border border-[var(--sd-border)] bg-[var(--sd-surface)] px-2 text-[11px] font-semibold text-[var(--sd-muted)]"
        >
          <option value="all">{t("dashboard.filter.all_severities")}</option>
          {SEVERITY_OPTIONS.map((value) => (
            <option key={value} value={value}>
              {t(`dashboard.severity.${value}`)}
            </option>
          ))}
        </select>

        {showPreventiveFilters ? (
          <>
            <select
              value={deadlineWindow ?? "all"}
              onChange={(event) => onDeadlineWindowChange?.(event.target.value)}
              aria-label={t("dashboard.filter.deadline_window")}
              className="h-8 rounded-lg border border-[var(--sd-border)] bg-[var(--sd-surface)] px-2 text-[11px] font-semibold text-[var(--sd-muted)]"
            >
              <option value="all">{t("dashboard.filter.deadline_all")}</option>
              <option value="3">{t("dashboard.filter.deadline_3d")}</option>
              <option value="7">{t("dashboard.filter.deadline_7d")}</option>
            </select>

            <button
              type="button"
              onClick={onToggleFines}
              aria-pressed={withFines}
              className={`inline-flex h-8 shrink-0 items-center gap-2 rounded-lg border px-2.5 text-[11px] font-semibold transition ${
                withFines
                  ? "border-[var(--sd-urgent)] bg-[var(--sd-urgent-soft)] text-[var(--sd-urgent)]"
                  : "border-[var(--sd-border)] text-[var(--sd-muted)] hover:text-[var(--sd-text)]"
              }`}
            >
              <span
                className={`relative h-3.5 w-6 rounded-full transition ${
                  withFines ? "bg-[var(--sd-urgent)]" : "bg-[var(--sd-border-strong)]"
                }`}
              >
                <span
                  className={`absolute top-0.5 h-2.5 w-2.5 rounded-full bg-white transition ${
                    withFines ? "left-[13px]" : "left-0.5"
                  }`}
                />
              </span>
              {t("dashboard.filter.with_fines")}
            </button>
          </>
        ) : (
          <button
            type="button"
            onClick={onToggleDeadline}
            aria-pressed={onlyDeadline}
            className={`inline-flex h-8 shrink-0 items-center gap-2 rounded-lg border px-2.5 text-[11px] font-semibold transition ${
              onlyDeadline
                ? "border-[var(--sd-accent)] bg-[var(--sd-accent-soft)] text-[var(--sd-accent)]"
                : "border-[var(--sd-border)] text-[var(--sd-muted)] hover:text-[var(--sd-text)]"
            }`}
          >
            <span
              className={`relative h-3.5 w-6 rounded-full transition ${
                onlyDeadline ? "bg-[var(--sd-accent)]" : "bg-[var(--sd-border-strong)]"
              }`}
            >
              <span
                className={`absolute top-0.5 h-2.5 w-2.5 rounded-full bg-white transition ${
                  onlyDeadline ? "left-[13px]" : "left-0.5"
                }`}
              />
            </span>
            {t("dashboard.filter.only_deadline")}
          </button>
        )}

        <div className="relative min-w-[160px] flex-1 sm:max-w-[260px]">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[var(--sd-faint)]" />
          <input
            value={search}
            onChange={(event) => onSearchChange(event.target.value)}
            placeholder={t("dashboard.feed.search_inline")}
            aria-label={t("dashboard.feed.search_inline")}
            className="h-8 w-full rounded-lg border border-[var(--sd-border)] bg-[var(--sd-surface)] pl-8 pr-7 text-[11px] font-medium text-[var(--sd-text)] placeholder:text-[var(--sd-faint)] focus:border-[var(--sd-accent)] focus:outline-none"
          />
          {search ? (
            <button
              type="button"
              onClick={() => onSearchChange("")}
              aria-label={t("dashboard.filter.clear")}
              className="absolute right-1.5 top-1/2 grid h-5 w-5 -translate-y-1/2 place-items-center rounded text-[var(--sd-faint)] hover:text-[var(--sd-text)]"
            >
              <X className="h-3 w-3" />
            </button>
          ) : null}
        </div>

        <button
          type="button"
          onClick={onClear}
          className="ml-auto shrink-0 text-[10px] font-bold uppercase tracking-[0.06em] text-[var(--sd-muted)] underline-offset-2 hover:text-[var(--sd-text)] hover:underline"
        >
          {t("dashboard.filter.clear")}
        </button>
      </div>
    </section>
  );
}

function CityChip({
  active,
  onClick,
  label,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`shrink-0 rounded-full border px-2.5 py-1 text-[10.5px] font-bold transition ${
        active
          ? "border-[var(--sd-accent)] bg-[var(--sd-accent-soft)] text-[var(--sd-accent)]"
          : "border-[var(--sd-border)] text-[var(--sd-muted)] hover:text-[var(--sd-text)]"
      }`}
    >
      {label}
    </button>
  );
}

"use client";

import { useEffect, useMemo, useState } from "react";
import { MapPin, ShieldCheck, Clock, ArrowRight } from "lucide-react";
import { useI18n } from "@/lib/i18n";
import { TRADE_CATEGORIES } from "@/lib/categories";
import {
  fetchOpportunities,
  type Opportunity,
  type OpportunityListResponse,
} from "@/lib/api-client";

const SEVERITY_KEYS: Record<string, string> = {
  critical: "dashboard.severity.critical",
  high: "dashboard.severity.high",
  medium: "dashboard.severity.medium",
  routine: "dashboard.severity.routine",
  emergency: "dashboard.severity.emergency",
  immediate: "dashboard.severity.immediate",
  class_1: "dashboard.severity.class_1",
  class_2: "dashboard.severity.class_2",
  class_3: "dashboard.severity.class_3",
  class_a: "dashboard.severity.class_a",
  class_b: "dashboard.severity.class_b",
  class_c: "dashboard.severity.class_c",
};

function severityKey(value?: string | null): string {
  if (!value) return "dashboard.severity.medium";
  return SEVERITY_KEYS[value.toLowerCase()] || "dashboard.severity.medium";
}

function categoryKey(value?: string | null): string | null {
  if (!value) return null;
  return TRADE_CATEGORIES.find((c) => c.key === value)?.labelKey || null;
}

function daysUntil(value?: string | null): number | null {
  if (!value) return null;
  const target = Date.parse(value.replace(" ", "T") + (value.includes("T") ? "" : "Z"));
  if (!Number.isFinite(target)) return null;
  return Math.max(0, Math.ceil((target - Date.now()) / 86400000));
}

export function PreventiveFeed({
  onOpenReveal,
  onOpenReactive,
}: {
  onOpenReveal: (opportunity: Opportunity) => void;
  onOpenReactive: () => void;
}) {
  const { t, lang } = useI18n();
  const money = (value: number) =>
    new Intl.NumberFormat(lang === "pt" ? "pt-BR" : lang === "es" ? "es-MX" : "en-US", {
      style: "currency",
      currency: "USD",
      maximumFractionDigits: 0,
    }).format(value);
  const [data, setData] = useState<OpportunityListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [city, setCity] = useState("all");
  const [category, setCategory] = useState("all");

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError(false);
    fetchOpportunities({ kind: "preventive", limit: 100 })
      .then((res) => {
        if (alive) setData(res);
      })
      .catch(() => {
        if (alive) setError(true);
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, []);

  const rows = useMemo(() => {
    let list = data?.opportunities || [];
    if (city !== "all") list = list.filter((o) => o.city === city);
    if (category !== "all") list = list.filter((o) => o.category === category);
    return list;
  }, [data, city, category]);

  const cities = useMemo(
    () => Array.from(new Set((data?.opportunities || []).map((o) => o.city).filter((v): v is string => Boolean(v)))).sort(),
    [data]
  );
  const categories = useMemo(
    () => Array.from(new Set((data?.opportunities || []).map((o) => o.category).filter((v): v is string => Boolean(v)))).sort(),
    [data]
  );

  return (
    <section className="flex flex-col overflow-hidden rounded-2xl border border-[var(--sd-border)] bg-[var(--sd-surface)]">
      <div className={`border-b px-5 py-4 ${"border-[var(--sd-border)]"}`}>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="flex items-center gap-2 text-base font-bold">
              <ShieldCheck className="h-4 w-4 text-[var(--sd-accent)]" />
              {t("dashboard.preinspection.title")}
              <span className="rounded-full bg-[var(--sd-accent-soft)] px-2 py-0.5 text-[11px] font-semibold text-[var(--sd-accent)]">
                {data?.counts.preventive ?? 0}
              </span>
            </h2>
            <p className="mt-1 text-xs text-[var(--sd-muted)]">
              {t("dashboard.preinspection.subtitle")}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              className="rounded-lg bg-[var(--sd-accent)] px-3 py-2 text-[11px] font-bold text-[var(--sd-accent-text)]"
            >
              {t("dashboard.feed.tab_preventive")}
            </button>
            <button
              type="button"
              onClick={onOpenReactive}
              className="rounded-lg border border-[var(--sd-border)] px-3 py-2 text-[11px] font-bold text-[var(--sd-muted)]"
            >
              {t("dashboard.feed.tab_reactive")}
            </button>
          </div>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-2">
          <select
            value={city}
            onChange={(e) => setCity(e.target.value)}
            className="rounded-lg border border-[var(--sd-border)] bg-[var(--sd-surface)] px-2.5 py-1.5 text-[11px] font-semibold text-[var(--sd-muted)]"
            aria-label={t("dashboard.feed.all_cities")}
          >
            <option value="all">{t("dashboard.feed.all_cities")}</option>
            {cities.map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>
          <select
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            className="rounded-lg border border-[var(--sd-border)] bg-[var(--sd-surface)] px-2.5 py-1.5 text-[11px] font-semibold text-[var(--sd-muted)]"
            aria-label={t("dashboard.feed.tab_preventive")}
          >
            <option value="all">{t("dashboard.preinspection.badge")}</option>
            {categories.map((c) => (
              <option key={c} value={c}>{categoryKey(c) ? t(categoryKey(c) as string) : c}</option>
            ))}
          </select>
          <span className="ml-auto text-[11px] text-[var(--sd-muted)]">
            {rows.length} {t("dashboard.feed.tab_preventive").toLowerCase()}
          </span>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto max-h-[680px]">
        {loading ? (
          <div className="space-y-3 p-4" aria-busy="true">
            {[0, 1, 2].map((i) => (
              <div key={i} className="h-28 animate-pulse rounded-xl bg-[var(--sd-surface-2)]" />
            ))}
          </div>
        ) : error ? (
          <div className="p-10 text-center text-sm text-[var(--sd-muted)]">
            {t("dashboard.opportunity.not_found")}
          </div>
        ) : rows.length === 0 ? (
          <div className="p-12 text-center">
            <ShieldCheck className="mx-auto h-8 w-8 text-[var(--sd-faint)]" />
            <p className="mt-3 text-sm font-semibold text-[var(--sd-text)]">
              {t("dashboard.preinspection.title")}
            </p>
            <p className="mt-1 text-xs text-[var(--sd-muted)]">
              {t("dashboard.preinspection.subtitle")}
            </p>
          </div>
        ) : (
          <div className="space-y-3 p-3">
            {rows.map((opp) => {
              const days = daysUntil(opp.compliance_deadline);
              return (
                <article
                  key={opp.id}
                  className="rounded-xl border border-[var(--sd-border)] bg-[var(--sd-surface-2)] p-4 transition hover:border-[var(--sd-accent)]/40"
                >
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="rounded-full bg-[var(--sd-accent-soft)] px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-[var(--sd-accent)]">
                          {t("dashboard.preinspection.badge")}
                        </span>
                        <span className="rounded-full border border-[var(--sd-border)] px-2 py-0.5 text-[10px] font-semibold text-[var(--sd-muted)]">
                          {t(severityKey(opp.severity))}
                        </span>
                      </div>
                      <h3 className="mt-2 truncate text-sm font-bold text-[var(--sd-text)]">
                        {categoryKey(opp.category) ? t(categoryKey(opp.category) as string) : opp.category || opp.address}
                      </h3>
                      <p className="mt-1 flex items-center gap-1 text-xs text-[var(--sd-muted)]">
                        <MapPin className="h-3 w-3" />
                        {opp.address}{opp.city ? ` · ${opp.city}` : ""}{opp.zip_code ? ` ${opp.zip_code}` : ""}
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={() => onOpenReveal(opp)}
                      className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--sd-accent)] px-3 py-2 text-[11px] font-bold text-[var(--sd-accent-text)]"
                    >
                      {t("dashboard.reveal.title")}
                      <ArrowRight className="h-3.5 w-3.5" />
                    </button>
                  </div>

                  <div className="mt-3 flex flex-wrap items-center gap-3 border-t border-[var(--sd-border)] pt-3 text-[10px] font-semibold text-[var(--sd-muted)]">
                    <span className="inline-flex items-center gap-1">
                      <Clock className="h-3 w-3" />
                      {opp.status === "reserved" && opp.stage_expires_at
                        ? t("dashboard.status.selected")
                        : days != null
                          ? t("dashboard.deadline.in_days").replace("{days}", String(days))
                          : t("dashboard.deadline.none")}
                    </span>
                    <span>{t("dashboard.preinspection.possible")}</span>
                    {opp.job_value != null ? (
                      <span>{money(opp.job_value)}</span>
                    ) : null}
                  </div>
                </article>
              );
            })}
          </div>
        )}
      </div>
    </section>
  );
}

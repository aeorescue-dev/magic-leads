"use client";

import { useEffect, useMemo, useState } from "react";
import { ShieldCheck } from "lucide-react";
import { useI18n } from "@/lib/i18n";
import { TRADE_CATEGORIES } from "@/lib/categories";
import {
  fetchOpportunities,
  type Opportunity,
  type OpportunityListResponse,
} from "@/lib/api-client";
import { PreventiveCard } from "@/components/dashboard/PreventiveCard";
import { OpportunityDrawer } from "@/components/dashboard/OpportunityDrawer";

function categoryKey(value?: string | null): string | null {
  if (!value) return null;
  return TRADE_CATEGORIES.find((c) => c.key === value)?.labelKey || null;
}

export function PreventiveFeed({
  onOpenReveal,
  onOpenReactive,
}: {
  onOpenReveal: (opportunity: Opportunity) => void;
  onOpenReactive: () => void;
}) {
  const { t } = useI18n();
  const [data, setData] = useState<OpportunityListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [city, setCity] = useState("all");
  const [category, setCategory] = useState("all");
  const [selected, setSelected] = useState<Opportunity | null>(null);

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
          <div className="grid grid-cols-1 gap-3 p-3 md:grid-cols-2">
            {rows.map((opp) => (
              <PreventiveCard
                key={opp.id}
                opportunity={opp}
                onOpen={() => setSelected(opp)}
              />
            ))}
          </div>
        )}
        {selected ? (
          <OpportunityDrawer
            opportunity={selected}
            onClose={() => setSelected(null)}
            onReveal={() => {
              const opp = selected;
              setSelected(null);
              onOpenReveal(opp);
            }}
          />
        ) : null}
      </div>
    </section>
  );
}

"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ShieldCheck } from "lucide-react";
import { useI18n } from "@/lib/i18n";
import {
  fetchOpportunities,
  type Opportunity,
  type OpportunityListResponse,
} from "@/lib/api-client";
import { severityBucket, deadlineDaysLeft } from "@/lib/opportunity-format";
import { OPPORTUNITIES_REFRESH_EVENT } from "@/lib/opportunity-events";
import { PreventiveCard } from "@/components/dashboard/PreventiveCard";
import { OpportunityDrawer } from "@/components/dashboard/OpportunityDrawer";
import { FeedRail } from "@/components/dashboard/FeedRail";

const PAGE_SIZE = 50;
const MAX_CARDS = 100;

export interface FeedFilters {
  city: string;
  category: string;
  severity: string;
  onlyDeadline: boolean;
  /** Máximo de dias até ao prazo; `null` = qualquer prazo. */
  deadlineWindow: number | null;
  /** Só imóveis com multa real em aberto. */
  withFines: boolean;
  search: string;
  now: number;
}

export function PreventiveFeed({
  onOpenReveal,
  filters,
  onCountChange,
}: {
  onOpenReveal: (opportunity: Opportunity) => void;
  filters: FeedFilters;
  onCountChange?: (count: number) => void;
}) {
  const { t } = useI18n();
  const [data, setData] = useState<OpportunityListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState(false);
  const [selected, setSelected] = useState<Opportunity | null>(null);
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const requestRef = useRef(0);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(filters.search.trim()), 300);
    return () => clearTimeout(timer);
  }, [filters.search]);

  const buildParams = useCallback(
    (offset: number) => ({
      kind: "preventive",
      limit: PAGE_SIZE,
      offset,
      days: 7,
      city: filters.city !== "all" ? filters.city : undefined,
      category: filters.category !== "all" ? filters.category : undefined,
      severity: filters.severity !== "all" ? filters.severity : undefined,
      deadline_within:
        filters.deadlineWindow ?? (filters.onlyDeadline ? 7 : undefined),
      with_fines: filters.withFines || undefined,
      search: debouncedSearch || undefined,
    }),
    [
      filters.city,
      filters.category,
      filters.severity,
      filters.deadlineWindow,
      filters.onlyDeadline,
      filters.withFines,
      debouncedSearch,
    ]
  );

  const load = useCallback(
    (offset: number, append: boolean) => {
      const id = ++requestRef.current;
      if (append) {
        setLoadingMore(true);
      } else {
        setLoading(true);
        setError(false);
      }
      fetchOpportunities(buildParams(offset))
        .then((res) => {
          if (!mountedRef.current || id !== requestRef.current) return;
          setData((prev) =>
            append && prev
              ? { ...res, opportunities: [...prev.opportunities, ...res.opportunities] }
              : res
          );
        })
        .catch(() => {
          if (!mountedRef.current || id !== requestRef.current) return;
          if (!append) setError(true);
        })
        .finally(() => {
          if (!mountedRef.current || id !== requestRef.current) return;
          if (append) setLoadingMore(false);
          else setLoading(false);
        });
    },
    [buildParams]
  );

  useEffect(() => {
    load(0, false);
    return () => {
      requestRef.current += 1;
    };
  }, [load]);

  useEffect(() => {
    const handler = () => load(0, false);
    window.addEventListener(OPPORTUNITIES_REFRESH_EVENT, handler);
    return () => window.removeEventListener(OPPORTUNITIES_REFRESH_EVENT, handler);
  }, [load]);

  const rows = data?.opportunities ?? [];
  const total = data?.total ?? rows.length;
  const hasMore = Boolean(data?.has_more) && rows.length < MAX_CARDS;

  useEffect(() => {
    onCountChange?.(total);
  }, [total, onCountChange]);

  const rail = useMemo(() => {
    const severity = { critical: 0, high: 0, medium: 0, routine: 0 };
    const zipCounts = new Map<string, number>();
    const deadlines: Array<{
      id: number;
      address: string;
      city?: string | null;
      severity?: string | null;
      days_left: number;
    }> = [];
    for (const opp of rows) {
      severity[severityBucket(opp.severity)] += 1;
      const zip = String(opp.zip_code || "").trim().slice(0, 5);
      if (zip.length === 5) zipCounts.set(zip, (zipCounts.get(zip) ?? 0) + 1);
      const days = deadlineDaysLeft(opp.compliance_deadline, filters.now);
      if (days != null) {
        deadlines.push({
          id: opp.id,
          address: opp.address,
          city: opp.city,
          severity: opp.severity,
          days_left: days,
        });
      }
    }
    return {
      severity,
      zips: Array.from(zipCounts.entries())
        .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
        .slice(0, 5)
        .map(([zip, count]) => ({ zip, count })),
      deadlines: deadlines.sort((a, b) => a.days_left - b.days_left).slice(0, 5),
    };
  }, [rows, filters.now]);
  const railSeverity = rail.severity;
  const railDeadlines = rail.deadlines;
  const railZips = rail.zips;

  return (
    <div className="grid grid-cols-1 items-start gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
    <section className="flex w-full min-w-0 flex-col overflow-hidden rounded-2xl border border-[var(--sd-border)] bg-[var(--sd-surface)]">
      <div className="border-b border-[var(--sd-border)] px-5 py-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
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
          <span className="text-[11px] font-semibold text-[var(--sd-muted)]">
            {t("dashboard.preinspection.showing_of", { shown: rows.length, total })}
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
              {t("dashboard.preinspection.no_results")}
            </p>
            <p className="mt-1 text-xs text-[var(--sd-muted)]">
              {t("dashboard.preinspection.subtitle")}
            </p>
          </div>
        ) : (
          <>
            <div className="grid grid-cols-1 gap-3 p-3 md:grid-cols-2">
              {rows.map((opp) => (
                <PreventiveCard
                  key={opp.id}
                  opportunity={opp}
                  onOpen={() => setSelected(opp)}
                />
              ))}
            </div>
            {hasMore ? (
              <div className="border-t border-[var(--sd-border)] p-4 text-center">
                <button
                  type="button"
                  onClick={() => load(rows.length, true)}
                  disabled={loadingMore}
                  className="inline-flex items-center justify-center rounded-lg border border-[var(--sd-border)] px-4 py-2 text-xs font-bold text-[var(--sd-muted)] transition hover:text-[var(--sd-text)] disabled:opacity-50"
                >
                  {loadingMore
                    ? t("dashboard.preinspection.loading_more")
                    : t("dashboard.preinspection.load_more")}
                </button>
              </div>
            ) : null}
          </>
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
    <FeedRail
      deadlines={railDeadlines}
      severity={railSeverity}
      zips={railZips}
      onOpenDeadline={(id) => {
        const opp = rows.find((item) => item.id === Number(id));
        if (opp) setSelected(opp);
      }}
      onSeeAll={() => {
        const first = railDeadlines[0];
        const opp = first ? rows.find((item) => item.id === Number(first.id)) : null;
        if (opp) setSelected(opp);
      }}
      onOpenMap={() => {
        const zip = railZips[0]?.zip;
        if (zip && typeof window !== "undefined") {
          window.open(`https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(zip)}`, "_blank", "noopener");
        }
      }}
    />
    </div>
  );
}

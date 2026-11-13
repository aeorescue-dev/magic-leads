"use client";

import { useEffect, useMemo, useState } from "react";
import { ShieldCheck } from "lucide-react";
import { useI18n } from "@/lib/i18n";
import {
  fetchOpportunities,
  type Opportunity,
  type OpportunityListResponse,
} from "@/lib/api-client";
import { severityBucket } from "@/lib/opportunity-format";
import { PreventiveCard } from "@/components/dashboard/PreventiveCard";
import { OpportunityDrawer } from "@/components/dashboard/OpportunityDrawer";
import { FeedRail } from "@/components/dashboard/FeedRail";

export interface FeedFilters {
  city: string;
  category: string;
  severity: string;
  onlyDeadline: boolean;
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
  const [error, setError] = useState(false);
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
    const term = filters.search.trim().toLowerCase();
    return (data?.opportunities || []).filter((opp) => {
      if (filters.city !== "all" && opp.city !== filters.city) return false;
      if (filters.category !== "all" && opp.category !== filters.category) return false;
      if (filters.severity !== "all" && severityBucket(opp.severity) !== filters.severity) {
        return false;
      }
      if (filters.onlyDeadline) {
        if (!opp.compliance_deadline) return false;
        const target = Date.parse(
          opp.compliance_deadline.includes("T")
            ? opp.compliance_deadline
            : `${opp.compliance_deadline}T00:00:00`
        );
        if (!Number.isFinite(target) || target - filters.now > 7 * 86400000) return false;
      }
      if (term) {
        const haystack = [
          opp.address,
          opp.city,
          opp.zip_code,
          opp.category,
          opp.description,
          opp.owner_name,
        ]
          .filter(Boolean)
          .join(" ")
          .toLowerCase();
        if (!haystack.includes(term)) return false;
      }
      return true;
    });
  }, [data, filters]);

  useEffect(() => {
    onCountChange?.(rows.length);
  }, [rows.length, onCountChange]);

  const insights = data?.insights;
  const railSeverity = insights?.by_severity ?? { critical: 0, high: 0, medium: 0, routine: 0 };
  const railDeadlines = (insights?.deadlines ?? []).map((item) => ({
    id: item.id,
    address: item.address,
    city: item.city,
    severity: item.severity,
    days_left: item.days_left,
  }));
  const railZips = insights?.by_zip ?? [];

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
              {(data?.opportunities.length ?? 0) > 0
                ? t("dashboard.preinspection.no_results")
                : t("dashboard.preinspection.title")}
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
    <FeedRail
      deadlines={railDeadlines}
      severity={railSeverity}
      zips={railZips}
      onOpenDeadline={(id) => {
        const opp = data?.opportunities.find((item) => item.id === Number(id));
        if (opp) setSelected(opp);
      }}
      onSeeAll={() => {
        const first = railDeadlines[0];
        const opp = first
          ? data?.opportunities.find((item) => item.id === Number(first.id))
          : null;
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

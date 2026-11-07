"use client";

import Link from "next/link";
import useSWR from "swr";
import {
  ArrowUpRight,
  Database,
  HeartPulse,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { fetchAdminDataPlane } from "@/lib/admin-api";
import { MetricCard, StatusPill, cn } from "@/components/admin/ui";
import { formatScore } from "@/lib/score";

function fmtAgo(hours: number | null | undefined) {
  if (hours === null || hours === undefined) return "sem registo";
  if (hours < 1) return `${Math.round(hours * 60)} min`;
  if (hours < 48) return `${hours.toFixed(1)} h`;
  return `${Math.round(hours / 24)} d`;
}

export default function DataPlaneStrip() {
  const { data, error } = useSWR("admin-data-plane-overview", fetchAdminDataPlane, {
    refreshInterval: 60_000,
    revalidateOnFocus: true,
  });

  if (error) {
    return (
      <div className="rounded-2xl border border-rose-400/15 bg-rose-500/[0.04] p-3 text-[11px] text-rose-200">
        Data Plane indisponível: {error instanceof Error ? error.message : "erro"}
      </div>
    );
  }

  const ingestions = data?.ingestion.runs.length ?? 0;
  const failures = (data?.ingestion.by_status ?? [])
    .filter((row) => row.status !== "success")
    .reduce((sum, row) => sum + row.n, 0);
  const placeholders = data?.quarantine.active_count ?? 0;
  const lastFreshness = data?.freshness.last_run;
  const score = data?.score;

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-emerald-300/80">
            Data Plane
          </p>
          <p className="text-[11px] text-slate-500">
            Ingestão, quarentena, frescura e scoring em tempo quase real.
          </p>
        </div>
        <Link
          href="/admin/data-plane"
          className="inline-flex items-center gap-1.5 rounded-xl border border-white/10 bg-white/[0.03] px-3 py-1.5 text-[10px] font-bold text-slate-300 transition hover:border-emerald-400/30 hover:text-emerald-200"
        >
          Abrir Data Plane <ArrowUpRight className="h-3 w-3" />
        </Link>
      </div>
      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard
          label="Ingestões"
          value={data ? ingestions : "—"}
          sub={failures ? `${failures} falha(s)` : "sem falhas registadas"}
          icon={<Database className="h-4 w-4" />}
          tone={failures ? "amber" : "emerald"}
        />
        <MetricCard
          label="Quarentena"
          value={data ? placeholders : "—"}
          sub={`${(data?.quarantine.other_quarantined ?? 0).toLocaleString("pt-PT")} outras entidades`}
          icon={<ShieldCheck className="h-4 w-4" />}
          tone="violet"
        />
        <MetricCard
          label="Frescura HPD/DOB"
          value={lastFreshness ? fmtAgo(data?.freshness.last_age_hours) : "—"}
          sub={
            lastFreshness
              ? `${lastFreshness.hpd_checked.toLocaleString("pt-PT")} HPD · ${lastFreshness.dob_checked.toLocaleString("pt-PT")} DOB`
              : "sem runs"
          }
          icon={<HeartPulse className="h-4 w-4" />}
          tone={lastFreshness?.status === "ok" ? "emerald" : "amber"}
        />
        <MetricCard
          label="Score médio"
          value={score ? formatScore(score.avg) : "—"}
          sub={
            score
              ? `${score.total.toLocaleString("pt-PT")} prospects · ${score.min}–${score.max}`
              : "a carregar…"
          }
          icon={<Sparkles className="h-4 w-4" />}
          tone="sky"
        />
      </div>
      <div className="flex flex-wrap items-center gap-2 text-[10px] text-slate-600">
        <StatusPill state={failures ? "warn" : "ok"}>
          {failures ? "ingestão com falhas" : "ingestão limpa"}
        </StatusPill>
        <StatusPill state={placeholders ? "warn" : "ok"}>
          {placeholders ? `${placeholders} placeholders` : "quarentena limpa"}
        </StatusPill>
        <span className={cn("ml-auto", lastFreshness?.status === "ok" ? "text-emerald-300" : "text-amber-300")}>
          {lastFreshness?.status === "ok" ? "frescura ok" : "frescura a rever"}
        </span>
      </div>
    </div>
  );
}

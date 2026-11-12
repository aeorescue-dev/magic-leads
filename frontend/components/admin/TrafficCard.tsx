"use client";

import Link from "next/link";
import { ArrowUpRight, BarChart3, Loader2 } from "lucide-react";
import useSWR from "swr";

import { fetchAdminAnalytics } from "@/lib/admin-api";
import type { AdminAnalytics } from "@/lib/admin-api";

function todayEt(): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/New_York",
  }).format(new Date());
}

function fmt(value: number | undefined): string {
  return Number(value || 0).toLocaleString("pt-PT");
}

function MiniBars({ values }: { values: number[] }) {
  const max = Math.max(1, ...values);
  return (
    <div className="flex h-8 items-end gap-[3px]" aria-hidden="true">
      {values.slice(-14).map((value, index) => (
        <span
          key={index}
          className="w-1.5 rounded-t bg-emerald-400/70"
          style={{ height: `${Math.max(8, (value / max) * 100)}%` }}
        />
      ))}
    </div>
  );
}

function Column({
  label,
  data,
  hint,
}: {
  label: string;
  data?: AdminAnalytics;
  hint?: string;
}) {
  const cards = data?.cards;
  return (
    <div className="min-w-0 rounded-xl border border-white/[0.06] bg-white/[0.02] p-3">
      <p className="text-[9px] font-bold uppercase tracking-[0.14em] text-slate-500">
        {label}
      </p>
      <p className="mt-1 text-2xl font-black tabular-nums text-slate-100">
        {fmt(cards?.visits.value)}
      </p>
      <p className="text-[10px] font-semibold text-slate-500">
        {fmt(cards?.visitors.value)} únicos · {fmt(cards?.cta_clicks.value)} CTA ·{" "}
        {fmt(cards?.form_submits.value)} forms
      </p>
      {hint ? <p className="mt-1 text-[9px] text-slate-600">{hint}</p> : null}
    </div>
  );
}

export function TrafficCard() {
  const today = todayEt();
  const { data, error, isLoading } = useSWR(
    ["admin-traffic-card", today],
    async () => {
      const [todayData, week, month] = await Promise.all([
        fetchAdminAnalytics("custom", today, today),
        fetchAdminAnalytics("7d"),
        fetchAdminAnalytics("30d"),
      ]);
      return { todayData, week, month };
    },
    { refreshInterval: 60_000, revalidateOnFocus: true }
  );

  const weekSeries = data?.week.series.map((point) => point.visits) ?? [];

  return (
    <section className="rounded-2xl border border-white/10 bg-[#10131a] p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="flex items-center gap-2 text-sm font-bold text-slate-200">
            <BarChart3 className="h-4 w-4 text-emerald-400" />
            Tráfego
          </h2>
          <p className="mt-0.5 text-[10px] text-slate-500">
            {data?.week.internal_filter
              ? "Visitas reais de mercado · QA/infra e datacenters excluídos"
              : "Visitas de mercado · pré-visualização sobre o backend atual"}
          </p>
        </div>
        <Link
          href="/admin/analytics"
          className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 px-2.5 py-1.5 text-[10px] font-bold text-slate-300 transition hover:border-emerald-400/30 hover:text-emerald-200"
        >
          Ver Analytics
          <ArrowUpRight className="h-3.5 w-3.5" />
        </Link>
      </div>

      {error ? (
        <p className="mt-3 text-[11px] text-rose-300">
          Não foi possível carregar o tráfego.
        </p>
      ) : (
        <div className="mt-3 grid gap-2 sm:grid-cols-3">
          <Column label="Hoje (ET)" data={data?.todayData} hint={today} />
          <Column label="7 dias" data={data?.week} />
          <Column label="30 dias" data={data?.month} />
          <div className="hidden items-end justify-between gap-3 rounded-xl border border-white/[0.06] bg-white/[0.02] p-3 sm:col-span-3 sm:flex">
            <div>
              <p className="text-[9px] font-bold uppercase tracking-[0.14em] text-slate-500">
                Visitas por dia · 7 dias
              </p>
              <p className="mt-0.5 text-[10px] text-slate-600">
                {isLoading ? "a carregar…" : "atualiza a cada 60 s"}
              </p>
            </div>
            <MiniBars values={weekSeries} />
          </div>
        </div>
      )}
      {isLoading ? (
        <p className="mt-2 inline-flex items-center gap-1.5 text-[10px] text-slate-500">
          <Loader2 className="h-3 w-3 animate-spin" /> A carregar tráfego…
        </p>
      ) : null}
    </section>
  );
}

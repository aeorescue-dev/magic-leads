"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertCircle,
  Bell,
  ChevronRight,
  Clock,
  FolderKanban,
  LayoutDashboard,
  MapPin,
  Search,
  ShieldCheck,
  TrendingUp,
  Users,
} from "lucide-react";
import { useI18n } from "@/lib/i18n";
import { fetchPublicMetrics, fetchTradeGrid } from "@/lib/api-client";
import type { PublicMetrics } from "@/lib/api-client";

const SNAPSHOT = {
  active: 9611,
  owners: 8503,
  ownerPct: 88,
  urgent: 308,
  zips: 315,
  cities: 4,
  base: 127792,
  ownersBase: 100961,
  novas: 2293,
  citiesRows: [
    { key: "New York", active: 5915, ownerPct: 94 },
    { key: "Chicago", active: 2504, ownerPct: 78 },
    { key: "Dallas", active: 769, ownerPct: 83 },
    { key: "Boston", active: 423, ownerPct: 81 },
  ],
};

const COPY = {
  pt: {
    preview: "PREVIEW",
    overview: "Visão geral",
    navOpportunities: "Oportunidades",
    navAlerts: "Alertas",
    subtitle: "Proposta de KPI · snapshot 12/11/2026 03:05Z",
    search: "Buscar oportunidades",
    kpiActive: "Oportunidades ativas",
    kpiActiveDelta: "qualificadas nos últimos 7 dias",
    kpiOwners: "Proprietários identificados",
    kpiOwnersDelta: "das obras ativas",
    kpiUrgent: "Urgentes",
    kpiUrgentDelta: "precisam de ação",
    kpiNew: "Novas",
    kpiNewDelta: "atualizado agora",
    coverage: "Cobertura por praça",
    coverageSub: "Oportunidades ativas e proprietário identificado",
    sevenDays: "7 dias",
    active: "ativas",
    owner: "com dono",
    zips: "ZIPs cobertos",
    trades: "ofícios ativos",
    cities: "praças ativas",
    freshness: "Última atualização",
    updated: "Atualizado há {time}",
    changes: "O que esta proposta muda",
    change1Title: "Escopo ativo",
    change1Text: "{n} oportunidades em 7 dias no lugar de 127.792 históricos.",
    change2Title: "Dono no inventário",
    change2Text: "8.503 obras ativas com proprietário identificado (88%).",
    change3Title: "Frescura real",
    change3Text: "Atualização calculada em tempo real, em vez de “agora”.",
    note: "O KPI “Novas” (2.293) foi mantido exatamente como está, por decisão estratégica.",
    snapshot: "Dados do snapshot · 12/11/2026 03:05Z",
  },
  en: {
    preview: "PREVIEW",
    overview: "Overview",
    navOpportunities: "Opportunities",
    navAlerts: "Alerts",
    subtitle: "KPI proposal · snapshot 2026-11-12 03:05Z",
    search: "Search opportunities",
    kpiActive: "Active opportunities",
    kpiActiveDelta: "qualified in the last 7 days",
    kpiOwners: "Owners identified",
    kpiOwnersDelta: "of active jobs",
    kpiUrgent: "Urgent",
    kpiUrgentDelta: "need action",
    kpiNew: "New",
    kpiNewDelta: "updated now",
    coverage: "Coverage by market",
    coverageSub: "Active opportunities and identified owner",
    sevenDays: "7 days",
    active: "active",
    owner: "with owner",
    zips: "ZIPs covered",
    trades: "active trades",
    cities: "active markets",
    freshness: "Last update",
    updated: "Updated {time} ago",
    changes: "What this proposal changes",
    change1Title: "Active scope",
    change1Text: "{n} opportunities in 7 days instead of 127,792 historical.",
    change2Title: "Owner coverage",
    change2Text: "8,503 active jobs with an identified owner (88%).",
    change3Title: "Real freshness",
    change3Text: "Freshness computed in real time instead of “now”.",
    note: "The “New” KPI (2,293) is unchanged by strategic decision.",
    snapshot: "Snapshot data · 2026-11-12 03:05Z",
  },
  es: {
    preview: "PREVIEW",
    overview: "Visión general",
    navOpportunities: "Oportunidades",
    navAlerts: "Alertas",
    subtitle: "Propuesta de KPI · snapshot 12/11/2026 03:05Z",
    search: "Buscar oportunidades",
    kpiActive: "Oportunidades activas",
    kpiActiveDelta: "cualificadas en los últimos 7 días",
    kpiOwners: "Propietarios identificados",
    kpiOwnersDelta: "de las obras activas",
    kpiUrgent: "Urgentes",
    kpiUrgentDelta: "necesitan acción",
    kpiNew: "Nuevas",
    kpiNewDelta: "actualizado ahora",
    coverage: "Cobertura por plaza",
    coverageSub: "Oportunidades activas y propietario identificado",
    sevenDays: "7 días",
    active: "activas",
    owner: "con dueño",
    zips: "ZIPs cubiertos",
    trades: "oficios activos",
    cities: "plazas activas",
    freshness: "Última actualización",
    updated: "Actualizado hace {time}",
    changes: "Qué cambia esta propuesta",
    change1Title: "Alcance activo",
    change1Text: "{n} oportunidades en 7 días en lugar de 127.792 históricas.",
    change2Title: "Dueño en el inventario",
    change2Text: "8.503 obras activas con propietario identificado (88%).",
    change3Title: "Frescura real",
    change3Text: "Actualización calculada en tiempo real, en lugar de “ahora”.",
    note: "El KPI “Nuevas” (2.293) se mantiene exactamente igual, por decisión estratégica.",
    snapshot: "Datos del snapshot · 12/11/2026 03:05Z",
  },
} as const;

function parseServerTime(value?: string | null): number | null {
  if (!value) return null;
  const normalized = /Z$|[+-]\d{2}:?\d{2}$/.test(value) ? value : `${value}Z`;
  const ms = Date.parse(normalized);
  return Number.isFinite(ms) ? ms : null;
}

function formatAgo(ms: number | null, now: number): string {
  if (ms === null) return "1h 27m";
  const minutes = Math.max(0, Math.round((now - ms) / 60000));
  if (minutes < 1) return "0 min";
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest ? `${hours}h ${rest}m` : `${hours}h`;
}

export default function DashboardProposalPage() {
  const { lang } = useI18n();
  const c = COPY[lang] ?? COPY.pt;
  const [metrics, setMetrics] = useState<PublicMetrics | null>(null);
  const [active, setActive] = useState(SNAPSHOT.active);
  const [gridCities, setGridCities] = useState<Record<string, number> | null>(null);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    let mounted = true;
    Promise.allSettled([fetchPublicMetrics(), fetchTradeGrid()]).then(([m, g]) => {
      if (!mounted) return;
      if (m.status === "fulfilled") setMetrics(m.value);
      if (g.status === "fulfilled" && g.value.total > 0) {
        setActive(g.value.total);
        const byLabel: Record<string, number> = {};
        g.value.cities.forEach((city) => {
          byLabel[city.label] = city.count;
        });
        setGridCities(byLabel);
      }
    });
    const timer = setInterval(() => setNow(Date.now()), 60000);
    return () => {
      mounted = false;
      clearInterval(timer);
    };
  }, []);

  const freshness = useMemo(
    () => formatAgo(parseServerTime(metrics?.last_scrape?.finished_at), now),
    [metrics, now],
  );
  const novas = metrics?.last_scrape?.novas_oportunidades ?? SNAPSHOT.novas;
  const citiesRows = SNAPSHOT.citiesRows.map((row) => ({
    ...row,
    active: gridCities?.[row.key] ?? row.active,
  }));

  const kpis = [
    {
      label: c.kpiActive,
      value: active,
      delta: c.kpiActiveDelta,
      icon: Activity,
      tone: "emerald" as const,
    },
    {
      label: c.kpiOwners,
      value: SNAPSHOT.owners,
      delta: `${SNAPSHOT.ownerPct}% ${c.kpiOwnersDelta}`,
      icon: Users,
      tone: "violet" as const,
      bar: SNAPSHOT.ownerPct,
    },
    {
      label: c.kpiUrgent,
      value: SNAPSHOT.urgent,
      delta: c.kpiUrgentDelta,
      icon: AlertCircle,
      tone: "amber" as const,
    },
    {
      label: c.kpiNew,
      value: novas,
      delta: c.kpiNewDelta,
      icon: TrendingUp,
      tone: "slate" as const,
    },
  ];

  return (
    <main className="relative min-h-screen overflow-hidden bg-[#070a12] text-white">
      <div className="pointer-events-none absolute -right-40 -top-40 h-[520px] w-[520px] rounded-full bg-[#10b981]/[0.08] blur-3xl" />
      <div className="pointer-events-none absolute -left-32 top-1/3 h-[420px] w-[420px] rounded-full bg-[#7c5cff]/[0.05] blur-3xl" />
      <div className="pointer-events-none absolute inset-0 grid-fade opacity-40" />

      <div className="relative mx-auto flex max-w-[1400px] gap-6 px-4 py-6 sm:px-8">
        <aside className="hidden w-[220px] shrink-0 flex-col rounded-[1.75rem] border border-white/[0.06] bg-white/[0.025] p-4 backdrop-blur-xl lg:flex">
          <div className="flex items-center gap-2.5 px-2">
            <span className="grid h-9 w-9 place-items-center rounded-xl bg-gradient-to-br from-[#34e0a1] to-[#7c5cff] text-[12px] font-black text-[#04120d]">
              ML
            </span>
            <span className="font-display text-[15px] font-black tracking-tight">
              Magic<span className="text-[#34e0a1]">Leads</span>
            </span>
          </div>
          <nav className="mt-8 space-y-1">
            {[
              { icon: LayoutDashboard, label: c.overview, active: true },
              { icon: FolderKanban, label: c.navOpportunities, active: false },
              { icon: Bell, label: c.navAlerts, active: false },
            ].map((item) => (
              <div
                key={item.label}
                className={`flex items-center gap-2.5 rounded-xl px-3 py-2.5 text-[12px] font-semibold ${
                  item.active
                    ? "bg-[#34e0a1]/10 text-[#34e0a1] ring-1 ring-[#34e0a1]/15"
                    : "text-white/40"
                }`}
              >
                <item.icon className="h-4 w-4" />
                {item.label}
              </div>
            ))}
          </nav>
          <div className="mt-auto rounded-2xl border border-white/[0.06] bg-black/20 p-3">
            <p className="text-[8px] font-black uppercase tracking-[0.16em] text-white/25">
              {c.freshness}
            </p>
            <p className="mt-1 inline-flex items-center gap-1.5 text-[11px] font-bold text-white/70">
              <span className="h-1.5 w-1.5 rounded-full bg-[#34e0a1]" />
              {freshness}
            </p>
          </div>
        </aside>

        <div className="min-w-0 flex-1">
          <header className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex min-w-0 items-center gap-2 rounded-xl border border-white/[0.07] bg-white/[0.03] px-3 py-2 text-white/35 sm:w-72">
              <Search className="h-3.5 w-3.5 shrink-0" />
              <span className="truncate text-[11px]">{c.search}</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="rounded-full border border-[#34e0a1]/25 bg-[#34e0a1]/10 px-2.5 py-1 text-[8px] font-black uppercase tracking-[0.14em] text-[#34e0a1]">
                {c.preview}
              </span>
              <span className="grid h-8 w-8 place-items-center rounded-full bg-gradient-to-br from-[#34e0a1] to-[#7c5cff] text-[9px] font-black text-[#04120d]">
                ML
              </span>
            </div>
          </header>

          <div className="mt-8 flex flex-wrap items-end justify-between gap-3">
            <div>
              <p className="text-[9px] font-black uppercase tracking-[0.18em] text-[#34e0a1]">
                Dashboard
              </p>
              <h1 className="font-display mt-1.5 text-[2rem] font-black leading-none tracking-[-0.04em]">
                {c.overview}
              </h1>
              <p className="mt-2 text-[11px] font-medium text-white/35">{c.subtitle}</p>
            </div>
            <div className="inline-flex items-center gap-2 rounded-full border border-white/[0.07] bg-white/[0.03] px-3 py-1.5 text-[10px] font-semibold text-white/45">
              <Clock className="h-3.5 w-3.5 text-[#34e0a1]" />
              {c.updated.replace("{time}", freshness)}
            </div>
          </div>

          <section className="mt-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {kpis.map((kpi) => {
              const tone =
                kpi.tone === "emerald"
                  ? { text: "text-[#34e0a1]", bg: "bg-[#34e0a1]/10", ring: "ring-[#34e0a1]/15" }
                  : kpi.tone === "violet"
                    ? { text: "text-[#a78bfa]", bg: "bg-[#a78bfa]/10", ring: "ring-[#a78bfa]/15" }
                    : kpi.tone === "amber"
                      ? { text: "text-[#fbbf24]", bg: "bg-[#fbbf24]/10", ring: "ring-[#fbbf24]/15" }
                      : { text: "text-white/55", bg: "bg-white/[0.05]", ring: "ring-white/10" };
              return (
                <article
                  key={kpi.label}
                  className="relative overflow-hidden rounded-[1.35rem] border border-white/[0.07] bg-white/[0.03] p-5 backdrop-blur-xl transition-colors duration-300 hover:border-white/[0.12]"
                >
                  <div className="flex items-start justify-between gap-3">
                    <p className="text-[9px] font-black uppercase tracking-[0.14em] text-white/35">
                      {kpi.label}
                    </p>
                    <span className={`grid h-8 w-8 place-items-center rounded-xl ring-1 ${tone.bg} ${tone.ring} ${tone.text}`}>
                      <kpi.icon className="h-4 w-4" />
                    </span>
                  </div>
                  <p className="mono-data mt-4 text-[2.1rem] font-black leading-none tracking-[-0.05em] tabular-nums text-white">
                    {kpi.value.toLocaleString("en-US")}
                  </p>
                  <p className={`mt-2 text-[10px] font-semibold ${kpi.tone === "amber" ? "text-[#fbbf24]/80" : "text-white/40"}`}>
                    {kpi.delta}
                  </p>
                  {typeof kpi.bar === "number" && (
                    <div className="mt-3 h-1 overflow-hidden rounded-full bg-white/[0.06]">
                      <div className="h-full rounded-full bg-[#a78bfa]" style={{ width: `${kpi.bar}%` }} />
                    </div>
                  )}
                </article>
              );
            })}
          </section>

          <section className="mt-4 grid gap-3 lg:grid-cols-[1.45fr_1fr]">
            <div className="rounded-[1.35rem] border border-white/[0.07] bg-white/[0.03] p-5 backdrop-blur-xl">
              <div className="flex flex-wrap items-end justify-between gap-2">
                <div>
                  <h2 className="font-display text-[15px] font-black tracking-tight">{c.coverage}</h2>
                  <p className="mt-1 text-[10px] text-white/30">{c.coverageSub}</p>
                </div>
                <span className="rounded-full border border-white/[0.07] px-2 py-0.5 text-[8px] font-black uppercase tracking-[0.12em] text-white/30">
                  {c.sevenDays}
                </span>
              </div>
              <div className="mt-4 space-y-3">
                {citiesRows.map((row) => {
                  const width = Math.max(6, Math.round((row.active / citiesRows[0].active) * 100));
                  return (
                    <div key={row.key} className="grid grid-cols-[86px_1fr_54px] items-center gap-3 sm:grid-cols-[110px_1fr_64px_54px]">
                      <span className="inline-flex items-center gap-1.5 text-[11px] font-bold text-white/70">
                        <MapPin className="h-3 w-3 text-[#34e0a1]" />
                        {row.key}
                      </span>
                      <div className="hidden h-1.5 overflow-hidden rounded-full bg-white/[0.05] sm:block">
                        <div className="h-full rounded-full bg-gradient-to-r from-[#10b981] to-[#34e0a1]" style={{ width: `${width}%` }} />
                      </div>
                      <span className="mono-data text-right text-[12px] font-black tabular-nums text-white">
                        {row.active.toLocaleString("en-US")}
                      </span>
                      <span className="mono-data text-right text-[10px] font-bold tabular-nums text-[#a78bfa]">
                        {row.ownerPct}%
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>

            <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-1">
              {[
                { icon: ShieldCheck, value: `${SNAPSHOT.ownerPct}%`, label: c.owner, tone: "text-[#a78bfa]" },
                { icon: MapPin, value: SNAPSHOT.zips.toLocaleString("en-US"), label: c.zips, tone: "text-[#34e0a1]" },
                { icon: Activity, value: "16", label: c.trades, tone: "text-[#34e0a1]" },
              ].map((item) => (
                <div key={item.label} className="flex items-center gap-3 rounded-[1.35rem] border border-white/[0.07] bg-white/[0.03] px-4 py-3 backdrop-blur-xl">
                  <span className="grid h-8 w-8 place-items-center rounded-xl bg-white/[0.04] text-white/45">
                    <item.icon className="h-4 w-4" />
                  </span>
                  <div>
                    <p className={`mono-data text-[15px] font-black leading-none ${item.tone}`}>{item.value}</p>
                    <p className="mt-0.5 text-[9px] font-bold uppercase tracking-[0.1em] text-white/30">{item.label}</p>
                  </div>
                </div>
              ))}
            </div>
          </section>

          <section className="mt-6 rounded-[1.35rem] border border-white/[0.07] bg-white/[0.02] p-5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="font-display text-[14px] font-black tracking-tight">{c.changes}</h2>
              <span className="inline-flex items-center gap-1.5 text-[9px] font-bold text-white/25">
                <ChevronRight className="h-3.5 w-3.5" />
                {c.note}
              </span>
            </div>
            <div className="mt-4 grid gap-3 md:grid-cols-3">
              {[
                { title: c.change1Title, text: c.change1Text.replace("{n}", active.toLocaleString("en-US")) },
                { title: c.change2Title, text: c.change2Text },
                { title: c.change3Title, text: c.change3Text },
              ].map((item, i) => (
                <div key={item.title} className="rounded-xl border border-white/[0.06] bg-black/20 p-3.5">
                  <p className="mono-data text-[9px] font-black text-[#34e0a1]">0{i + 1}</p>
                  <p className="mt-1.5 text-[11px] font-bold text-white/80">{item.title}</p>
                  <p className="mt-1 text-[10px] leading-relaxed text-white/35">{item.text}</p>
                </div>
              ))}
            </div>
            <p className="mt-4 text-[9px] font-semibold text-white/20">{c.snapshot}</p>
          </section>
        </div>
      </div>
    </main>
  );
}

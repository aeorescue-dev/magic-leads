"use client";

import {
  Activity,
  AlertTriangle,
  ArrowLeft,
  BarChart3,
  Calendar,
  CheckCircle2,
  Clock,
  Download,
  Eye,
  Globe2,
  Loader2,
  MousePointerClick,
  RefreshCcw,
  Send,
  ShieldCheck,
  Users,
} from "lucide-react";
import { useState, type ReactNode } from "react";
import useSWR from "swr";

import { AdminApiError, fetchAdminAnalytics } from "@/lib/admin-api";
import type { AdminAnalytics } from "@/lib/admin-api";
import { downloadAnalyticsCsv } from "@/lib/analytics-csv";
import {
  fmtWhen,
  fmtValue,
  scoreClasses,
  sparkPoints,
  statusClasses,
} from "@/lib/system-health";

const RANGES = ["24h", "7d", "30d"] as const;
type RangeKey = (typeof RANGES)[number];

const EVENT_LABELS: Record<string, string> = {
  pageview: "Visita",
  cta_click: "Clique CTA",
  form_start: "Início formulário",
  form_submit: "Formulário enviado",
  scroll: "Scroll",
  outbound_click: "Link externo",
  language_switch: "Mudança de idioma",
  pricing_view: "Planos",
};

function cn(...values: Array<string | false | null | undefined>) {
  return values.filter(Boolean).join(" ");
}

function ScoreRing({ score, size = 118 }: { score: number; size?: number }) {
  const classes = scoreClasses(score);
  const stroke = 10;
  const radius = (size - stroke) / 2;
  const center = size / 2;
  return (
    <div className="relative" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={center} cy={center} r={radius} fill="none" strokeWidth={stroke} className="stroke-white/10" />
        <circle
          cx={center}
          cy={center}
          r={radius}
          fill="none"
          strokeWidth={stroke}
          strokeLinecap="round"
          pathLength={100}
          strokeDasharray={`${Math.max(0, Math.min(100, score))} 100`}
          className={classes.ring}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className={cn("text-2xl font-black", classes.text)}>{score}</span>
        <span className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">
          / 100
        </span>
      </div>
    </div>
  );
}

function Spark({ values }: { values: number[] }) {
  if (!values || values.length < 2) {
    return <div className="h-8 w-[110px] rounded bg-white/5" />;
  }
  return (
    <svg width={110} height={30} className="overflow-visible">
      <polyline
        points={sparkPoints(values, 110, 30)}
        fill="none"
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
        className="stroke-indigo-400"
      />
    </svg>
  );
}

function Kpi({
  label,
  value,
  unit,
  delta,
  spark,
  icon,
  inverse = false,
}: {
  label: string;
  value: number;
  unit?: string;
  delta: number | null;
  spark: number[];
  icon: ReactNode;
  inverse?: boolean;
}) {
  const good = delta == null ? null : inverse ? delta <= 0 : delta >= 0;
  return (
    <div className="rounded-2xl border border-white/10 bg-[#10131a] p-3">
      <div className="flex items-center justify-between text-slate-500">
        <span className="text-[10px] font-semibold uppercase tracking-wide">{label}</span>
        {icon}
      </div>
      <div className="mt-1 flex items-end justify-between gap-2">
        <span className="text-xl font-black text-slate-100">
          {fmtValue(value, unit)}
        </span>
        <Spark values={spark} />
      </div>
      <p
        className={cn(
          "mt-0.5 text-[10px] font-semibold",
          good == null
            ? "text-slate-500"
            : good
              ? "text-emerald-300"
              : "text-rose-300"
        )}
      >
        {delta == null ? "sem comparação" : `${delta > 0 ? "+" : ""}${delta}% vs período anterior`}
      </p>
    </div>
  );
}

function Section({
  title,
  icon,
  hint,
  children,
}: {
  title: string;
  icon: ReactNode;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <section className="rounded-2xl border border-white/10 bg-[#10131a] p-4">
      <div className="mb-3">
        <h2 className="flex items-center gap-2 text-sm font-bold text-slate-200">
          {icon}
          {title}
        </h2>
        {hint ? <p className="mt-0.5 text-[11px] text-slate-500">{hint}</p> : null}
      </div>
      {children}
    </section>
  );
}

function GateScreen({ status, message }: { status: number; message: string }) {
  return (
    <div className="flex min-h-screen items-center justify-center p-6">
      <div className="max-w-md rounded-2xl border border-white/10 bg-[#10131a] p-6 text-center">
        <ShieldCheck className="mx-auto mb-3 h-8 w-8 text-rose-400" />
        <h1 className="text-lg font-bold text-slate-100">
          {status === 403 ? "Sem permissão de administrador" : "Sessão expirada"}
        </h1>
        <p className="mt-2 text-sm text-slate-400">{message}</p>
        <div className="mt-4 flex justify-center gap-2">
          {status === 401 ? (
            <a href="/pt/auth" className="rounded-lg bg-indigo-500 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-400">
              Fazer login
            </a>
          ) : null}
          <a href="/admin" className="rounded-lg border border-white/10 px-4 py-2 text-sm font-semibold text-slate-300 hover:bg-white/5">
            Voltar ao Admin
          </a>
        </div>
      </div>
    </div>
  );
}

export default function AnalyticsPage() {
  const [range, setRange] = useState<RangeKey>("7d");
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");
  const [custom, setCustom] = useState(false);
  const [dateError, setDateError] = useState<string | null>(null);
  const today = new Date().toISOString().slice(0, 10);
  const { data, error, isLoading, isValidating, mutate } = useSWR<AdminAnalytics>(
    ["admin-analytics", range, custom ? fromDate : "", custom ? toDate : ""],
    () =>
      fetchAdminAnalytics(
        range,
        custom ? fromDate : undefined,
        custom ? toDate : undefined
      ),
    { refreshInterval: 30_000, keepPreviousData: true, revalidateOnFocus: true }
  );

  const applyCustom = () => {
    if (!fromDate || !toDate) {
      setDateError("Escolhe a data inicial e final.");
      return;
    }
    if (fromDate > toDate) {
      setDateError("A data inicial tem de ser anterior à final.");
      return;
    }
    const days =
      Math.round(
        (Date.parse(toDate) - Date.parse(fromDate)) / (24 * 60 * 60 * 1000)
      ) + 1;
    if (days > 366) {
      setDateError("O intervalo máximo é de 366 dias.");
      return;
    }
    setDateError(null);
    setCustom(true);
  };

  const clearCustom = () => {
    setCustom(false);
    setFromDate("");
    setToDate("");
    setDateError(null);
  };

  if (error instanceof AdminApiError && (error.status === 401 || error.status === 403)) {
    return (
      <GateScreen
        status={error.status}
        message={
          error.status === 403
            ? "A tua sessão é válida mas a conta não tem o perfil de administrador."
            : "A tua sessão de administrador expirou. Volta a entrar para continuar."
        }
      />
    );
  }
  if (!data && isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center gap-3 text-slate-400">
        <Loader2 className="h-5 w-5 animate-spin" /> A carregar analytics…
      </div>
    );
  }
  if (!data) {
    return (
      <div className="flex min-h-screen items-center justify-center p-6">
        <div className="max-w-md rounded-2xl border border-white/10 bg-[#10131a] p-6 text-center">
          <AlertTriangle className="mx-auto mb-3 h-8 w-8 text-amber-400" />
          <h1 className="text-lg font-bold text-slate-100">Telemetria indisponível</h1>
          <p className="mt-2 text-sm text-slate-400">
            {error instanceof Error ? error.message : "Não foi possível falar com a API."}
          </p>
          <button
            type="button"
            onClick={() => void mutate()}
            className="mt-4 rounded-lg bg-indigo-500 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-400"
          >
            Tentar novamente
          </button>
        </div>
      </div>
    );
  }

  const cards = data.cards;
  const overall = data.overall;
  const overallClasses = scoreClasses(overall.score);
  const maxSource = Math.max(1, ...data.sources.map((s) => s.visits));
  const campaignRows = [...data.campaigns]
    .filter((campaign) => campaign.campaign && campaign.campaign !== "(none)")
    .sort(
      (a, b) =>
        Number(b.source === "email") - Number(a.source === "email") ||
        b.visits - a.visits
    )
    .slice(0, 8);
  const email = data.email_attribution;
  const maxGeo = Math.max(1, ...data.geo.map((g) => g.visits));
  const funnelMax = Math.max(1, ...data.funnel.map((f) => f.count));

  return (
    <main className="mx-auto max-w-[1400px] px-4 py-6 text-slate-200">
      <header className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div>
          <a href="/admin" className="mb-1 inline-flex items-center gap-1 text-xs font-semibold text-slate-400 hover:text-slate-200">
            <ArrowLeft className="h-3.5 w-3.5" /> Torre de Controlo
          </a>
          <h1 className="flex items-center gap-2 text-xl font-bold text-slate-100">
            <BarChart3 className="h-5 w-5 text-indigo-400" /> Web Analytics
          </h1>
          <p className="text-[11px] text-slate-500">
            First-party, sem cookies · gerado em {fmtWhen(data.generated_at)} · período{" "}
            {data.start} → {data.end} (UTC){custom ? " · personalizado" : ""} · atualiza a cada 30 s
            {isValidating ? " · a atualizar…" : ""}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex rounded-lg border border-white/10 p-0.5">
            {RANGES.map((option) => (
              <button
                key={option}
                type="button"
                onClick={() => {
                  setRange(option);
                  setCustom(false);
                  setDateError(null);
                }}
                className={cn(
                  "rounded-md px-2.5 py-1.5 text-[11px] font-semibold",
                  !custom && range === option
                    ? "bg-indigo-500 text-white"
                    : "text-slate-400 hover:text-slate-200"
                )}
              >
                {option}
              </button>
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-1 rounded-lg border border-white/10 p-1">
            <Calendar className="ml-1 h-3.5 w-3.5 text-slate-500" />
            <input
              type="date"
              value={fromDate}
              max={toDate || today}
              onChange={(event) => setFromDate(event.target.value)}
              aria-label="Data inicial"
              style={{ colorScheme: "dark" }}
              className="rounded bg-transparent px-1 py-1 text-[11px] text-slate-300 outline-none"
            />
            <span className="text-[10px] text-slate-500">até</span>
            <input
              type="date"
              value={toDate}
              min={fromDate || undefined}
              max={today}
              onChange={(event) => setToDate(event.target.value)}
              aria-label="Data final"
              style={{ colorScheme: "dark" }}
              className="rounded bg-transparent px-1 py-1 text-[11px] text-slate-300 outline-none"
            />
            <button
              type="button"
              onClick={applyCustom}
              disabled={!fromDate || !toDate}
              className="rounded-md bg-indigo-500 px-2 py-1 text-[10px] font-semibold text-white hover:bg-indigo-400 disabled:opacity-40"
            >
              Aplicar
            </button>
            {custom ? (
              <button
                type="button"
                onClick={clearCustom}
                title="Limpar período personalizado"
                className="rounded-md px-1.5 py-1 text-[12px] font-bold text-slate-400 hover:text-slate-200"
              >
                ×
              </button>
            ) : null}
          </div>
          <button
            type="button"
            onClick={() => downloadAnalyticsCsv(data)}
            className="inline-flex items-center gap-2 rounded-lg border border-emerald-400/30 bg-emerald-500/10 px-3 py-2 text-xs font-semibold text-emerald-200 hover:bg-emerald-500/20"
          >
            <Download className="h-3.5 w-3.5" />
            CSV
          </button>
          <button
            type="button"
            onClick={() => void mutate()}
            className="inline-flex items-center gap-2 rounded-lg border border-white/10 px-3 py-2 text-xs font-semibold text-slate-300 hover:bg-white/5"
          >
            <RefreshCcw className={cn("h-3.5 w-3.5", isValidating && "animate-spin")} />
            Atualizar
          </button>
        </div>
      </header>
      {dateError ? (
        <p className="-mt-3 mb-3 text-[11px] font-semibold text-rose-300">{dateError}</p>
      ) : null}

      <section className="mb-5 rounded-2xl border border-white/10 bg-gradient-to-br from-[#121722] to-[#0d1017] p-5">
        <div className="flex flex-wrap items-center gap-6">
          <ScoreRing score={overall.score} />
          <div className="min-w-[230px] flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-lg font-bold text-slate-100">Saúde do tráfego</h2>
              <span className={cn("rounded-full border px-2 py-0.5 text-[11px] font-semibold", statusClasses(overall.status))}>
                {overall.status_label}
              </span>
              <span className={cn("text-sm font-bold", overallClasses.text)}>{overall.score}/100</span>
            </div>
            <div className="mt-3 grid gap-2 sm:grid-cols-3">
              {[
                ["Volume", overall.volume],
                ["Engajamento", overall.engagement],
                ["Conversão", overall.conversion],
              ].map(([label, value]) => (
                <div key={String(label)}>
                  <div className="flex items-center justify-between text-[10px] text-slate-500">
                    <span>{label}</span>
                    <span className="font-semibold text-slate-300">{value}</span>
                  </div>
                  <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-white/10">
                    <div
                      className={cn("h-full rounded-full", scoreClasses(Number(value)).bar)}
                      style={{ width: `${value}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
            {overall.reasons.length ? (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {overall.reasons.map((reason) => (
                  <span key={reason} className="rounded-full border border-amber-500/20 bg-amber-500/10 px-2 py-0.5 text-[11px] text-amber-200">
                    {reason}
                  </span>
                ))}
              </div>
            ) : (
              <p className="mt-2 text-[11px] font-semibold text-emerald-300">Sem sinais de degradação.</p>
            )}
          </div>
        </div>
      </section>

      <div className="mb-5 grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-7">
        <Kpi label="Visitas" value={cards.visits.value} delta={cards.visits.delta_pct} spark={cards.visits.spark} icon={<Activity className="h-3.5 w-3.5" />} />
        <Kpi label="Visitantes" value={cards.visitors.value} delta={cards.visitors.delta_pct} spark={cards.visitors.spark} icon={<Users className="h-3.5 w-3.5" />} />
        <Kpi label="Pageviews" value={cards.pageviews.value} delta={cards.pageviews.delta_pct} spark={cards.pageviews.spark} icon={<Eye className="h-3.5 w-3.5" />} />
        <Kpi label="CTA clicks" value={cards.cta_clicks.value} delta={cards.cta_clicks.delta_pct} spark={cards.cta_clicks.spark} icon={<MousePointerClick className="h-3.5 w-3.5" />} />
        <Kpi label="Form submits" value={cards.form_submits.value} delta={cards.form_submits.delta_pct} spark={cards.form_submits.spark} icon={<Send className="h-3.5 w-3.5" />} />
        <Kpi label="Tempo médio" value={cards.avg_engagement_s.value} unit="s" delta={cards.avg_engagement_s.delta_pct} spark={cards.avg_engagement_s.spark} icon={<Clock className="h-3.5 w-3.5" />} />
        <Kpi label="Bounce" value={cards.bounce_rate.value} unit="%" delta={cards.bounce_rate.delta_pct} spark={cards.bounce_rate.spark} icon={<Activity className="h-3.5 w-3.5" />} inverse />
      </div>

      <div className="grid gap-5 xl:grid-cols-2">
        <Section title="Tráfego no período" icon={<BarChart3 className="h-4 w-4 text-indigo-400" />} hint="Visitas por hora (24h) ou por dia (7/30d)">
          {data.series.length ? (
            <div className="flex h-40 items-end gap-1">
              {data.series.map((point) => {
                const max = Math.max(1, ...data.series.map((p) => p.visits));
                return (
                  <div key={point.t} className="group relative flex flex-1 flex-col items-center justify-end gap-1">
                    <div
                      className="w-full rounded-t bg-indigo-400/80 transition group-hover:bg-indigo-300"
                      style={{ height: `${Math.max(3, (point.visits / max) * 100)}%` }}
                    />
                    <span className="hidden text-[9px] text-slate-500 group-hover:block">
                      {point.visits}
                    </span>
                  </div>
                );
              })}
            </div>
          ) : (
            <p className="py-8 text-center text-xs text-slate-500">Sem tráfego no período.</p>
          )}
          <div className="mt-3 flex flex-wrap gap-3 text-[10px] text-slate-500">
            <span className="inline-flex items-center gap-1"><span className="h-2 w-2 rounded-sm bg-indigo-400" /> visitas</span>
            <span><strong className="text-slate-300">{fmtValue(data.series.reduce((a, p) => a + p.visits, 0))}</strong> no total</span>
          </div>
        </Section>

        <Section title="Origem do tráfego" icon={<Globe2 className="h-4 w-4 text-indigo-400" />} hint="UTM/referrer classificados no servidor">
          {data.sources.length ? (
            <div className="space-y-2">
              {data.sources.map((source) => (
                <div key={`${source.source}-${source.medium}`}>
                  <div className="flex items-center justify-between text-[11px]">
                    <span className="font-semibold text-slate-300">
                      {source.source}
                      <span className="ml-1 font-normal text-slate-500">/ {source.medium}</span>
                    </span>
                    <span className="text-slate-400">
                      {source.visits} visitas · {source.visitors} únicos
                    </span>
                  </div>
                  <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-white/10">
                    <div className="h-full rounded-full bg-emerald-400" style={{ width: `${(source.visits / maxSource) * 100}%` }} />
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="py-8 text-center text-xs text-slate-500">Sem origens registadas.</p>
          )}
          <h3 className="mt-4 mb-2 text-[10px] font-bold uppercase tracking-wide text-slate-500">
            Campanhas / passo do e-mail
          </h3>
          {campaignRows.length ? (
            <div className="space-y-2">
              {campaignRows.map((campaign) => (
                <div
                  key={`${campaign.source}-${campaign.medium}-${campaign.campaign}-${campaign.content}`}
                  className="rounded-lg border border-white/5 bg-white/[0.02] p-2"
                >
                  <div className="flex items-center justify-between gap-2 text-[11px]">
                    <span className="truncate font-mono text-[10px] text-slate-300">
                      {campaign.campaign}
                    </span>
                    <span className="shrink-0 text-slate-500">
                      {campaign.content || "—"}
                    </span>
                  </div>
                  <div className="mt-0.5 flex items-center justify-between text-[10px] text-slate-500">
                    <span>
                      {campaign.source}/{campaign.medium}
                    </span>
                    <span>
                      {campaign.visits} visitas · {campaign.cta_clicks} CTA ·{" "}
                      {campaign.form_submits} forms
                    </span>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="py-4 text-center text-[11px] text-slate-500">
              Sem campanhas UTM ainda. Os links de outreach já saem com UTM.
            </p>
          )}
        </Section>

        <Section title="Funil de conversão" icon={<Activity className="h-4 w-4 text-indigo-400" />} hint="Sessões distintas em cada passo">
          <div className="space-y-2">
            {data.funnel.map((step) => (
              <div key={step.step}>
                <div className="flex items-center justify-between text-[11px]">
                  <span className="text-slate-300">{step.step}</span>
                  <span className="text-slate-400">
                    {step.count} · {step.rate.toFixed(1)}%
                  </span>
                </div>
                <div className="mt-1 h-2 overflow-hidden rounded-full bg-white/10">
                  <div
                    className="h-full rounded-full bg-amber-400"
                    style={{ width: `${Math.max(step.count ? 2 : 0, (step.count / funnelMax) * 100)}%` }}
                  />
                </div>
              </div>
            ))}
          </div>
        </Section>

        <Section title="E-mail → Lead" icon={<Send className="h-4 w-4 text-indigo-400" />} hint="Formulários preenchidos por campanha, passo e cidade">
          <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
            {[
              ["Visitas email", email.visits, ""],
              ["CTA", email.cta_clicks, ""],
              ["Forms", email.form_submits, ""],
              ["Taxa", email.form_rate, "%"],
            ].map(([label, value, unit]) => (
              <div key={String(label)} className="rounded-lg border border-white/5 bg-white/[0.02] p-2">
                <p className="text-[10px] text-slate-500">{label}</p>
                <p className="text-lg font-bold text-slate-100">
                  {fmtValue(value as number, String(unit))}
                </p>
              </div>
            ))}
          </div>
          <div className="mt-3 overflow-x-auto">
            <table className="w-full text-left text-[11px]">
              <thead className="text-slate-500">
                <tr>
                  <th className="pb-1">Campanha</th>
                  <th className="pb-1">Step</th>
                  <th className="pb-1">Cidade</th>
                  <th className="pb-1 text-right">Visitas</th>
                  <th className="pb-1 text-right">CTA</th>
                  <th className="pb-1 text-right">Forms</th>
                  <th className="pb-1 text-right">Taxa</th>
                </tr>
              </thead>
              <tbody>
                {email.rows.map((row) => (
                  <tr key={`${row.campaign}-${row.content}-${row.city}`} className="border-t border-white/5">
                    <td className="max-w-[160px] truncate py-1.5 font-mono text-[10px] text-slate-300">
                      {row.campaign}
                    </td>
                    <td className="py-1.5 text-slate-400">{row.content || "—"}</td>
                    <td className="py-1.5 text-slate-400">{row.city || "—"}</td>
                    <td className="py-1.5 text-right text-slate-300">{row.visits}</td>
                    <td className="py-1.5 text-right text-slate-300">{row.cta_clicks}</td>
                    <td className="py-1.5 text-right font-semibold text-emerald-300">{row.form_submits}</td>
                    <td className="py-1.5 text-right text-slate-400">{row.form_rate.toFixed(1)}%</td>
                  </tr>
                ))}
                {!email.rows.length ? (
                  <tr>
                    <td colSpan={7} className="py-6 text-center text-slate-500">
                      Sem formulários atribuídos a e-mail no período.
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </Section>

        <Section title="Geografia" icon={<Globe2 className="h-4 w-4 text-indigo-400" />} hint="País/região/cidade (cidade-level, sem coordenadas)">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-[11px]">
              <thead className="text-slate-500">
                <tr>
                  <th className="pb-1">País</th>
                  <th className="pb-1">Cidade</th>
                  <th className="pb-1 text-right">Visitas</th>
                  <th className="pb-1 text-right">Únicos</th>
                  <th className="pb-1 text-right">CTA</th>
                  <th className="pb-1 text-right">Forms</th>
                </tr>
              </thead>
              <tbody>
                {data.geo.map((row) => (
                  <tr key={`${row.country}-${row.region}-${row.city}`} className="border-t border-white/5">
                    <td className="py-1.5 font-semibold text-slate-300">{row.country || "—"}</td>
                    <td className="py-1.5 text-slate-400">
                      {row.city || row.region || "—"}
                    </td>
                    <td className="py-1.5 text-right text-slate-300">{row.visits}</td>
                    <td className="py-1.5 text-right text-slate-400">{row.visitors}</td>
                    <td className="py-1.5 text-right text-slate-300">{row.cta_clicks}</td>
                    <td className="py-1.5 text-right text-emerald-300">{row.form_submits}</td>
                  </tr>
                ))}
                {!data.geo.length ? (
                  <tr>
                    <td colSpan={6} className="py-6 text-center text-slate-500">
                      Sem dados geográficos.
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </Section>

        <Section title="Dispositivo e idioma" icon={<Users className="h-4 w-4 text-indigo-400" />}>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <p className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-slate-500">Dispositivo</p>
              {data.devices.map((row) => (
                <div key={row.device} className="flex justify-between text-[11px]">
                  <span className="text-slate-400">{row.device}</span>
                  <span className="font-semibold text-slate-300">{row.visits}</span>
                </div>
              ))}
            </div>
            <div>
              <p className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-slate-500">Idioma</p>
              {data.locales.map((row) => (
                <div key={row.locale} className="flex justify-between text-[11px]">
                  <span className="text-slate-400">{row.locale}</span>
                  <span className="font-semibold text-slate-300">{row.visits}</span>
                </div>
              ))}
            </div>
          </div>
        </Section>

        <Section title="Ações recentes" icon={<MousePointerClick className="h-4 w-4 text-indigo-400" />} hint="Últimos 15 eventos, sem IP nem dados pessoais">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-[11px]">
              <thead className="text-slate-500">
                <tr>
                  <th className="pb-1">Quando</th>
                  <th className="pb-1">Evento</th>
                  <th className="pb-1">Origem</th>
                  <th className="pb-1">Label</th>
                  <th className="pb-1">Página</th>
                </tr>
              </thead>
              <tbody>
                {data.recent.map((row, index) => (
                  <tr key={`${row.ts}-${index}`} className="border-t border-white/5">
                    <td className="py-1.5 text-slate-500">{fmtWhen(row.ts)}</td>
                    <td className="py-1.5 font-semibold text-slate-300">
                      {EVENT_LABELS[row.name] || row.name}
                    </td>
                    <td className="py-1.5 text-[10px] text-slate-400">
                      {row.source === "email" ? (
                        <>
                          <span className="font-semibold text-emerald-300">email</span>
                          <span className="text-slate-500">
                            {" "}· {row.campaign || "?"} · {row.content || "?"}
                          </span>
                        </>
                      ) : (
                        <span className="font-semibold text-slate-300">{row.source}</span>
                      )}
                      {row.city ? (
                        <div className="text-[9px] text-slate-500">{row.city}</div>
                      ) : null}
                    </td>
                    <td className="py-1.5 text-slate-400">{row.label || "—"}</td>
                    <td className="py-1.5 text-slate-500">{row.path || "—"}</td>
                  </tr>
                ))}
                {!data.recent.length ? (
                  <tr>
                    <td colSpan={5} className="py-6 text-center text-slate-500">
                      Sem eventos no período.
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </Section>
      </div>

      <footer className="mt-6 flex flex-wrap items-center gap-3 text-[10px] text-slate-600">
        <CheckCircle2 className="h-3 w-3" />
        <span>First-party · cookieless · sem IP em repouso.</span>
        <span>·</span>
        <span>Raw 90d · sessões 180d.</span>
        <span>·</span>
        <span>UTM de outreach ativo.</span>
      </footer>
    </main>
  );
}

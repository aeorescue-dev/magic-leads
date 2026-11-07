"use client";

import {
  Activity,
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  Clock,
  Database,
  Gauge,
  HardDrive,
  Loader2,
  Mail,
  RefreshCcw,
  Send,
  ShieldAlert,
  Sparkles,
  Users,
  Wifi,
} from "lucide-react";
import type { ReactNode } from "react";
import { useState } from "react";
import useSWR from "swr";

import { AdminApiError, ackAdminAlert, fetchSystemHealth } from "@/lib/admin-api";
import {
  LAYER_HINTS,
  LAYER_ORDER,
  fmtAge,
  fmtValue,
  fmtWhen,
  scoreClasses,
  sparkPoints,
  statusClasses,
  type HealthLayer,
  type HealthStatus,
  type SystemHealth,
} from "@/lib/system-health";

const REFRESH_MS = 30_000;

function ClassNames(...values: Array<string | false | null | undefined>) {
  return values.filter(Boolean).join(" ");
}

function StatusPill({ status, label }: { status: HealthStatus; label: string }) {
  return (
    <span
      className={ClassNames(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-semibold",
        statusClasses(status)
      )}
    >
      {status === "ok" ? (
        <CheckCircle2 className="h-3 w-3" />
      ) : status === "warn" ? (
        <AlertTriangle className="h-3 w-3" />
      ) : status === "fail" ? (
        <ShieldAlert className="h-3 w-3" />
      ) : (
        <Clock className="h-3 w-3" />
      )}
      {label}
    </span>
  );
}

function ScoreRing({
  score,
  size = 120,
  stroke = 10,
}: {
  score: number;
  size?: number;
  stroke?: number;
}) {
  const classes = scoreClasses(score);
  const radius = (size - stroke) / 2;
  const center = size / 2;
  return (
    <div className="relative" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle
          cx={center}
          cy={center}
          r={radius}
          fill="none"
          strokeWidth={stroke}
          className="stroke-white/10"
        />
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
        <span className={ClassNames("text-2xl font-black", classes.text)}>{score}</span>
        <span className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">
          / 100
        </span>
      </div>
    </div>
  );
}

function ScoreBar({ score }: { score: number }) {
  const classes = scoreClasses(score);
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-white/10">
      <div
        className={ClassNames("h-full rounded-full transition-all", classes.bar)}
        style={{ width: `${Math.max(0, Math.min(100, score))}%` }}
      />
    </div>
  );
}

function Sparkline({ values }: { values: number[] }) {
  if (!values.length) {
    return <div className="h-8 w-[120px] rounded bg-white/5" />;
  }
  const classes = scoreClasses(values[values.length - 1]);
  return (
    <svg width={120} height={32} className="overflow-visible">
      <polyline
        points={sparkPoints(values)}
        fill="none"
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
        className={classes.ring}
      />
    </svg>
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
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <h2 className="flex items-center gap-2 text-sm font-bold text-slate-200">
            {icon}
            {title}
          </h2>
          {hint ? <p className="mt-0.5 text-[11px] text-slate-500">{hint}</p> : null}
        </div>
      </div>
      {children}
    </section>
  );
}

function LayerCard({ layer }: { layer: HealthLayer }) {
  const classes = scoreClasses(layer.score);
  return (
    <article className="rounded-2xl border border-white/10 bg-[#10131a] p-4">
      <div className="flex items-start justify-between gap-2">
        <div>
          <h3 className="text-sm font-bold text-slate-200">{layer.label}</h3>
          <p className="text-[11px] text-slate-500">{LAYER_HINTS[layer.key]}</p>
        </div>
        <div className="flex flex-col items-end gap-1">
          <span className={ClassNames("text-2xl font-black", classes.text)}>
            {layer.score}
          </span>
          <StatusPill status={layer.status} label={layer.status_label} />
        </div>
      </div>
      <div className="mt-3">
        <ScoreBar score={layer.score} />
      </div>
      <p className="mt-3 min-h-[32px] text-xs font-medium text-slate-300">
        {layer.headline}
      </p>
      <div className="mt-2 space-y-1.5">
        {layer.metrics.slice(0, 3).map((metric) => (
          <div key={metric.key} className="flex items-center justify-between gap-2 text-[11px]">
            <span className="text-slate-500">{metric.label}</span>
            <span
              className={ClassNames(
                "font-semibold",
                metric.status === "fail"
                  ? "text-rose-300"
                  : metric.status === "warn"
                    ? "text-amber-300"
                    : "text-slate-200"
              )}
            >
              {fmtValue(metric.value, metric.unit)}
            </span>
          </div>
        ))}
      </div>
      {layer.reasons.length ? (
        <ul className="mt-3 space-y-1 border-t border-white/5 pt-2">
          {layer.reasons.slice(0, 2).map((reason) => (
            <li key={reason} className="text-[11px] text-amber-300/90">
              • {reason}
            </li>
          ))}
        </ul>
      ) : null}
    </article>
  );
}

function GateScreen({
  status,
  message,
}: {
  status: number;
  message: string;
}) {
  return (
    <div className="flex min-h-screen items-center justify-center p-6">
      <div className="max-w-md rounded-2xl border border-white/10 bg-[#10131a] p-6 text-center">
        <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-rose-500/15">
          <ShieldAlert className="h-6 w-6 text-rose-400" />
        </div>
        <h1 className="text-lg font-bold text-slate-100">
          {status === 403 ? "Sem permissão de administrador" : "Sessão expirada"}
        </h1>
        <p className="mt-2 text-sm text-slate-400">{message}</p>
        <div className="mt-4 flex justify-center gap-2">
          {status === 401 ? (
            <a
              href="/pt/auth"
              className="inline-block rounded-lg bg-indigo-500 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-400"
            >
              Fazer login
            </a>
          ) : null}
          <a
            href="/admin"
            className="inline-block rounded-lg border border-white/10 px-4 py-2 text-sm font-semibold text-slate-300 hover:bg-white/5"
          >
            Voltar ao Admin
          </a>
        </div>
      </div>
    </div>
  );
}

function LoadingScreen() {
  return (
    <div className="flex min-h-screen items-center justify-center gap-3 text-slate-400">
      <Loader2 className="h-5 w-5 animate-spin" /> A carregar System Health…
    </div>
  );
}

export default function SystemHealthPage() {
  const { data, error, isLoading, isValidating, mutate } = useSWR<SystemHealth>(
    ["system-health", 24],
    () => fetchSystemHealth(24),
    {
      refreshInterval: REFRESH_MS,
      keepPreviousData: true,
      revalidateOnFocus: true,
    }
  );
  const [ackingId, setAckingId] = useState<number | null>(null);
  const [ackError, setAckError] = useState<string | null>(null);

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

  if (!data && isLoading) return <LoadingScreen />;

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

  const handleAck = async (alertId: number) => {
    setAckingId(alertId);
    setAckError(null);
    try {
      await ackAdminAlert(alertId);
      await mutate();
    } catch (err) {
      setAckError(
        err instanceof Error ? err.message : "Não foi possível reconhecer o alerta."
      );
    } finally {
      setAckingId(null);
    }
  };

  const layers = data.layers;
  const overallClasses = scoreClasses(data.overall.score);
  const history = data.history || [];
  const overallHistory = history.map((point) => point.score);

  const ingest = layers.ingest;
  const enrichment = layers.enrichment;
  const outreach = layers.outreach;
  const push = layers.push;
  const quotas = layers.quotas;
  const infra = layers.infra;
  const alerts = layers.alerts;

  const cities = (ingest.detail.cities || []) as any[];
  const runs = (ingest.detail.runs || []) as any[];
  const byCity = (enrichment.detail.by_city || {}) as Record<string, Record<string, number>>;
  const ownerBackfill = (enrichment.detail.owner_backfill || []) as any[];
  const mailboxRows = (outreach.detail.mailboxes || []) as any[];
  const blocker = outreach.detail.queue_blocker as
    | { reason?: string; detail?: string; retry_at?: string }
    | null;
  const brave = (quotas.detail.brave || {}) as Record<string, any>;
  const searchbug = (quotas.detail.searchbug || {}) as Record<string, any>;
  const pushDetail = (push.detail || {}) as Record<string, any>;
  const checks = (infra.detail.checks || []) as any[];
  const alertItems = (alerts.detail.items || []) as any[];

  return (
    <main className="mx-auto max-w-[1400px] px-4 py-6 text-slate-200">
      <header className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div>
          <a
            href="/admin"
            className="mb-1 inline-flex items-center gap-1 text-xs font-semibold text-slate-400 hover:text-slate-200"
          >
            <ArrowLeft className="h-3.5 w-3.5" /> Torre de Controlo
          </a>
          <h1 className="flex items-center gap-2 text-xl font-bold text-slate-100">
            <Gauge className="h-5 w-5 text-indigo-400" /> System Health
          </h1>
          <p className="text-[11px] text-slate-500">
            Gerado em {fmtWhen(data.generated_at)} · atualiza a cada 30 s
            {isValidating ? " · a atualizar…" : ""}
          </p>
        </div>
        <button
          type="button"
          onClick={() => void mutate()}
          className="inline-flex items-center gap-2 rounded-lg border border-white/10 px-3 py-2 text-xs font-semibold text-slate-300 hover:bg-white/5"
        >
          <RefreshCcw className={ClassNames("h-3.5 w-3.5", isValidating && "animate-spin")} />
          Atualizar
        </button>
      </header>

      {/* Score geral */}
      <section className="mb-5 rounded-2xl border border-white/10 bg-gradient-to-br from-[#121722] to-[#0d1017] p-5">
        <div className="flex flex-wrap items-center gap-6">
          <ScoreRing score={data.overall.score} size={132} stroke={11} />
          <div className="min-w-[220px] flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-lg font-bold text-slate-100">Saúde geral</h2>
              <StatusPill status={data.overall.status} label={data.overall.status_label} />
              <span className={ClassNames("text-sm font-bold", overallClasses.text)}>
                {data.overall.score}/100
              </span>
            </div>
            <p className="mt-1 text-xs text-slate-400">
              Média ponderada das 7 camadas; o estado global é o pior delas.
            </p>
            {data.overall.reasons.length ? (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {data.overall.reasons.map((reason) => (
                  <span
                    key={reason}
                    className="rounded-full border border-amber-500/20 bg-amber-500/10 px-2 py-0.5 text-[11px] font-medium text-amber-200"
                  >
                    {reason}
                  </span>
                ))}
              </div>
            ) : (
              <p className="mt-2 text-[11px] font-semibold text-emerald-300">
                Sem sinais de degradação.
              </p>
            )}
          </div>
          <div className="text-right">
            <p className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-slate-500">
              Últimas {data.window_hours}h
            </p>
            <Sparkline values={overallHistory} />
          </div>
        </div>
      </section>

      {/* 7 camadas */}
      <div className="mb-5 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {LAYER_ORDER.map((key) => (
          <LayerCard key={key} layer={layers[key]} />
        ))}
      </div>

      <div className="grid gap-5 xl:grid-cols-2">
        {/* Ingestão */}
        <Section
          title="Ingestão por cidade"
          icon={<Database className="h-4 w-4 text-indigo-400" />}
          hint="Frescura do último facto vs runs de recolha"
        >
          <div className="overflow-x-auto">
            <table className="w-full text-left text-[11px]">
              <thead className="text-slate-500">
                <tr>
                  <th className="pb-2">Cidade</th>
                  <th className="pb-2">Último facto</th>
                  <th className="pb-2 text-right">Idade</th>
                  <th className="pb-2 text-right">24h</th>
                  <th className="pb-2 text-right">Owners</th>
                  <th className="pb-2 text-right">Estado</th>
                </tr>
              </thead>
              <tbody>
                {cities.map((city) => {
                  const age = city.age_h as number | null;
                  const tone = age == null || age > 36 ? "fail" : age > 24 ? "warn" : "ok";
                  return (
                    <tr key={city.city} className="border-t border-white/5">
                      <td className="py-1.5 font-semibold text-slate-200">{city.city}</td>
                      <td className="py-1.5 text-slate-400">{fmtWhen(city.last_fact)}</td>
                      <td
                        className={ClassNames(
                          "py-1.5 text-right font-semibold",
                          tone === "fail"
                            ? "text-rose-300"
                            : tone === "warn"
                              ? "text-amber-300"
                              : "text-emerald-300"
                        )}
                      >
                        {fmtAge(age)}
                      </td>
                      <td className="py-1.5 text-right text-slate-300">
                        {fmtValue(city.facts_24h)}
                      </td>
                      <td className="py-1.5 text-right text-slate-300">
                        {fmtValue(city.owner_pct, "%")}
                      </td>
                      <td className="py-1.5 text-right">
                        <StatusPill
                          status={tone as HealthStatus}
                          label={tone === "ok" ? "Fresca" : tone === "warn" ? "Atrasada" : "Seca"}
                        />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          <h3 className="mt-4 mb-1 text-[11px] font-bold uppercase tracking-wide text-slate-500">
            Últimos runs
          </h3>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-[11px]">
              <thead className="text-slate-500">
                <tr>
                  <th className="pb-1">Run</th>
                  <th className="pb-1">Trigger</th>
                  <th className="pb-1">Início</th>
                  <th className="pb-1 text-right">Inseridos</th>
                  <th className="pb-1 text-right">Brutos</th>
                  <th className="pb-1 text-right">Estado</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((run) => (
                  <tr key={run.run_id} className="border-t border-white/5">
                    <td className="py-1 font-mono text-[10px] text-slate-400">
                      {String(run.run_id).slice(0, 8)}
                    </td>
                    <td className="py-1 text-slate-400">{run.trigger}</td>
                    <td className="py-1 text-slate-400">{fmtWhen(run.started_at)}</td>
                    <td className="py-1 text-right font-semibold text-slate-200">
                      {fmtValue(run.inserted)}
                    </td>
                    <td className="py-1 text-right text-slate-400">
                      {fmtValue(run.total_raw)}
                    </td>
                    <td className="py-1 text-right">
                      <span
                        className={ClassNames(
                          "font-semibold",
                          run.status === "success"
                            ? "text-emerald-300"
                            : run.status === "partial"
                              ? "text-amber-300"
                              : "text-rose-300"
                        )}
                      >
                        {run.status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>

        {/* Cotas */}
        <Section
          title="Cotas & custos"
          icon={<Activity className="h-4 w-4 text-indigo-400" />}
          hint="Brave (descoberta) e Searchbug (telefone)"
        >
          <div className="rounded-xl border border-white/5 bg-white/[0.02] p-3">
            <div className="flex items-center justify-between text-xs">
              <span className="font-semibold text-slate-300">Brave Search</span>
              <span
                className={ClassNames(
                  "font-bold",
                  brave.blocked ? "text-rose-300" : "text-emerald-300"
                )}
              >
                {fmtValue(brave.used)} / {fmtValue(brave.limit)}
              </span>
            </div>
            <div className="mt-2">
              <div className="h-2 w-full overflow-hidden rounded-full bg-white/10">
                <div
                  className={ClassNames(
                    "h-full rounded-full",
                    brave.blocked ? "bg-rose-400" : "bg-emerald-400"
                  )}
                  style={{
                    width: `${
                      brave.limit
                        ? Math.min(100, Math.round((Number(brave.used) / Number(brave.limit)) * 100))
                        : 0
                    }%`,
                  }}
                />
              </div>
            </div>
            <p className="mt-1 text-[10px] text-slate-500">
              {brave.blocked
                ? "Orçamento esgotado: descoberta de domínios adiada até amanhã."
                : `Quota de domínio por cidade: ${fmtValue(brave.domain_limit)}/dia.`}
            </p>
          </div>

          <div className="mt-3 grid grid-cols-2 gap-2">
            <div className="rounded-xl border border-white/5 bg-white/[0.02] p-3">
              <p className="text-[10px] uppercase tracking-wide text-slate-500">Searchbug 24h</p>
              <p className="mt-1 text-lg font-bold text-slate-100">
                ${Number(searchbug.cost_24h || 0).toFixed(2)}
              </p>
              <p className="text-[10px] text-slate-500">
                {fmtValue(searchbug.calls_24h)} chamadas · {fmtValue(searchbug.billed)} pagas
              </p>
            </div>
            <div className="rounded-xl border border-white/5 bg-white/[0.02] p-3">
              <p className="text-[10px] uppercase tracking-wide text-slate-500">Qualidade</p>
              <p className="mt-1 text-lg font-bold text-slate-100">
                {searchbug.billed
                  ? `${Math.round((Number(searchbug.ghost || 0) * 100) / Number(searchbug.billed))}%`
                  : "—"}
              </p>
              <p className="text-[10px] text-slate-500">pagas sem telefone</p>
            </div>
          </div>

          <h3 className="mt-4 mb-1 text-[11px] font-bold uppercase tracking-wide text-slate-500">
            Backlog de enriquecimento
          </h3>
          <div className="space-y-1.5">
            {Object.entries(byCity).map(([city, counts]) => {
              const newCount = Number(counts.new || 0);
              const ready = Number(counts.ready || 0);
              const quarantine = Number(counts.quarantined || 0);
              return (
                <div key={city} className="flex items-center gap-2 text-[11px]">
                  <span className="w-16 font-semibold text-slate-300">{city}</span>
                  <div className="flex h-2 flex-1 overflow-hidden rounded-full bg-white/5">
                    <div className="bg-indigo-400" style={{ width: `${newCount}%` }} />
                    <div className="bg-emerald-400" style={{ width: `${ready}%` }} />
                    <div className="bg-rose-400/70" style={{ width: `${quarantine}%` }} />
                  </div>
                  <span className="w-24 text-right text-slate-400">
                    {ready} prontos · {newCount} novos
                  </span>
                </div>
              );
            })}
          </div>
          <p className="mt-2 text-[10px] text-slate-500">
            Owner backfill hoje:{" "}
            {ownerBackfill.length
              ? ownerBackfill
                  .map((row) => `${String(row.city).toLowerCase()} ${row.jobs_today ?? 0}`)
                  .join(" · ")
              : "sem execuções"}
          </p>
        </Section>

        {/* Outreach */}
        <Section
          title="Outreach"
          icon={<Send className="h-4 w-4 text-indigo-400" />}
          hint="Fila, caixas e entregabilidade"
        >
          {blocker ? (
            <div className="mb-3 rounded-lg border border-amber-500/20 bg-amber-500/10 p-2 text-[11px] text-amber-200">
              <span className="font-bold">Fila bloqueada: </span>
              {blocker.detail || blocker.reason}
              {blocker.retry_at ? ` · retoma ${fmtWhen(blocker.retry_at)}` : ""}
            </div>
          ) : null}
          <div className="overflow-x-auto">
            <table className="w-full text-left text-[11px]">
              <thead className="text-slate-500">
                <tr>
                  <th className="pb-1">Caixa</th>
                  <th className="pb-1 text-right">Hoje</th>
                  <th className="pb-1 text-right">Warm-up</th>
                  <th className="pb-1 text-right">48h OK/Falha</th>
                  <th className="pb-1">Estado</th>
                </tr>
              </thead>
              <tbody>
                {mailboxRows.map((row) => (
                  <tr key={row.id} className="border-t border-white/5">
                    <td className="py-1.5">
                      <div className="font-semibold text-slate-200">{row.email}</div>
                      <div className="text-[10px] text-slate-500">{row.city || "—"}</div>
                    </td>
                    <td className="py-1.5 text-right text-slate-300">
                      {fmtValue(row.sent_today)} / {fmtValue(row.effective_cap)}
                    </td>
                    <td className="py-1.5 text-right text-slate-400">
                      {fmtValue(row.warmup_days)}d
                    </td>
                    <td className="py-1.5 text-right text-slate-300">
                      {fmtValue(row.sent_48h)} / {fmtValue(row.failed_48h)}
                    </td>
                    <td className="py-1.5">
                      {row.paused_at || row.paused_reason ? (
                        <span className="font-semibold text-rose-300">
                          {row.paused_reason || "pausada"}
                        </span>
                      ) : Number(row.enabled) === 0 ? (
                        <span className="font-semibold text-slate-400">desligada</span>
                      ) : (
                        <span className="font-semibold text-emerald-300">ativa</span>
                      )}
                      {row.last_error ? (
                        <div className="max-w-[220px] truncate text-[10px] text-rose-300/80">
                          {row.last_error}
                        </div>
                      ) : null}
                    </td>
                  </tr>
                ))}
                {!mailboxRows.length ? (
                  <tr>
                    <td colSpan={5} className="py-3 text-center text-slate-500">
                      Sem caixas configuradas.
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
          <div className="mt-3 grid grid-cols-3 gap-2 text-center">
            <div className="rounded-lg border border-white/5 bg-white/[0.02] p-2">
              <p className="text-[10px] text-slate-500">Enviados hoje</p>
              <p className="text-sm font-bold text-slate-100">
                {fmtValue(outreach.metrics.find((m) => m.key === "sent_today")?.value)}
              </p>
            </div>
            <div className="rounded-lg border border-white/5 bg-white/[0.02] p-2">
              <p className="text-[10px] text-slate-500">Bounce 30d</p>
              <p className="text-sm font-bold text-slate-100">
                {fmtValue(outreach.metrics.find((m) => m.key === "bounce_rate")?.value, "%")}
              </p>
            </div>
            <div className="rounded-lg border border-white/5 bg-white/[0.02] p-2">
              <p className="text-[10px] text-slate-500">Complaint 30d</p>
              <p className="text-sm font-bold text-slate-100">
                {fmtValue(outreach.metrics.find((m) => m.key === "complaint_rate")?.value, "%")}
              </p>
            </div>
          </div>
        </Section>

        {/* Push */}
        <Section
          title="Web Push"
          icon={<Wifi className="h-4 w-4 text-indigo-400" />}
          hint="Entregas nas últimas 24h e subscrições"
        >
          <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
            {[
              ["Aceites", pushDetail.accepted, "text-emerald-300"],
              ["Expiradas", pushDetail.expired, "text-amber-300"],
              ["Mortas", pushDetail.rejected_dead, "text-rose-300"],
              ["Sem VAPID", pushDetail.not_configured, "text-rose-300"],
            ].map(([label, value, tone]) => (
              <div key={String(label)} className="rounded-lg border border-white/5 bg-white/[0.02] p-2">
                <p className="text-[10px] text-slate-500">{label}</p>
                <p className={ClassNames("text-lg font-bold", String(tone))}>
                  {fmtValue(value as number)}
                </p>
              </div>
            ))}
          </div>
          <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-[11px] text-slate-400">
            <span>
              <Users className="mr-1 inline h-3.5 w-3.5" />
              {fmtValue(pushDetail.active_subs)} ativos / {fmtValue(pushDetail.total_subs)} totais
            </span>
            <span>
              <Sparkles className="mr-1 inline h-3.5 w-3.5" />
              {fmtValue(pushDetail.clicks)} cliques
            </span>
            <span>Última entrega: {fmtWhen(pushDetail.last_accepted)}</span>
          </div>
        </Section>

        {/* Infra */}
        <Section
          title="Infra & Control Tower"
          icon={<HardDrive className="h-4 w-4 text-indigo-400" />}
          hint="Worker, backup, disco, tokens"
        >
          <div className="space-y-1.5">
            {checks.map((check) => {
              const name = check.check_name || check.name;
              return (
                <div
                  key={`${name}-${check.checked_at || ""}`}
                  className="flex items-center justify-between gap-3 border-b border-white/5 pb-1.5 text-[11px] last:border-0"
                >
                  <span className="font-mono text-[10px] text-slate-400">{name}</span>
                  <span className="flex-1 truncate text-right text-slate-500">
                    {check.detail}
                  </span>
                  <StatusPill
                    status={
                      (check.status === "ok"
                        ? "ok"
                        : check.status === "warn"
                          ? "warn"
                          : "fail") as HealthStatus
                    }
                    label={String(check.status)}
                  />
                </div>
              );
            })}
            {!checks.length ? (
              <p className="text-[11px] text-slate-500">
                Sem snapshot da Control Tower (recolha a cada 15 min).
              </p>
            ) : null}
          </div>
        </Section>

        {/* Alertas */}
        <Section
          title="Alertas abertos"
          icon={<AlertTriangle className="h-4 w-4 text-amber-400" />}
          hint={`${alertItems.length} código(s) aberto(s) · reconhecer aqui`}
        >
          {ackError ? (
            <p className="mb-2 rounded-lg border border-rose-500/20 bg-rose-500/10 p-2 text-[11px] text-rose-200">
              {ackError}
            </p>
          ) : null}
          <div className="space-y-2">
            {alertItems.map((alert) => (
              <div
                key={alert.id}
                className="rounded-lg border border-white/5 bg-white/[0.02] p-2"
              >
                <div className="flex items-center justify-between gap-2">
                  <span
                    className={ClassNames(
                      "text-[10px] font-bold uppercase",
                      alert.informational
                        ? "text-slate-400"
                        : String(alert.level).toLowerCase().includes("crit")
                          ? "text-rose-300"
                          : "text-amber-300"
                    )}
                  >
                    {alert.informational ? "auditoria" : alert.level}
                  </span>
                  {Number(alert.occurrences || 1) > 1 ? (
                    <span className="rounded-full border border-white/10 bg-white/[0.04] px-1.5 py-0.5 text-[9px] font-bold text-slate-400">
                      {alert.occurrences}×
                    </span>
                  ) : null}
                  <div className="flex items-center gap-2">
                    <span className="text-[10px] text-slate-500">
                      {fmtWhen(alert.created_at)}
                    </span>
                    <button
                      type="button"
                      onClick={() => void handleAck(Number(alert.id))}
                      disabled={ackingId === Number(alert.id)}
                      className="inline-flex items-center gap-1 rounded-md border border-white/10 px-2 py-0.5 text-[10px] font-semibold text-slate-300 hover:border-emerald-400/40 hover:bg-emerald-500/10 hover:text-emerald-200 disabled:opacity-50"
                    >
                      {ackingId === Number(alert.id) ? (
                        <Loader2 className="h-3 w-3 animate-spin" />
                      ) : (
                        <CheckCircle2 className="h-3 w-3" />
                      )}
                      Reconhecer
                    </button>
                  </div>
                </div>
                <p className="mt-1 font-mono text-[10px] text-slate-400">{alert.code}</p>
                <p className="text-[11px] text-slate-300">{alert.message}</p>
                {Number(alert.occurrences || 1) > 1 && alert.first_seen ? (
                  <p className="mt-1 text-[9px] text-slate-600">
                    primeira ocorrência {fmtWhen(alert.first_seen)}
                  </p>
                ) : null}
                {alert.informational ? (
                  <p className="mt-1 text-[10px] text-slate-500">
                    Registo de auditoria — não afeta o score operacional.
                  </p>
                ) : null}
              </div>
            ))}
            {!alertItems.length ? (
              <p className="text-[11px] font-semibold text-emerald-300">
                Sem alertas abertos.
              </p>
            ) : null}
          </div>
        </Section>
      </div>

      <footer className="mt-6 flex flex-wrap items-center gap-3 text-[10px] text-slate-600">
        <Mail className="h-3 w-3" />
        <span>Operação read-only · única escrita: reconhecer alertas.</span>
        <span>·</span>
        <span>Snapshot: 1/15 min, retenção 30 dias.</span>
        <span>·</span>
        <span>Cache API: 30 s.</span>
      </footer>
    </main>
  );
}

"use client";

import useSWR from "swr";
import {
  Activity,
  AlertTriangle,
  ArrowUpRight,
  CheckCircle2,
  Clock3,
  Database,
  GitBranch,
  HeartPulse,
  Layers,
  MapPin,
  RefreshCcw,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { fetchAdminDataPlane } from "@/lib/admin-api";
import { formatScore } from "@/lib/score";
import {
  EmptyState,
  MetricCard,
  ScoreHistogram,
  SectionHeader,
  StatusPill,
  Surface,
  cn,
} from "@/components/admin/ui";

function fmtDt(value?: string | null) {
  if (!value) return "—";
  const normalized = value.includes("T") ? value : value.replace(" ", "T");
  const hasTz = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(normalized);
  const date = new Date(hasTz ? normalized : `${normalized}Z`);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("pt-PT", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function ago(hours: number | null | undefined) {
  if (hours === null || hours === undefined) return "sem registo";
  if (hours < 1) return `${Math.round(hours * 60)} min`;
  if (hours < 48) return `${hours.toFixed(1)} h`;
  return `${Math.round(hours / 24)} d`;
}

function statusTone(status: string) {
  const value = status.toLowerCase();
  if (["success", "ok", "done", "active", "quarantined"].includes(value)) return "ok" as const;
  if (["partial", "warn", "pending", "dry_run", "no_bbl"].includes(value)) return "warn" as const;
  if (["failed", "error", "fail", "miss"].includes(value)) return "fail" as const;
  return "neutral" as const;
}

function pct(value: number, total: number) {
  if (!total) return 0;
  return Math.round((value / total) * 1000) / 10;
}

export default function DataPlanePage() {
  const { data, error, isLoading, isValidating, mutate } = useSWR(
    "admin-data-plane",
    fetchAdminDataPlane,
    { refreshInterval: 30_000, revalidateOnFocus: true }
  );

  const ingestion = data?.ingestion;
  const quarantine = data?.quarantine;
  const freshness = data?.freshness;
  const score = data?.score;

  const ingestsTotal = (ingestion?.by_status ?? []).reduce(
    (sum, row) => sum + row.n,
    0
  );
  const ingestsOk =
    ingestion?.by_status.find((row) => row.status === "success")?.n ?? 0;
  const ingestsBad = (ingestion?.by_status ?? [])
    .filter((row) => row.status !== "success")
    .reduce((sum, row) => sum + row.n, 0);
  const scoreAvg = score?.avg ?? 0;
  const lastFreshness = freshness?.last_run;
  const geocodeDone =
    freshness?.geocode.find((row) => row.status === "done")?.n ?? 0;
  const geocodeTotal = freshness?.geocode_total ?? 0;

  return (
    <main className="mx-auto max-w-[1600px] space-y-6 px-4 py-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <StatusPill state="info" pulse>
              read-only
            </StatusPill>
            <span className="text-[10px] font-semibold uppercase tracking-[0.2em] text-slate-600">
              Fase 1 · auto-cura
            </span>
          </div>
          <h1 className="text-3xl font-black tracking-tight text-white">
            Data Plane
          </h1>
          <p className="mt-1 max-w-3xl text-sm leading-relaxed text-slate-400">
            Ingestão, quarentena, frescura e scoring num só lugar. Todos os
            indicadores são lidos diretamente das tabelas de auditoria.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-slate-600">
            atualizado {fmtDt(data?.generated_at)}
          </span>
          <button
            type="button"
            onClick={() => void mutate()}
            disabled={isValidating}
            className="inline-flex items-center gap-2 rounded-xl border border-white/10 bg-white/[0.03] px-3 py-2 text-[11px] font-bold text-slate-300 transition hover:border-emerald-400/30 hover:text-emerald-200 disabled:opacity-50"
          >
            <RefreshCcw className={cn("h-3.5 w-3.5", isValidating && "animate-spin")} />
            Atualizar
          </button>
        </div>
      </header>

      {error ? (
        <Surface className="border-rose-400/20 p-5">
          <p className="text-sm font-semibold text-rose-200">
            Não foi possível carregar o Data Plane.
          </p>
          <p className="mt-1 text-xs text-slate-400">
            {error instanceof Error ? error.message : "Erro desconhecido."}
          </p>
        </Surface>
      ) : null}

      {isLoading && !data ? (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {[0, 1, 2, 3].map((index) => (
            <div
              key={index}
              className="h-32 animate-pulse rounded-2xl border border-white/[0.06] bg-white/[0.03]"
            />
          ))}
        </div>
      ) : null}

      {/* top metrics */}
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard
          label="Ingestões registadas"
          value={data ? ingestsTotal : "—"}
          sub={
            ingestsBad
              ? `${ingestsBad} falha(s) · ${ingestsOk} sucesso(s)`
              : `${ingestsOk} sucesso(s) · 0 falhas`
          }
          icon={<Database className="h-4 w-4" />}
          tone={ingestsBad ? "amber" : "emerald"}
          footer={
            <div className="flex items-center gap-2 text-[10px] text-slate-500">
              <StatusPill state={ingestsBad ? "warn" : "ok"}>
                {ingestsBad ? "com falhas" : "limpo"}
              </StatusPill>
              <span>{ingestion?.coverage_note?.split(".")[0]}</span>
            </div>
          }
        />
        <MetricCard
          label="Placeholders isolados"
          value={quarantine?.active_count ?? "—"}
          sub={
            quarantine
              ? `${quarantine.other_quarantined.toLocaleString("pt-PT")} outras entidades em quarentena de enriquecimento`
              : "a carregar…"
          }
          icon={<ShieldCheck className="h-4 w-4" />}
          tone="violet"
          footer={
            <div className="flex items-center gap-2 text-[10px] text-slate-500">
              <StatusPill state={quarantine?.active_count ? "warn" : "ok"}>
                {quarantine?.active_count ? "revisão ativa" : "sem placeholders"}
              </StatusPill>
              <span>{quarantine?.findings_total ?? 0} findings auditados</span>
            </div>
          }
        />
        <MetricCard
          label="Frescura HPD/DOB"
          value={lastFreshness ? ago(freshness?.last_age_hours) : "—"}
          sub={
            lastFreshness
              ? `${lastFreshness.hpd_checked.toLocaleString("pt-PT")} HPD · ${lastFreshness.dob_checked.toLocaleString("pt-PT")} DOB`
              : "sem runs de frescura"
          }
          icon={<HeartPulse className="h-4 w-4" />}
          tone={lastFreshness?.status === "ok" ? "emerald" : "amber"}
          footer={
            <div className="flex items-center gap-2 text-[10px] text-slate-500">
              <StatusPill state={lastFreshness?.status === "ok" ? "ok" : "warn"}>
                {lastFreshness?.status ?? "sem dados"}
              </StatusPill>
              <span>
                {(freshness?.by_status ?? []).reduce((sum, row) => sum + row.n, 0)} runs no histórico
              </span>
            </div>
          }
        />
        <MetricCard
          label="Scoring V2"
          value={score ? formatScore(scoreAvg) : "—"}
          sub={
            score
              ? `média · ${score.total.toLocaleString("pt-PT")} prospects · ${score.distinct_scores} valores`
              : "a carregar…"
          }
          icon={<Sparkles className="h-4 w-4" />}
          tone="sky"
          footer={
            <div className="flex items-center gap-2 text-[10px] text-slate-500">
              <StatusPill state="info">
                {score ? `${score.min}–${score.max}` : "0–63"}
              </StatusPill>
              <span>{score?.snapshots.toLocaleString("pt-PT") ?? 0} snapshots</span>
            </div>
          }
        />
      </div>

      {/* score */}
      <Surface className="p-5">
        <SectionHeader
          eyebrow="Scoring V2"
          title="Distribuição real dos prospects"
          description="A régua foi corrigida para 0–63. As barras mostram a concentração por faixa e o detalhe do prospect passa a expor os componentes do snapshot."
          icon={<Layers className="h-5 w-5" />}
          action={
            score?.last_run ? (
              <StatusPill state={score.last_run.status === "success" ? "ok" : "warn"}>
                {score.last_run.version} · {score.last_run.status}
              </StatusPill>
            ) : null
          }
        />
        <div className="mt-5 grid gap-5 lg:grid-cols-[1.3fr_0.7fr]">
          <div className="rounded-2xl border border-white/[0.06] bg-white/[0.02] p-4">
            <ScoreHistogram buckets={score?.buckets ?? []} total={score?.total ?? 0} />
          </div>
          <div className="grid grid-cols-2 gap-2">
            {[
              { label: "Mínimo", value: score ? formatScore(score.min) : "—" },
              { label: "Máximo", value: score ? formatScore(score.max) : "—" },
              { label: "Média", value: score ? formatScore(score.avg) : "—" },
              { label: "Distintos", value: score?.distinct_scores ?? "—" },
            ].map((item) => (
              <div
                key={item.label}
                className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-3"
              >
                <p className="text-[9px] font-bold uppercase tracking-[0.16em] text-slate-600">
                  {item.label}
                </p>
                <p className="mt-1 text-lg font-black text-white">{item.value}</p>
              </div>
            ))}
            <div className="col-span-2 rounded-xl border border-white/[0.06] bg-white/[0.02] p-3">
              <p className="text-[9px] font-bold uppercase tracking-[0.16em] text-slate-600">
                Snapshot
              </p>
              <p className="mt-1 text-[11px] text-slate-300">
                {score?.snapshots.toLocaleString("pt-PT") ?? 0} prospects com
                componentes explicáveis ·{" "}
                <span className={score?.snapshots_without_components ? "text-amber-300" : "text-emerald-300"}>
                  {score?.snapshots_without_components ?? 0} sem componentes
                </span>
              </p>
              {score?.last_run ? (
                <p className="mt-1 text-[10px] text-slate-500">
                  último run {fmtDt(score.last_run.finished_at)} ·{" "}
                  {score.last_run.processed.toLocaleString("pt-PT")} processados
                </p>
              ) : null}
            </div>
          </div>
        </div>
      </Surface>

      {/* ingestion */}
      <Surface className="p-5">
        <SectionHeader
          eyebrow="Ingestão"
          title="Runs, falhas e retries"
          description="`ingestion_runs` cobre os conectores de licenças. Socrata/HPD/DOB violations continuam agregados em `scraper_runs`, visíveis ao lado para não perder o contexto."
          icon={<GitBranch className="h-5 w-5" />}
          action={
            <div className="flex flex-wrap gap-1.5">
              {(ingestion?.by_status ?? []).length ? (
                ingestion?.by_status.map((row) => (
                  <StatusPill key={row.status} state={statusTone(row.status)}>
                    {row.status} · {row.n}
                  </StatusPill>
                ))
              ) : (
                <StatusPill state="neutral">sem runs</StatusPill>
              )}
            </div>
          }
        />
        <div className="mt-5 grid gap-4 xl:grid-cols-2">
          <div className="rounded-2xl border border-white/[0.06] bg-white/[0.02]">
            <div className="flex items-center justify-between border-b border-white/[0.05] px-4 py-3">
              <h3 className="text-xs font-bold uppercase tracking-[0.14em] text-slate-400">
                ingestion_runs
              </h3>
              <span className="text-[10px] text-slate-600">
                {ingestion?.runs.length ?? 0} registos
              </span>
            </div>
            <div className="max-h-[360px] overflow-auto">
              {ingestion?.runs.length ? (
                <table className="w-full text-left text-[11px]">
                  <thead className="sticky top-0 bg-[#0e1118] text-[9px] uppercase tracking-wider text-slate-600">
                    <tr>
                      <th className="px-4 py-2">Fonte</th>
                      <th className="px-2 py-2">Estado</th>
                      <th className="px-2 py-2 text-right">Linhas</th>
                      <th className="px-4 py-2 text-right">Quando</th>
                    </tr>
                  </thead>
                  <tbody>
                    {ingestion.runs.map((run) => (
                      <tr key={run.id} className="border-t border-white/[0.04]">
                        <td className="px-4 py-2.5">
                          <p className="font-mono text-[10px] text-slate-300">{run.source}</p>
                          {run.error_code ? (
                            <p className="text-[9px] text-rose-300">{run.error_code}</p>
                          ) : null}
                        </td>
                        <td className="px-2 py-2.5">
                          <StatusPill state={statusTone(run.status)}>{run.status}</StatusPill>
                        </td>
                        <td className="px-2 py-2.5 text-right tabular-nums text-slate-400">
                          {run.rows_upserted}/{run.rows_fetched}
                        </td>
                        <td className="px-4 py-2.5 text-right text-[10px] text-slate-500">
                          {fmtDt(run.started_at)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <div className="p-4">
                  <EmptyState
                    icon={<Database className="h-6 w-6" />}
                    title="Sem ingestion_runs"
                    description="Os conectores de licenças ainda não correram desde o último deploy."
                  />
                </div>
              )}
            </div>
          </div>

          <div className="rounded-2xl border border-white/[0.06] bg-white/[0.02]">
            <div className="flex items-center justify-between border-b border-white/[0.05] px-4 py-3">
              <h3 className="text-xs font-bold uppercase tracking-[0.14em] text-slate-400">
                scraper_runs
              </h3>
              <span className="text-[10px] text-slate-600">
                {ingestion?.scraper_runs.length ?? 0} registos
              </span>
            </div>
            <div className="max-h-[360px] overflow-auto">
              {ingestion?.scraper_runs.length ? (
                <table className="w-full text-left text-[11px]">
                  <thead className="sticky top-0 bg-[#0e1118] text-[9px] uppercase tracking-wider text-slate-600">
                    <tr>
                      <th className="px-4 py-2">Run</th>
                      <th className="px-2 py-2">Estado</th>
                      <th className="px-2 py-2 text-right">Inseridos</th>
                      <th className="px-4 py-2 text-right">Cidades</th>
                    </tr>
                  </thead>
                  <tbody>
                    {ingestion.scraper_runs.map((run) => (
                      <tr key={run.run_id} className="border-t border-white/[0.04]">
                        <td className="px-4 py-2.5">
                          <p className="font-mono text-[10px] text-slate-300">
                            {run.run_id.slice(0, 10)}
                          </p>
                          <p className="text-[9px] text-slate-600">
                            {run.trigger} · {fmtDt(run.started_at)}
                          </p>
                        </td>
                        <td className="px-2 py-2.5">
                          <StatusPill state={statusTone(run.status)}>{run.status}</StatusPill>
                        </td>
                        <td className="px-2 py-2.5 text-right tabular-nums text-slate-300">
                          {run.inserted.toLocaleString("pt-PT")}
                        </td>
                        <td className="px-4 py-2.5 text-right tabular-nums text-slate-500">
                          {run.cities_covered}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <div className="p-4">
                  <EmptyState title="Sem scraper_runs" />
                </div>
              )}
            </div>
          </div>
        </div>
        {ingestion?.failures.length ? (
          <div className="mt-3 rounded-xl border border-rose-400/15 bg-rose-500/[0.04] p-3">
            <p className="mb-2 flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wide text-rose-200">
              <AlertTriangle className="h-3.5 w-3.5" /> Falhas registadas
            </p>
            <div className="space-y-1">
              {ingestion.failures.slice(0, 5).map((failure) => (
                <p key={failure.id} className="text-[10px] text-slate-400">
                  <span className="font-mono text-rose-200">{failure.source}</span>{" "}
                  {failure.http_status ?? "—"} · {failure.error_class ?? "erro"} ·{" "}
                  {failure.retryable ? "retry" : "permanente"}
                </p>
              ))}
            </div>
          </div>
        ) : null}
      </Surface>

      {/* quarantine */}
      <Surface className="p-5">
        <SectionHeader
          eyebrow="Quarentena"
          title="Placeholders ativos"
          description="Os 9 placeholders de teste são a quarentena ativa de `entity_quarantine`. As restantes entidades em quarentena pertencem ao pipeline de enriquecimento e não se misturam com este número."
          icon={<ShieldCheck className="h-5 w-5" />}
          action={
            <StatusPill state={quarantine?.active_count ? "warn" : "ok"}>
              {quarantine?.active_count ?? 0} ativos
            </StatusPill>
          }
        />
        <div className="mt-5 grid gap-4 xl:grid-cols-[1.4fr_0.6fr]">
          <div className="grid gap-2 sm:grid-cols-2">
            {quarantine?.active.length ? (
              quarantine.active.map((entity) => (
                <div
                  key={entity.id}
                  className="rounded-2xl border border-amber-400/15 bg-amber-500/[0.04] p-3.5"
                >
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <p className="text-sm font-bold text-white">
                        {entity.legal_name ?? `Entidade ${entity.entity_id}`}
                      </p>
                      <p className="mt-0.5 font-mono text-[10px] text-amber-200/80">
                        {entity.license ?? "—"}
                      </p>
                    </div>
                    <StatusPill state="warn">{entity.reason}</StatusPill>
                  </div>
                  <div className="mt-2 flex flex-wrap items-center gap-2 text-[10px] text-slate-500">
                    <span className="inline-flex items-center gap-1">
                      <MapPin className="h-3 w-3" /> {entity.city ?? entity.state ?? "—"}
                    </span>
                    <span className="font-mono">{entity.phone ?? "sem telefone"}</span>
                    <span className="ml-auto">{fmtDt(entity.created_at)}</span>
                  </div>
                </div>
              ))
            ) : (
              <div className="sm:col-span-2">
                <EmptyState
                  icon={<CheckCircle2 className="h-6 w-6" />}
                  title="Nenhum placeholder ativo"
                  description="A quarentena está limpa."
                />
              </div>
            )}
          </div>
          <div className="space-y-2">
            <div className="rounded-2xl border border-white/[0.06] bg-white/[0.02] p-4">
              <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-slate-600">
                Fora dos placeholders
              </p>
              <p className="mt-2 text-2xl font-black text-white">
                {(quarantine?.other_quarantined ?? 0).toLocaleString("pt-PT")}
              </p>
              <p className="mt-1 text-[10px] leading-relaxed text-slate-500">
                entidades com `status=quarantined` no pipeline de enriquecimento.
                São um conceito diferente dos 9 placeholders.
              </p>
            </div>
            <div className="rounded-2xl border border-white/[0.06] bg-white/[0.02] p-4">
              <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-slate-600">
                Findings por regra
              </p>
              <div className="mt-2 space-y-1.5">
                {(quarantine?.findings_by_rule ?? []).slice(0, 8).map((finding) => (
                  <div
                    key={`${finding.rule_id}-${finding.severity}-${finding.status}`}
                    className="flex items-center justify-between gap-2 text-[10px]"
                  >
                    <span className="truncate text-slate-400">{finding.rule_id}</span>
                    <span className="flex items-center gap-1.5">
                      <span className="text-slate-600">{finding.status}</span>
                      <span
                        className={cn(
                          "rounded-full px-1.5 py-0.5 font-bold tabular-nums",
                          finding.severity === "critical"
                            ? "bg-rose-500/15 text-rose-200"
                            : finding.severity === "high"
                              ? "bg-amber-500/15 text-amber-200"
                              : "bg-white/5 text-slate-300"
                        )}
                      >
                        {finding.n}
                      </span>
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </Surface>

      {/* freshness + geocode */}
      <div className="grid gap-4 xl:grid-cols-2">
        <Surface className="p-5">
          <SectionHeader
            eyebrow="Frescura"
            title="Sincronização HPD/DOB"
            description="Runs de fecho e atualização de histórico. A tabela é atualizada pelo worker de frescura e não pelo scraper."
            icon={<Clock3 className="h-5 w-5" />}
            action={
              <StatusPill state={lastFreshness?.status === "ok" ? "ok" : "warn"}>
                {lastFreshness?.status ?? "sem dados"}
              </StatusPill>
            }
          />
          <div className="mt-4 grid grid-cols-3 gap-2">
            {[
              { label: "HPD", value: lastFreshness?.hpd_checked ?? 0 },
              { label: "DOB", value: lastFreshness?.dob_checked ?? 0 },
              { label: "Histórico", value: lastFreshness?.history_refreshed ?? 0 },
            ].map((item) => (
              <div
                key={item.label}
                className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-3"
              >
                <p className="text-[9px] font-bold uppercase tracking-[0.14em] text-slate-600">
                  {item.label}
                </p>
                <p className="mt-1 text-lg font-black text-white">
                  {item.value.toLocaleString("pt-PT")}
                </p>
              </div>
            ))}
          </div>
          <div className="mt-3 max-h-56 overflow-auto rounded-xl border border-white/[0.06]">
            <table className="w-full text-left text-[10px]">
              <thead className="sticky top-0 bg-[#0e1118] text-[9px] uppercase tracking-wider text-slate-600">
                <tr>
                  <th className="px-3 py-2">Run</th>
                  <th className="px-2 py-2">Estado</th>
                  <th className="px-2 py-2 text-right">HPD</th>
                  <th className="px-3 py-2 text-right">DOB</th>
                </tr>
              </thead>
              <tbody>
                {(freshness?.runs ?? []).map((run) => (
                  <tr key={run.id} className="border-t border-white/[0.04]">
                    <td className="px-3 py-2 text-slate-400">{fmtDt(run.finished_at)}</td>
                    <td className="px-2 py-2">
                      <StatusPill state={statusTone(run.status)}>{run.status}</StatusPill>
                    </td>
                    <td className="px-2 py-2 text-right tabular-nums text-slate-400">
                      {run.hpd_checked.toLocaleString("pt-PT")}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums text-slate-400">
                      {run.dob_checked.toLocaleString("pt-PT")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Surface>

        <Surface className="p-5">
          <SectionHeader
            eyebrow="Geocoding"
            title="Fila de coordenadas"
            description="Sem BBL não há coordenada inventada. A fila processa BBL → PLUTO e mantém retry para os misses."
            icon={<MapPin className="h-5 w-5" />}
            action={
              <StatusPill state={geocodeTotal ? "info" : "ok"}>
                {geocodeTotal.toLocaleString("pt-PT")} jobs
              </StatusPill>
            }
          />
          <div className="mt-4 space-y-3">
            <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-3">
              <div className="flex items-center justify-between text-[10px] text-slate-500">
                <span>resolvidos</span>
                <span className="tabular-nums text-emerald-300">
                  {geocodeDone.toLocaleString("pt-PT")} / {geocodeTotal.toLocaleString("pt-PT")}
                </span>
              </div>
              <div className="mt-2 h-2 overflow-hidden rounded-full bg-white/[0.06]">
                <div
                  className="h-full rounded-full bg-gradient-to-r from-emerald-400 to-teal-300"
                  style={{ width: `${pct(geocodeDone, geocodeTotal)}%` }}
                />
              </div>
            </div>
            <div className="grid grid-cols-3 gap-2">
              {(freshness?.geocode ?? []).map((row) => (
                <div
                  key={row.status}
                  className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-3"
                >
                  <p className="text-[9px] font-bold uppercase tracking-[0.12em] text-slate-600">
                    {row.status}
                  </p>
                  <p className="mt-1 text-base font-black text-white">
                    {row.n.toLocaleString("pt-PT")}
                  </p>
                </div>
              ))}
            </div>
            <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-3">
              <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-slate-600">
                Remediações
              </p>
              <p className="mt-1 text-[11px] text-slate-400">
                {freshness?.health_remediations_implemented
                  ? `${freshness.health_remediations_count} remediações registadas`
                  : "Tabela pronta, ainda sem remediações implementadas no data plane."}
              </p>
            </div>
          </div>
        </Surface>
      </div>

      <div className="flex flex-wrap items-center gap-3 rounded-2xl border border-white/[0.06] bg-white/[0.02] px-4 py-3 text-[10px] text-slate-500">
        <Activity className="h-3.5 w-3.5 text-emerald-400" />
        <span>
          Leitura direta de `ingestion_runs`, `entity_quarantine`,
          `data_quality_findings`, `freshness_runs`, `geocode_jobs` e
          `score_snapshots`.
        </span>
        <a
          href="/admin/system-health"
          className="ml-auto inline-flex items-center gap-1 font-bold text-emerald-300 hover:text-emerald-200"
        >
          System Health <ArrowUpRight className="h-3 w-3" />
        </a>
      </div>
    </main>
  );
}

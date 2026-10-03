"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Activity,
  AlertTriangle,
  Ban,
  BellRing,
  CheckCircle2,
  Database,
  Loader2,
  RefreshCcw,
  Search,
  Users,
  Wallet,
} from "lucide-react";

import {
  AdminAlert,
  AdminApiError,
  AdminOverview,
  AdminPushMetrics,
  AdminReveal,
  AdminScraperRun,
  AdminSearchbugMetrics,
  AdminSources,
  fetchAdminAlerts,
  fetchAdminOverview,
  fetchAdminPush,
  fetchAdminReveals,
  fetchAdminScraperRuns,
  fetchAdminSearchbug,
  fetchAdminSources,
} from "@/lib/admin-api";

type Gate = "loading" | "unauthenticated" | "forbidden" | "ok" | "error";

// --------------------------------------------------------------- UI bits

function Card({
  title,
  icon,
  children,
  hint,
}: {
  title: string;
  icon: React.ReactNode;
  children: React.ReactNode;
  hint?: string;
}) {
  return (
    <section className="rounded-2xl border border-white/10 bg-[#10131a]">
      <header className="flex items-center gap-2 border-b border-white/10 px-4 py-3">
        <span className="text-indigo-400">{icon}</span>
        <h2 className="text-sm font-bold text-slate-200">{title}</h2>
        {hint ? <span className="ml-auto text-[11px] text-slate-500">{hint}</span> : null}
      </header>
      <div className="p-4">{children}</div>
    </section>
  );
}

function Kpi({ label, value, sub }: { label: string; value: React.ReactNode; sub?: string }) {
  return (
    <div className="rounded-xl border border-white/10 bg-white/[0.02] px-3 py-2">
      <div className="text-[10px] uppercase tracking-wider text-slate-500">{label}</div>
      <div className="text-xl font-bold text-slate-100">{value}</div>
      {sub ? <div className="text-[11px] text-slate-500">{sub}</div> : null}
    </div>
  );
}

function StateBadge({ ok, bad }: { ok: boolean; bad: string }) {
  return ok ? (
    <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/15 px-2 py-0.5 text-[11px] font-semibold text-emerald-400">
      <CheckCircle2 className="h-3 w-3" /> Saudável
    </span>
  ) : (
    <span className="inline-flex items-center gap-1 rounded-full bg-amber-500/15 px-2 py-0.5 text-[11px] font-semibold text-amber-400">
      <AlertTriangle className="h-3 w-3" /> {bad}
    </span>
  );
}

function fmtDt(value?: string | null) {
  if (!value) return "—";
  const d = new Date(value.includes("T") ? value : value.replace(" ", "T"));
  if (isNaN(d.getTime())) return value;
  return d.toLocaleString("pt-PT", { dateStyle: "short", timeStyle: "short" });
}

// --------------------------------------------------------------- gate

function GateScreen({ gate }: { gate: Gate }) {
  if (gate === "loading") {
    return (
      <div className="flex min-h-screen items-center justify-center gap-3 text-slate-400">
        <Loader2 className="h-5 w-5 animate-spin" /> A validar sessão de administrador…
      </div>
    );
  }

  const isAuthIssue = gate === "unauthenticated" || gate === "forbidden";
  return (
    <div className="flex min-h-screen items-center justify-center p-6">
      <div className="max-w-md rounded-2xl border border-white/10 bg-[#10131a] p-6 text-center">
        <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-rose-500/15">
          <Ban className="h-6 w-6 text-rose-400" />
        </div>
        <h1 className="text-lg font-bold text-slate-100">Acesso restrito</h1>
        <p className="mt-2 text-sm text-slate-400">
          {gate === "unauthenticated"
            ? "Sessão inexistente ou expirada. Inicia sessão com uma conta de administrador."
            : gate === "forbidden"
              ? "A tua sessão é válida mas a conta não tem o perfil de administrador."
              : "Não foi possível falar com a API. Verifica se o backend está de pé."}
        </p>
        <a
          href="/"
          className="mt-4 inline-block rounded-lg bg-indigo-500 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-400"
        >
          Voltar ao início
        </a>
      </div>
    </div>
  );
}

// --------------------------------------------------------------- página

export default function AdminPage() {
  const [gate, setGate] = useState<Gate>("loading");
  const [overview, setOverview] = useState<AdminOverview | null>(null);
  const [sources, setSources] = useState<AdminSources | null>(null);
  const [runs, setRuns] = useState<AdminScraperRun[]>([]);
  const [reveals, setReveals] = useState<AdminReveal[]>([]);
  const [alerts, setAlerts] = useState<AdminAlert[]>([]);
  const [searchbug, setSearchbug] = useState<AdminSearchbugMetrics | null>(null);
  const [push, setPush] = useState<AdminPushMetrics | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setBusy(true);
    try {
      // searchbug falha isoladamente: a telemetria é secundária e não deve
      // apagar o resto do painel.
      const sb = fetchAdminSearchbug(7, 25).catch(() => null);
      const pu = fetchAdminPush(7, 25).catch(() => null);
      const [ov, src, rn, rv, al, sbm, pum] = await Promise.all([
        fetchAdminOverview(),
        fetchAdminSources(),
        fetchAdminScraperRuns(15),
        fetchAdminReveals(50, true),
        fetchAdminAlerts(20),
        sb,
        pu,
      ]);
      setOverview(ov);
      setSources(src);
      setRuns(rn.runs);
      setReveals(rv.reveals);
      setAlerts(al.alerts);
      setSearchbug(sbm);
      setPush(pum);
      setGate("ok");
    } catch (e) {
      if (e instanceof AdminApiError) {
        if (e.status === 401) return setGate("unauthenticated");
        if (e.status === 403) return setGate("forbidden");
      }
      setGate("error");
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (gate !== "ok") return <GateScreen gate={gate} />;

  const health = sources?.city_health ?? {};
  const cities = Object.entries(health);
  const unhealthy = cities.filter(([, v]) => (v.failure_count ?? 0) > 0 || v.circuit_open_until);
  const lastRun = overview?.last_scraper_run ?? null;

  return (
    <div className="mx-auto max-w-7xl space-y-5 p-5">
      <header className="flex flex-wrap items-center gap-3">
        <div>
          <h1 className="text-xl font-bold text-slate-100">Torre de Controlo · Magic Leads</h1>
          <p className="text-xs text-slate-500">
            Painel interno. Gerado em {fmtDt(overview?.generated_at)} (UTC).
          </p>
        </div>
        <button
          onClick={() => void load()}
          disabled={busy}
          className="ml-auto inline-flex items-center gap-2 rounded-lg border border-white/10 px-3 py-2 text-xs font-semibold text-slate-300 hover:bg-white/5 disabled:opacity-50"
        >
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCcw className="h-4 w-4" />}
          Atualizar
        </button>
      </header>

      {/* ---------------------------------------------------------- topo */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Kpi label="Leads (total)" value={overview?.leads.total ?? "—"} sub={`${overview?.leads.today ?? 0} hoje`} />
        <Kpi label="Utilizadores" value={overview?.users.total ?? "—"} sub={`${overview?.users.today ?? 0} hoje`} />
        <Kpi
          label="Revelos hoje"
          value={overview?.reveals.today ?? "—"}
          sub={`${overview?.reveals.active ?? 0} ainda ativos`}
        />
        <Kpi
          label="Créditos usados"
          value={overview?.credits.used_today ?? "—"}
          sub={`${overview?.credits.refunded_today ?? 0} estornados`}
        />
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        {/* -------------------------------------------------- fontes */}
        <Card title="Saúde das fontes de dados" icon={<Database className="h-4 w-4" />}>
          <div className="mb-3 flex flex-wrap items-center gap-3 text-xs">
            <StateBadge ok={unhealthy.length === 0} bad={`${unhealthy.length} cidade(s) com falha`} />
            <span className="text-slate-500">
              Último run: <span className="text-slate-300">{fmtDt(lastRun?.finished_at)}</span>
              {lastRun?.inserted != null ? ` · ${lastRun.inserted} leads inseridos` : ""}
            </span>
          </div>
          {cities.length === 0 ? (
            <p className="text-xs text-slate-500">Sem registos em city_health ainda.</p>
          ) : (
            <table className="w-full text-left text-xs">
              <thead className="text-[10px] uppercase tracking-wider text-slate-500">
                <tr>
                  <th className="py-1">Cidade</th>
                  <th className="py-1">Falhas</th>
                  <th className="py-1">Circuit</th>
                  <th className="py-1">Último sucesso</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {cities.map(([city, v]) => {
                  const broken = (v.failure_count ?? 0) > 0 || !!v.circuit_open_until;
                  return (
                    <tr key={city}>
                      <td className="py-1.5 font-medium text-slate-300">{city}</td>
                      <td className={broken ? "py-1.5 text-amber-400" : "py-1.5 text-slate-400"}>
                        {v.failure_count ?? 0}
                      </td>
                      <td className="py-1.5 text-slate-400">
                        {v.circuit_open_until ? `aberto até ${fmtDt(v.circuit_open_until)}` : "fechado"}
                      </td>
                      <td className="py-1.5 text-slate-400">{fmtDt(v.last_success_at)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </Card>

        {/* -------------------------------------------------- créditos */}
        <Card title="Controlo de créditos" icon={<Wallet className="h-4 w-4" />}>
          <div className="grid grid-cols-2 gap-3 text-xs">
            <div className="rounded-lg border border-white/10 p-3">
              <div className="text-slate-500">Consumidos hoje</div>
              <div className="text-lg font-bold text-slate-100">{overview?.credits.used_today ?? 0}</div>
            </div>
            <div className="rounded-lg border border-white/10 p-3">
              <div className="text-slate-500">Estornos hoje</div>
              <div className="text-lg font-bold text-slate-100">{overview?.credits.refunded_today ?? 0}</div>
            </div>
          </div>
          <p className="mt-3 text-[11px] leading-relaxed text-slate-500">
            Fonte: soma de <code className="text-slate-400">user_daily_stats.leads_used</code>. É um contador
            mutável, sem ledger — a reconciliação contra <code className="text-slate-400">lead_reveals</code>{" "}
            chega na Fase 3.
          </p>
        </Card>
      </div>

      {/* ---------------------------------------------------------- fila */}
      <Card
        title="Custo das consultas Searchbug"
        icon={<Search className="h-4 w-4" />}
        hint="últimos 7 dias"
      >
        {!searchbug ? (
          <p className="text-xs text-slate-500">
            Telemetria indisponível. A recolha de métricas corre em background e nunca
            afeta a entrega — se falhar, volta a tentar.
          </p>
        ) : (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
              <Kpi
                label="Consultas pagas"
                value={searchbug.totals.billed_calls}
                sub={`hoje: ${searchbug.today.billed_calls}`}
              />
              <Kpi
                label="Cobranças fantasma"
                value={
                  <span
                    className={
                      searchbug.totals.ghost_charges > 0 ? "text-amber-400" : "text-emerald-400"
                    }
                  >
                    {searchbug.totals.ghost_charges}
                  </span>
                }
                sub="pagas, sem telefone"
              />
              <Kpi
                label="Taxa de sucesso"
                value={
                  searchbug.success_rate === null
                    ? "—"
                    : `${Math.round(searchbug.success_rate * 100)}%`
                }
                sub={`${searchbug.totals.successes} com telefone`}
              />
              <Kpi
                label="Latência p95"
                value={searchbug.latency.p95_ms === null ? "—" : `${searchbug.latency.p95_ms} ms`}
                sub={`${searchbug.latency.samples} amostras`}
              />
              <Kpi
                label="Poupadas"
                value={searchbug.totals.saved_calls}
                sub="por guard/cache"
              />
            </div>

            {searchbug.buffer.dropped > 0 || searchbug.buffer.flush_errors > 0 ? (
              <p className="rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-[11px] text-amber-300">
                Telemetria perdida: {searchbug.buffer.dropped} evento(s) descartado(s) e{" "}
                {searchbug.buffer.flush_errors} falha(s) de escrita. Os números acima
                estão subestimados.
              </p>
            ) : null}

            {searchbug.by_outcome.length > 0 ? (
              <div>
                <h3 className="mb-1.5 text-[10px] uppercase tracking-wider text-slate-500">
                  Resultado das consultas
                </h3>
                <div className="flex flex-wrap gap-1.5">
                  {searchbug.by_outcome.map((o) => (
                    <span
                      key={o.outcome}
                      className={`rounded-md border px-2 py-1 font-mono text-[11px] ${
                        o.outcome === "success"
                          ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-400"
                          : o.billed_n > 0
                            ? "border-amber-500/30 bg-amber-500/10 text-amber-400"
                            : "border-white/10 bg-white/[0.02] text-slate-500"
                      }`}
                    >
                      {o.outcome} <span className="opacity-70">{o.n}</span>
                    </span>
                  ))}
                </div>
              </div>
            ) : null}

            {searchbug.by_city.length > 0 ? (
              <div>
                <h3 className="mb-1.5 text-[10px] uppercase tracking-wider text-slate-500">
                  Cidades que mais custam
                </h3>
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-xs">
                    <thead className="text-[10px] uppercase tracking-wider text-slate-500">
                      <tr>
                        <th className="py-1">Cidade</th>
                        <th className="py-1">Pagas</th>
                        <th className="py-1">Sem telefone</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-white/5">
                      {searchbug.by_city.map((c) => (
                        <tr key={c.city}>
                          <td className="py-1.5 text-slate-300">{c.city}</td>
                          <td className="py-1.5 text-slate-400">{c.billed_calls}</td>
                          <td
                            className={
                              c.ghost_charges > 0 ? "py-1.5 text-amber-400" : "py-1.5 text-slate-500"
                            }
                          >
                            {c.ghost_charges}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            ) : null}

            {searchbug.recent.length === 0 ? (
              <p className="text-xs text-slate-500">
                Sem consultas registadas. A recolha de métricas só entra em vigor depois
                do deploy desta versão.
              </p>
            ) : (
              <details className="rounded-lg border border-white/10 p-2">
                <summary className="cursor-pointer text-xs font-semibold text-slate-400">
                  Últimas {searchbug.recent.length} consultas
                </summary>
                <div className="mt-2 overflow-x-auto">
                  <table className="w-full text-left text-[11px]">
                    <thead className="text-[10px] uppercase tracking-wider text-slate-500">
                      <tr>
                        <th className="py-1">Quando</th>
                        <th className="py-1">Resultado</th>
                        <th className="py-1">Cidade</th>
                        <th className="py-1">Latência</th>
                        <th className="py-1">Erro</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-white/5">
                      {searchbug.recent.map((r) => (
                        <tr key={r.id}>
                          <td className="py-1 text-slate-500">{fmtDt(r.called_at)}</td>
                          <td
                            className={`py-1 font-mono ${
                              r.outcome === "success"
                                ? "text-emerald-400"
                                : r.billed === 1
                                  ? "text-amber-400"
                                  : "text-slate-500"
                            }`}
                          >
                            {r.outcome}
                          </td>
                          <td className="py-1 text-slate-400">{r.city ?? "—"}</td>
                          <td className="py-1 text-slate-400">
                            {r.latency_ms === null ? "—" : `${r.latency_ms} ms`}
                          </td>
                          <td className="max-w-[220px] truncate py-1 text-slate-600">
                            {r.error ?? "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </details>
            )}
          </div>
        )}
      </Card>

      {/* ------------------------------------------------------ push */}
      <Card
        title="Saúde das push notifications"
        icon={<BellRing className="h-4 w-4" />}
        hint={push ? `últimos ${push.days} dias` : undefined}
      >
        {!push ? (
          <p className="text-xs text-slate-500">
            Sem telemetria de push. O buffer só escreve quando há uma subscrição para notificar.
          </p>
        ) : (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <Kpi
                label=" subscrições mortas"
                value={push.totals.expired}
                sub={`hoje: ${push.today.expired} · ${push.live_subscriptions} vivas`}
              />
              <Kpi
                label="Aceites (não entregues)"
                value={push.totals.accepted}
                sub={`hoje: ${push.today.accepted}`}
              />
              <Kpi
                label="Com retry"
                value={push.totals.retried}
                sub={`${push.totals.deliveries} tentativas totais`}
              />
              <Kpi
                label="Latência p95"
                value={push.latency.p95_ms === null ? "?" : `${push.latency.p95_ms} ms`}
                sub={`${push.latency.samples} aceites`}
              />
            </div>

            {push.totals.not_configured > 0 ? (
              <p className="rounded-lg bg-amber-500/10 px-3 py-2 text-[11px] text-amber-300">
                {push.totals.not_configured} tentativa(s) com o push desligado (sem VAPID). Nada
                foi enviado e nada apareceu nos logs do utilizador.
              </p>
            ) : null}

            {push.buffer.dropped > 0 || push.buffer.flush_errors > 0 ? (
              <p className="rounded-lg bg-rose-500/10 px-3 py-2 text-[11px] text-rose-300">
                Telemetria perdida: {push.buffer.dropped} evento(s) descartado(s) e{" "}
                {push.buffer.flush_errors} falha(s) de escrita.
              </p>
            ) : null}

            {push.by_outcome.length > 0 ? (
              <div className="space-y-1">
                <h3 className="text-[10px] uppercase tracking-wider text-slate-500">Por resultado</h3>
                {push.by_outcome.map((o) => (
                  <div key={o.outcome} className="flex items-center gap-2 text-xs">
                    <span
                      className={`w-28 shrink-0 font-mono ${
                        o.outcome === "accepted"
                          ? "text-emerald-400"
                          : o.outcome === "expired"
                            ? "text-amber-400"
                            : "text-slate-400"
                      }`}
                    >
                      {o.outcome}
                    </span>
                    <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-white/5">
                      <div
                        className="h-full rounded-full bg-indigo-500/70"
                        style={{ width: `${(o.n / push.totals.deliveries) * 100}%` }}
                      />
                    </div>
                    <span className="w-8 shrink-0 text-right text-slate-500">{o.n}</span>
                  </div>
                ))}
              </div>
            ) : null}

            {push.by_kind.length > 0 ? (
              <details className="rounded-lg border border-white/5">
                <summary className="cursor-pointer px-3 py-2 text-xs text-slate-400">
                  Por tipo de envio ({push.by_kind.length})
                </summary>
                <div className="overflow-x-auto px-3 pb-3">
                  <table className="w-full text-left text-xs">
                    <thead className="text-[10px] uppercase tracking-wider text-slate-500">
                      <tr>
                        <th className="py-1">Tipo</th>
                        <th className="py-1">Total</th>
                        <th className="py-1">Aceites</th>
                        <th className="py-1">Mortas</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-white/5">
                      {push.by_kind.map((k) => (
                        <tr key={k.kind}>
                          <td className="py-1 font-mono text-slate-300">{k.kind}</td>
                          <td className="py-1 text-slate-400">{k.n}</td>
                          <td className="py-1 text-emerald-400">{k.accepted}</td>
                          <td className="py-1 text-amber-400">{k.expired}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </details>
            ) : null}

            {push.recent.length > 0 ? (
              <details className="rounded-lg border border-white/5">
                <summary className="cursor-pointer px-3 py-2 text-xs text-slate-400">
                  Últimas {push.recent.length} tentativas
                </summary>
                <div className="overflow-x-auto px-3 pb-3">
                  <table className="w-full text-left text-xs">
                    <thead className="text-[10px] uppercase tracking-wider text-slate-500">
                      <tr>
                        <th className="py-1">Quando</th>
                        <th className="py-1">Resultado</th>
                        <th className="py-1">Tipo</th>
                        <th className="py-1">Tentativas</th>
                        <th className="py-1">Erro</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-white/5">
                      {push.recent.map((r) => (
                        <tr key={r.id}>
                          <td className="py-1 text-slate-500">{fmtDt(r.sent_at)}</td>
                          <td
                            className={`py-1 font-mono ${
                              r.outcome === "accepted"
                                ? "text-emerald-400"
                                : r.outcome === "expired"
                                  ? "text-amber-400"
                                  : "text-slate-400"
                            }`}
                          >
                            {r.outcome}
                          </td>
                          <td className="py-1 text-slate-400">{r.kind ?? "—"}</td>
                          <td className="py-1 text-slate-400">
                            {r.attempts}
                            {r.http_status !== null ? ` · ${r.http_status}` : ""}
                          </td>
                          <td className="max-w-[220px] truncate py-1 text-slate-600">
                            {r.error ?? "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </details>
            ) : null}
          </div>
        )}
      </Card>

      {/* ---------------------------------------------------------- fila */}
      <Card
        title="Fila de recuperação (revelos que voltaram ao pool)"
        icon={<Activity className="h-4 w-4" />}
        hint={`${reveals.length} registo(s)`}
      >
        {reveals.length === 0 ? (
          <p className="text-xs text-slate-500">Nada pendente: nenhum reveal voltou ao pool sem estorno.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="text-[10px] uppercase tracking-wider text-slate-500">
                <tr>
                  <th className="py-1.5">Lead</th>
                  <th className="py-1.5">Morada</th>
                  <th className="py-1.5">Telefone na BD</th>
                  <th className="py-1.5">Revelado</th>
                  <th className="py-1.5">Contacto sinalizado</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {reveals.map((r) => (
                  <tr key={r.id}>
                    <td className="py-1.5 font-mono text-slate-400">#{r.lead_id}</td>
                    <td className="py-1.5 text-slate-300">
                      {r.address || "—"}
                      {r.city ? <span className="text-slate-500"> · {r.city}</span> : null}
                    </td>
                    <td className="py-1.5">
                      {r.has_phone ? (
                        <span className="text-emerald-400">presente (recuperável)</span>
                      ) : (
                        <span className="text-slate-500">ausente</span>
                      )}
                    </td>
                    <td className="py-1.5 text-slate-400">{fmtDt(r.revealed_at)}</td>
                    <td className="py-1.5">
                      {r.contact_flagged ? (
                        <span className="text-emerald-400">sim</span>
                      ) : (
                        <span className="text-amber-400">não</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <div className="grid gap-5 lg:grid-cols-2">
        {/* -------------------------------------------------- runs */}
        <Card title="Histórico de runs do scraper" icon={<RefreshCcw className="h-4 w-4" />}>
          {runs.length === 0 ? (
            <p className="text-xs text-slate-500">Sem runs registados.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="text-[10px] uppercase tracking-wider text-slate-500">
                  <tr>
                    <th className="py-1.5">Início</th>
                    <th className="py-1.5">Trigger</th>
                    <th className="py-1.5">Inseridos</th>
                    <th className="py-1.5">Cidades</th>
                    <th className="py-1.5">Estado</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/5">
                  {runs.map((r) => (
                    <tr key={r.run_id}>
                      <td className="py-1.5 text-slate-400">{fmtDt(r.started_at)}</td>
                      <td className="py-1.5 text-slate-400">{r.trigger}</td>
                      <td className="py-1.5 text-slate-300">{r.inserted}</td>
                      <td className="py-1.5 text-slate-400">{r.cities_covered ?? "—"}</td>
                      <td
                        className={`py-1.5 ${
                          r.error ? "text-rose-400" : r.status === "completed" ? "text-emerald-400" : "text-amber-400"
                        }`}
                      >
                        {r.error ? `erro: ${r.error.slice(0, 40)}` : r.status}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        {/* -------------------------------------------------- alertas */}
        <Card
          title="Alertas de auditoria"
          icon={<AlertTriangle className="h-4 w-4" />}
          hint={`${overview?.alerts.unacknowledged ?? 0} por reconhecer`}
        >
          {alerts.length === 0 ? (
            <p className="text-xs text-slate-500">Sem alertas registados.</p>
          ) : (
            <ul className="space-y-2">
              {alerts.map((a) => (
                <li key={a.id} className="rounded-lg border border-white/10 p-2.5">
                  <div className="flex items-center gap-2">
                    <span
                      className={`text-[10px] font-bold uppercase ${
                        a.level === "critical" ? "text-rose-400" : "text-amber-400"
                      }`}
                    >
                      {a.level}
                    </span>
                    <span className="font-mono text-[11px] text-slate-400">{a.code}</span>
                    <span className="ml-auto text-[11px] text-slate-500">{fmtDt(a.created_at)}</span>
                  </div>
                  <p className="mt-1 text-xs text-slate-300">{a.message}</p>
                  {a.acknowledged ? (
                    <span className="mt-1 inline-block text-[10px] text-slate-500">reconhecido</span>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <footer className="flex items-center gap-2 pt-2 text-[11px] text-slate-600">
        <Users className="h-3 w-3" />
        Push e Searchbug medem custo e entrega através de buffer próprio: uma falha de escrita
        nunca affecta um pedido de utilizador. As duas métricas entram no painel sem transacção
        no caminho crítico.
      </footer>
    </div>
  );
}
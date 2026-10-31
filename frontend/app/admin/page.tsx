"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  Activity,
  AlertTriangle,
  Ban,
  BellRing,
  CheckCircle2,
  Database,
  FlaskConical,
  KeyRound,
  Languages,
  Loader2,
  Mail,
  Phone,
  RefreshCcw,
  Search,
  Send,
  SendHorizontal,
  ShieldAlert,
  Sparkles,
  Undo2,
  Users,
  Wallet,
} from "lucide-react";

import {
  AdminAlert,
  AdminApiError,
  AdminOutboundBatchRow,
  AdminOutboundConfigResponse,
  AdminOutboundMessageRow,
  AdminOutboundPreview,
  AdminOutboundSimulation,
  AdminOutboundStatus,
  AdminOverview,
  AdminPlannerMetrics,
  AdminDigestAb,
  AdminPushMetrics,
  AdminReveal,
  AdminScraperRun,
  AdminSearchbugMetrics,
  AdminPhoneSampleProgress,
  AdminSources,
    AdminCreditBackfillResponse,
    AdminCreditBalance,
    AdminCreditLedgerEvent,
    AdminCreditLedgerResponse,
    AdminCreditReconcileResponse,
  fetchAdminAlerts,
  fetchAdminEnrichmentStatus,
  fetchAdminOutboundBatches,
  fetchAdminOutboundConfig,
  fetchAdminOutboundMessages,
  fetchAdminOutboundStatus,
  fetchAdminOverview,
  fetchAdminPlanner,
  fetchAdminPush,
  fetchAdminDigestAb,
  fetchAdminReveals,
  fetchAdminScraperRuns,
  fetchAdminSearchbug,
  fetchAdminPhoneSampleProgress,
  fetchAdminSources,
    fetchAdminCreditBalance,
    fetchAdminCreditBackfill,
    fetchAdminCreditLedger,
    fetchAdminCreditReconcile,
  generateAdminOutboundPreview,
  enqueueAdminEnrichment,
  sendAdminOutbound,
  sendAdminTestPush,
  simulateAdminOutbound,
  triggerAdminInboxSync,
  triggerAdminOutboundWorker,
  updateAdminOutboundConfig,
  fetchAdminSessions,
  revokeAdminSession,
  revokeAdminUserSessions,
  lookupAdminUser,
  grantAdminAccess,
  revokeAdminAccess,
  fetchAdminAccessAudit,
  fetchAdminOutboundHealth,
  markAdminOutboundReplied,
  fetchAdminBillingFunnel,
  type AdminSession,
  type AdminAccessLookup,
  type AdminAccessAuditEntry,
  type AdminOutboundHealth,
  type AdminBillingFunnel,
} from "@/lib/admin-api";
import { AUTH_TOKEN_KEY } from "@/lib/api-client";

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
  // Timestamps da BD são UTC naive. Sem sufixo, o browser interpretava como
  // hora local e desviava o valor pelo fuso.
  const normalized = value.includes("T") ? value : value.replace(" ", "T");
  const hasTz = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(normalized);
  const d = new Date(hasTz ? normalized : `${normalized}Z`);
  if (isNaN(d.getTime())) return value;
  return d.toLocaleString("pt-PT", { dateStyle: "short", timeStyle: "short" });
}

// --------------------------------------------------------------- outbound

const OUTBOUND_LABELS: Record<string, string> = {
  send_enabled: "Envio ligado",
  enrich_enabled: "Enriquecimento ligado",
  batch_size: "Tamanho do lote",
  max_spend_per_batch_usd: "Teto de gasto/lote (US$)",
  daily_enrich_cap: "Teto diário de enriquecimento",
  daily_send_cap: "Teto diário de envio",
  per_mailbox_daily_cap: "Teto diário por caixa",
  warmup_enabled: "Warm-up ligado",
  warmup_ramp: "Rampa de warm-up (x/dia por dia)",
  min_warmup_days: "Dias mínimos de warm-up",
  quiet_hours_start: "Hora de silêncio (início)",
  quiet_hours_end: "Hora de silêncio (fim)",
};

const OUTBOUND_FLAGS = new Set([
  "send_enabled",
  "enrich_enabled",
  "warmup_enabled",
]);

function fmtUsd(usd: number) {
  return `US$ ${(Number.isFinite(usd) ? usd : 0).toFixed(2)}`;
}

function OutboundPanel() {
  const [config, setConfig] = useState<AdminOutboundConfigResponse | null>(null);
  const [city, setCity] = useState<string>("");
  const [niche, setNiche] = useState<string>("");
  const [sim, setSim] = useState<AdminOutboundSimulation | null>(null);
  const [preview, setPreview] = useState<AdminOutboundPreview | null>(null);
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [loading, setLoading] = useState(true);
  const [simulating, setSimulating] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sendState, setSendState] = useState<{
    state: "idle" | "sending" | "blocked" | "error" | "ok";
    message?: string;
  }>({ state: "idle" });
  const [status, setStatus] = useState<AdminOutboundStatus | null>(null);
  const [health, setHealth] = useState<AdminOutboundHealth | null>(null);
  const [healthBusy, setHealthBusy] = useState(false);
  const [toggling, setToggling] = useState(false);
  const [enriching, setEnriching] = useState(false);
  const [batches, setBatches] = useState<AdminOutboundBatchRow[]>([]);
  const [batchesBusy, setBatchesBusy] = useState(false);
  const [batchesError, setBatchesError] = useState<string | null>(null);
  const [openBatch, setOpenBatch] = useState<number | null>(null);
  const [batchMsgs, setBatchMsgs] = useState<AdminOutboundMessageRow[]>([]);
  const [inboxBusy, setInboxBusy] = useState(false);
  const [enrichMsg, setEnrichMsg] = useState<string | null>(null);

  const loadConfig = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const cfg = await fetchAdminOutboundConfig();
      setConfig(cfg);
      setCity((prev) => (prev && cfg.cities.includes(prev) ? prev : cfg.cities[0] ?? ""));
      setNiche((prev) => prev || cfg.default_niche);
      fetchAdminOutboundStatus()
        .then(setStatus)
        .catch(() => setStatus(null));
    } catch (e) {
      setError(
        e instanceof AdminApiError ? e.message : "Falha ao carregar a configuração de outbound."
      );
    } finally {
      setLoading(false);
    }
  }, []);

  const loadBatches = useCallback(async (silent = false) => {
    if (!silent) {
      setBatchesBusy(true);
      setBatchesError(null);
    }
    try {
      const res = await fetchAdminOutboundBatches(8);
      setBatches(res.batches ?? []);
      if (!silent) setBatchesError(null);
    } catch (e) {
      // Nunca deixar o botão "morto": erro visível e estado sempre reposto.
      if (!silent) {
        setBatchesError(
          e instanceof AdminApiError
            ? `Falha ao actualizar (${e.status}): ${e.message}`
            : "Falha ao actualizar a fila. Verifique a ligação e tente novamente."
        );
      }
    } finally {
      if (!silent) setBatchesBusy(false);
    }
  }, []);

  useEffect(() => {
    void loadConfig();
    void loadBatches();
  }, [loadConfig, loadBatches]);

  // Auto-refresh leve: fila e caixas mudam sem interaccao do utilizador.
  useEffect(() => {
    const id = setInterval(() => {
      fetchAdminOutboundStatus().then(setStatus).catch(() => undefined);
      void loadBatches(true);
    }, 30000);
    return () => clearInterval(id);
  }, [loadBatches]);

  const toggleBatch = useCallback(
    async (batchId: number) => {
      if (openBatch === batchId) {
        setOpenBatch(null);
        setBatchMsgs([]);
        return;
      }
      setOpenBatch(batchId);
      setBatchMsgs([]);
      try {
        const res = await fetchAdminOutboundMessages(batchId, 100);
        setBatchMsgs(res.messages ?? []);
      } catch {
        setBatchMsgs([]);
      }
    },
    [openBatch]
  );

  const runInboxSync = useCallback(async () => {
    setInboxBusy(true);
    setError(null);
    try {
      const res = await triggerAdminInboxSync();
      setEnrichMsg(`Inbox sync: ${JSON.stringify(res)}`);
      void loadBatches();
    } catch (e) {
      setError(e instanceof AdminApiError ? e.message : "Falha no inbox sync.");
    } finally {
      setInboxBusy(false);
    }
  }, [loadBatches]);

  const runPreview = useCallback(async () => {
    if (!city) return;
    setPreviewing(true);
    setError(null);
    try {
      const result = await generateAdminOutboundPreview(city, niche || undefined);
      setPreview(result);
      setSubject(result.preview.subject);
      setBody(result.preview.body);
    } catch (e) {
      setError(e instanceof AdminApiError ? e.message : "Falha ao gerar a prévia.");
    } finally {
      setPreviewing(false);
    }
  }, [city, niche]);

  const runSimulation = useCallback(async () => {
    if (!city) return;
    setSimulating(true);
    setError(null);
    setSendState({ state: "idle" });
    try {
      const result = await simulateAdminOutbound(city, undefined, niche || undefined);
      setSim(result);
      setPreview(null);
      setSubject(result.preview.subject);
      setBody(result.preview.body);
    } catch (e) {
      setError(e instanceof AdminApiError ? e.message : "Falha na simulação.");
    } finally {
      setSimulating(false);
    }
  }, [city, niche]);

  const trySend = useCallback(async () => {
    if (!sim?.batch?.id) return;
    setSendState({ state: "sending" });
    try {
      const result = await sendAdminOutbound(sim.batch.id, city);
      setSendState({
        state: "ok",
        message: `Lote #${result.batch_id}: ${result.queued} de ${result.total_leads} lead(s) enfileirado(s); ${
          result.no_email
        } sem e-mail. O worker envia respeitando tetos e quiet hours.`,
      });
      void loadConfig();
    } catch (e) {
      if (e instanceof AdminApiError) {
        setSendState({ state: "blocked", message: e.message });
      } else {
        setSendState({ state: "error", message: "Falha ao contactar o servidor." });
      }
    }
  }, [sim, city, loadConfig]);

  const toggleFlag = useCallback(
    async (key: "send_enabled" | "enrich_enabled", next: boolean) => {
      setToggling(true);
      setError(null);
      try {
        await updateAdminOutboundConfig({ [key]: next });
        await loadConfig();
      } catch (e) {
        setError(e instanceof AdminApiError ? e.message : "Falha ao atualizar a configuração.");
      } finally {
        setToggling(false);
      }
    },
    [loadConfig]
  );

  const runWorker = useCallback(async () => {
    setToggling(true);
    setError(null);
    try {
      const result = await triggerAdminOutboundWorker();
      setStatus(await fetchAdminOutboundStatus());
      setSendState({
        state: "ok",
        message: `Tick do worker: ${result.sent} enviado(s)${
          result.skipped ? `, ${result.skipped} ignorado(s)` : ""
        }${result.failed ? `, ${result.failed} falha(s)` : ""} (estado: ${result.status}).`,
      });
    } catch (e) {
      setError(e instanceof AdminApiError ? e.message : "Falha ao correr o worker.");
    } finally {
      setToggling(false);
    }
  }, []);

  const loadHealth = useCallback(async () => {
    setHealthBusy(true);
    setError(null);
    try {
      setHealth(await fetchAdminOutboundHealth());
    } catch (e) {
      setError(e instanceof AdminApiError ? e.message : "Falha ao ler a saúde do motor.");
    } finally {
      setHealthBusy(false);
    }
  }, []);

  const markReplied = useCallback(async (message: AdminOutboundMessageRow) => {
    if (!message.contact_id) return;
    if (!window.confirm(`Marcar ${message.to_email} como tendo respondido?`)) return;
    try {
      await markAdminOutboundReplied(message.contact_id);
      setBatchMsgs((prev) =>
        prev.map((m) =>
          m.id === message.id
            ? { ...m, replied_at: new Date().toISOString() }
            : m
        )
      );
    } catch (e) {
      setError(e instanceof AdminApiError ? e.message : "Falha ao marcar a resposta.");
    }
  }, []);

  const runEnrich = useCallback(async () => {
    if (!city) return;
    setEnriching(true);
    setError(null);
    setEnrichMsg(null);
    try {
      const queued = await enqueueAdminEnrichment(city, niche || undefined, 200);
      setEnrichMsg(
        `Enfileirados ${queued.jobs_created} lead(s) de ${queued.candidates_found} candidato(s). Fila total: ${queued.pending_total}.`
      );

      // Polling: a fila corre em background (descoberta + RCPT na VPS).
      let last: Awaited<ReturnType<typeof fetchAdminEnrichmentStatus>> | null = null;
      for (let i = 0; i < 36; i += 1) {
        await new Promise((resolve) => setTimeout(resolve, 5000));
        last = await fetchAdminEnrichmentStatus(city);
        const pending = last.by_status?.pending ?? 0;
        const running = last.by_status?.running ?? 0;
        if (pending + running === 0) break;
      }

      setEnrichMsg(
        `Fila concluida - validados: ${last?.by_status?.done ?? 0}, sem e-mail: ${
          last?.by_status?.no_email ?? 0
        }, falhas: ${last?.by_status?.failed ?? 0}. Contactos na base: ${
          last?.outbound_contacts ?? "?"
        }.`
      );

      // Refrescar o KPI "Com e-mail" do painel com os contactos novos.
      await runSimulation();
    } catch (e) {
      setError(e instanceof AdminApiError ? e.message : "Falha ao enfileirar o enriquecimento.");
    } finally {
      setEnriching(false);
    }
  }, [city, niche, runSimulation]);

  const cityConfig = city && config ? config.per_city[city] : null;
  const sendEnabled = cityConfig ? cityConfig.send_enabled === "1" : false;
  const globalSendEnabled = config?.global?.send_enabled === "1";
  const globalEnrichEnabled = config?.global?.enrich_enabled === "1";
  const configRows = cityConfig
    ? Object.keys(OUTBOUND_LABELS).filter((k) => k in cityConfig)
    : [];

  // Prévia "ativa": a geração explícita tem prioridade; senão a da simulação.
  const activePreview = preview ?? sim;
  const previewLanguage = activePreview?.language ?? config?.language ?? "en-US";
  const previewCount = sim ? sim.qualified_available : preview?.count ?? 0;
  const recipient = activePreview?.recipient_sample ?? null;
  const opportunity = activePreview?.opportunity_sample ?? null;
  const sampleSource = activePreview?.sample_source;

  return (
    <Card
      title="Outbound frio · motor real + simulador"
      icon={<Mail className="h-4 w-4" />}
      hint={
        globalSendEnabled
          ? `envio LIGADO no global · templates EN (US)`
          : `envio desligado (fail-closed) · só simulação · templates EN (US)`
      }
    >
      <div className="space-y-4">
        {/* selector de cidade */}
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-[10px] uppercase tracking-wider text-slate-500">Cidade</span>
          {(config?.cities ?? []).map((c) => (
            <button
              key={c}
              onClick={() => {
                setCity(c);
                setSim(null);
                setPreview(null);
                setSendState({ state: "idle" });
              }}
              className={`rounded-lg border px-3 py-1.5 text-xs font-semibold ${
                c === city
                  ? "border-indigo-500/50 bg-indigo-500/15 text-indigo-300"
                  : "border-white/10 text-slate-400 hover:bg-white/5"
              }`}
            >
              {c}
            </button>
          ))}
          {loading ? <Loader2 className="h-4 w-4 animate-spin text-slate-500" /> : null}
        </div>

        {/* selector de nicho (segmento de construção) */}
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-[10px] uppercase tracking-wider text-slate-500">Nicho</span>
          {(config?.niches ?? []).map((n) => (
            <button
              key={n.key}
              onClick={() => {
                setNiche(n.key);
                setSim(null);
                setPreview(null);
                setSendState({ state: "idle" });
              }}
              className={`rounded-lg border px-3 py-1.5 text-xs font-semibold ${
                n.key === niche
                  ? "border-emerald-500/50 bg-emerald-500/15 text-emerald-300"
                  : "border-white/10 text-slate-400 hover:bg-white/5"
              }`}
            >
              {n.label}
            </button>
          ))}
        </div>

        {error ? (
          <p className="rounded-lg border border-rose-500/30 bg-rose-500/5 px-3 py-2 text-[11px] text-rose-300">
            {error}
          </p>
        ) : null}

        {/* config efetiva da cidade */}
        {cityConfig ? (
          <div className="grid grid-cols-2 gap-2 md:grid-cols-3">
            {configRows.map((k) => {
              const value = cityConfig[k];
              const isFlag = OUTBOUND_FLAGS.has(k);
              const on = value === "1";
              return (
                <div
                  key={k}
                  className="rounded-lg border border-white/10 bg-white/[0.02] px-3 py-2"
                >
                  <div className="text-[10px] uppercase tracking-wider text-slate-500">
                    {OUTBOUND_LABELS[k]}
                  </div>
                  <div
                    className={`text-sm font-bold ${
                      isFlag ? (on ? "text-emerald-400" : "text-slate-500") : "text-slate-100"
                    }`}
                  >
                    {isFlag ? (on ? "ligado" : "desligado") : value}
                  </div>
                </div>
              );
            })}
          </div>
        ) : null}

        {/* toggles do admin + estado do motor (Fase 2) */}
        <div className="space-y-2 rounded-lg border border-white/10 bg-white/[0.02] px-3 py-2.5">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[10px] uppercase tracking-wider text-slate-500">
              Motor de envio
            </span>
            <button
              onClick={() => void toggleFlag("send_enabled", !globalSendEnabled)}
              disabled={toggling}
              className={`inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-semibold disabled:opacity-50 ${
                globalSendEnabled
                  ? "border-emerald-500/50 bg-emerald-500/15 text-emerald-300"
                  : "border-white/10 text-slate-400 hover:bg-white/5"
              }`}
            >
              {globalSendEnabled ? (
                <CheckCircle2 className="h-3.5 w-3.5" />
              ) : (
                <Ban className="h-3.5 w-3.5" />
              )}
              Envio real {globalSendEnabled ? "ligado" : "desligado"}
            </button>
            <button
              onClick={() => void toggleFlag("enrich_enabled", !globalEnrichEnabled)}
              disabled={toggling}
              className={`inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-semibold disabled:opacity-50 ${
                globalEnrichEnabled
                  ? "border-indigo-500/50 bg-indigo-500/15 text-indigo-300"
                  : "border-white/10 text-slate-400 hover:bg-white/5"
              }`}
            >
              <Sparkles className="h-3.5 w-3.5" />
              Enriquecimento {globalEnrichEnabled ? "ligado" : "desligado"}
            </button>
            <button
              onClick={() => void runWorker()}
              disabled={!globalSendEnabled || toggling}
              title={globalSendEnabled ? undefined : "Bloqueado: send_enabled=0"}
              className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 px-3 py-1.5 text-xs font-semibold text-slate-300 hover:bg-white/5 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {toggling ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <RefreshCcw className="h-3.5 w-3.5" />
              )}
              Rodar worker
            </button>
            <button
              onClick={() => void loadHealth()}
              disabled={healthBusy}
              className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 px-3 py-1.5 text-xs font-semibold text-slate-300 hover:bg-white/5 disabled:opacity-50"
            >
              {healthBusy ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Activity className="h-3.5 w-3.5" />
              )}
              Saúde do motor
            </button>
            <button
              onClick={() => void runEnrich()}
              disabled={!city || enriching}
              title={
                globalEnrichEnabled
                  ? "Descobre dominios e valida e-mails na VPS (nao bloqueia a API)"
                  : "Liga o Enriquecimento para permitir a descoberta"
              }
              className="inline-flex items-center gap-1.5 rounded-lg border border-indigo-500/40 bg-indigo-500/10 px-3 py-1.5 text-xs font-semibold text-indigo-300 hover:bg-indigo-500/20 disabled:opacity-40"
            >
              {enriching ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Database className="h-3.5 w-3.5" />
              )}
              Enriquecer cidade
            </button>
            {status ? (
              <span className="ml-auto text-[11px] text-slate-500">
                fila {status.queued} · enviados hoje {status.sent_today} · enriquecidos{" "}
                {status.enriched_today} · {fmtUsd(status.spend_today_usd)}
              </span>
            ) : null}
          </div>
          {status?.queue_blocker ? (
            <div
              data-testid="outbound-queue-blocker"
              className="rounded border border-amber-500/30 bg-amber-500/5 px-2 py-1.5 text-[10px] text-amber-300"
            >
              <span className="font-semibold uppercase tracking-wide">
                Fila parada · {status.queue_blocker.reason}
              </span>
              <span className="ml-1 text-amber-200/90">{status.queue_blocker.detail}</span>
              {status.queue_blocker.retry_at ? (
                <span className="ml-1 text-amber-200/70">
                  (retoma {status.queue_blocker.retry_at.slice(0, 16)} UTC)
                </span>
              ) : null}
            </div>
          ) : status && status.queued > 0 ? (
            <p className="text-[10px] text-emerald-400/80">
              Fila a drenar · {status.mailbox_remaining_today ?? 0} envio(s) disponíveis hoje.
            </p>
          ) : null}
          {health ? (
            <div className="rounded border border-white/10 bg-black/20 px-2 py-1.5" data-testid="outbound-health">
              <div className="flex items-center gap-2">
                <span className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                  Saúde do motor · Control Tower
                </span>
                <button
                  onClick={() => setHealth(null)}
                  className="ml-auto text-[10px] text-slate-500 hover:text-slate-300"
                >
                  fechar
                </button>
              </div>
              {health.checks.filter((c) => c.status !== "ok").length > 0 ? (
                <ul className="mt-1 space-y-0.5">
                  {health.checks
                    .filter((c) => c.status !== "ok")
                    .map((c) => (
                      <li
                        key={c.check_name}
                        className={c.status === "fail" ? "text-[10px] text-rose-400" : "text-[10px] text-amber-400"}
                      >
                        [{c.status}] {c.check_name}: {c.detail}
                      </li>
                    ))}
                </ul>
              ) : (
                <p className="mt-1 text-[10px] text-emerald-400">Todos os checks OK.</p>
              )}
              <pre className="mt-1 max-h-56 overflow-auto whitespace-pre-wrap text-[10px] leading-relaxed text-slate-400">
                {health.digest}
              </pre>
            </div>
          ) : null}
          <p className="text-[10px] text-slate-600">
            EmailListVerify {status?.enrichment_configured ? "configurado" : "não configurado"}.
            {status?.quiet_hours_now ? " Agora em quiet hours — o worker não envia." : ""}
            {status && status.mailboxes.length === 0
              ? " Sem caixas de envio configuradas — o envio fica em espera."
              : ""}
          </p>
          {enrichMsg ? (
            <p className="rounded border border-indigo-500/30 bg-indigo-500/5 px-2 py-1 text-[10px] text-indigo-300">
              {enrichMsg}
            </p>
          ) : null}
        </div>

        {/* caixas de envio: dados reais de /outbound/status */}
        {status && status.mailboxes.length > 0 ? (
          <div className="space-y-2 rounded-lg border border-white/10 bg-white/[0.02] px-3 py-2.5">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-[10px] uppercase tracking-wider text-slate-500">
                Caixas de envio
              </span>
              <button
                onClick={() => void runInboxSync()}
                disabled={inboxBusy}
                className="ml-auto inline-flex items-center gap-1.5 rounded-lg border border-white/10 px-2 py-1 text-[10px] font-semibold text-slate-300 hover:bg-white/5 disabled:opacity-40"
              >
                {inboxBusy ? (
                  <Loader2 className="h-3 w-3 animate-spin" />
                ) : (
                  <Mail className="h-3 w-3" />
                )}
                Sincronizar inbox
              </button>
            </div>
            <table className="w-full text-left text-[11px]">
              <thead className="text-[10px] uppercase tracking-wider text-slate-500">
                <tr>
                  <th className="py-1">Conta</th>
                  <th className="py-1">Estado</th>
                  <th className="py-1">Hoje / cap</th>
                  <th className="py-1">Warm-up</th>
                </tr>
              </thead>
              <tbody className="text-slate-300">
                {status.mailboxes.map((mb) => (
                  <tr key={mb.id} className="border-t border-white/5">
                    <td className="py-1">
                      {mb.email}
                      {mb.city ? (
                        <span className="ml-1 text-[10px] text-slate-500">{mb.city}</span>
                      ) : null}
                    </td>
                    <td className="py-1">
                      {mb.enabled ? (
                        <span className="text-emerald-400">ligada</span>
                      ) : (
                        <span className="text-slate-500">desligada</span>
                      )}
                    </td>
                    <td className="py-1">
                      {mb.sent_today} / {mb.effective_cap}
                      <span className="ml-1 text-[10px] text-slate-500">
                        (restam {mb.remaining_today})
                      </span>
                    </td>
                    <td className="py-1">
                      dia {mb.warmup_days} · {mb.warmup_state}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}

        {/* fila e lotes: o que esta' realmente a sair e quando */}
        <div className="rounded-lg border border-white/10">
          <div className="flex flex-wrap items-center gap-2 border-b border-white/10 px-3 py-2">
            <span className="text-[10px] uppercase tracking-wider text-slate-500">
              Fila e lotes
            </span>
            <span className="text-[10px] text-slate-600">
              clica num lote para ver as mensagens
            </span>
            <button
              onClick={() => void loadBatches()}
              disabled={batchesBusy}
              data-testid="reload-batches"
              className="ml-auto inline-flex items-center gap-1 rounded border border-white/10 px-2 py-1 text-[10px] font-semibold text-slate-300 hover:bg-white/5 disabled:cursor-wait disabled:opacity-60"
            >
              {batchesBusy ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <RefreshCcw className="h-3 w-3" />
              )}
              {batchesBusy ? "A actualizar…" : "Actualizar"}
            </button>
          </div>
          {batchesError ? (
            <p
              role="alert"
              data-testid="batches-error"
              className="border-b border-rose-500/20 bg-rose-500/5 px-3 py-1.5 text-[10px] text-rose-300"
            >
              {batchesError}
            </p>
          ) : null}
          {batches.length === 0 ? (
            <p className="px-3 py-3 text-[11px] text-slate-500">Sem lotes.</p>
          ) : (
            <table className="w-full text-left text-[11px]">
              <thead className="text-[10px] uppercase tracking-wider text-slate-500">
                <tr>
                  <th className="px-3 py-1.5">#</th>
                  <th className="py-1.5">Cidade</th>
                  <th className="py-1.5">Estado</th>
                  <th className="py-1.5">Fila</th>
                  <th className="py-1.5">Enviados</th>
                  <th className="py-1.5">Saltados</th>
                  <th className="py-1.5">Falhas</th>
                  <th className="py-1.5">Total</th>
                </tr>
              </thead>
              {batches.map((b) => (
                <tbody key={b.id} className="text-slate-300">
                  <tr
                    onClick={() => void toggleBatch(b.id)}
                    className="cursor-pointer border-t border-white/5 hover:bg-white/[0.03]"
                  >
                    <td className="px-3 py-1.5 font-mono">{b.id}</td>
                    <td className="py-1.5">{b.city}</td>
                    <td className="py-1.5">
                      <span className={b.status === "sending" ? "text-indigo-300" : "text-slate-400"}>
                        {b.status}
                      </span>
                      {b.dry_run ? <span className="ml-1 text-slate-600">(dry)</span> : null}
                    </td>
                    <td className="py-1.5">{b.queued}</td>
                    <td className="py-1.5">{b.sent}</td>
                    <td className="py-1.5">{b.skipped}</td>
                    <td className={`py-1.5 ${b.failed ? "text-rose-400" : ""}`}>{b.failed}</td>
                    <td className="py-1.5">{b.total}</td>
                  </tr>
                  {openBatch === b.id ? (
                    <tr className="border-t border-white/5 bg-black/20">
                      <td colSpan={8} className="px-3 py-2">
                        {batchMsgs.length === 0 ? (
                          <span className="text-[10px] text-slate-500">
                            (sem mensagens — lote ainda nao promovido)
                          </span>
                        ) : (
                          <table className="w-full text-left text-[10px]">
                            <thead className="text-slate-500">
                              <tr>
                                <th className="py-1">#</th>
                                <th className="py-1">Destinatario</th>
                                <th className="py-1">Estado</th>
                                <th className="py-1">De</th>
                                <th className="py-1">provider_id</th>
                                <th className="py-1">Enviado</th>
                                <th className="py-1">Erro</th>
                                <th className="py-1">Resposta</th>
                              </tr>
                            </thead>
                            <tbody className="text-slate-400">
                              {batchMsgs.map((m) => (
                                <tr key={m.id} className="border-t border-white/5">
                                  <td className="py-0.5 font-mono">{m.id}</td>
                                  <td className="py-0.5">{m.to_email}</td>
                                  <td className={`py-0.5 ${m.status === "sent" ? "text-emerald-400" : m.status === "failed" ? "text-rose-400" : ""}`}>
                                    {m.status}
                                  </td>
                                  <td className="py-0.5">{m.from_addr || "—"}</td>
                                  <td className="py-0.5 font-mono">{m.provider_id || "—"}</td>
                                  <td className="py-0.5">{m.sent_at || "—"}</td>
                                  <td className="py-0.5 text-rose-400">{m.error || ""}</td>
                                   <td className="py-0.5">
                                     {m.replied_at ? (
                                       <span className="text-emerald-400">respondeu</span>
                                     ) : m.contact_id && m.status === "sent" ? (
                                       <button
                                         onClick={() => void markReplied(m)}
                                         className="rounded border border-white/10 px-1.5 py-0.5 text-[10px] text-slate-300 hover:bg-white/5"
                                       >
                                         marcar
                                       </button>
                                     ) : (
                                       <span className="text-slate-600">—</span>
                                     )}
                                   </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        )}
                      </td>
                    </tr>
                  ) : null}
                </tbody>
              ))}
            </table>
          )}
        </div>

        {/* gerar prévia + simular */}
        <div className="flex flex-wrap items-center gap-3">
          <button
            onClick={() => void runPreview()}
            disabled={!city || previewing}
            className="inline-flex items-center gap-2 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-xs font-semibold text-emerald-300 hover:bg-emerald-500/20 disabled:opacity-50"
          >
            {previewing ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Sparkles className="h-3.5 w-3.5" />
            )}
            Gerar prévia (dados reais)
          </button>
          <button
            onClick={() => void runSimulation()}
            disabled={!city || simulating}
            className="inline-flex items-center gap-2 rounded-lg bg-indigo-500 px-3 py-2 text-xs font-semibold text-white hover:bg-indigo-400 disabled:opacity-50"
          >
            {simulating ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Send className="h-3.5 w-3.5" />
            )}
            Simular lote (dry-run)
          </button>
          <span className="inline-flex items-center gap-1 rounded-md border border-white/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-slate-400">
            <Languages className="h-3 w-3" /> {previewLanguage}
          </span>
          <span className="text-[11px] text-slate-500">
            Não envia nada. Calcula o inventário, o custo estimado e o template do nicho.
          </span>
        </div>

        {/* dados reais que preenchem a prévia */}
        {activePreview ? (
          <div className="rounded-lg border border-white/10 bg-white/[0.02] px-3 py-2.5">
            <div className="mb-1.5 flex flex-wrap items-center gap-2 text-[10px] uppercase tracking-wider text-slate-500">
              <span>Prévia preenchida com dados reais</span>
              <span
                className={`rounded px-1.5 py-0.5 text-[9px] font-semibold ${
                  sampleSource === "enriched_contact"
                    ? "bg-emerald-500/15 text-emerald-300"
                    : "bg-amber-500/15 text-amber-300"
                }`}
              >
                {sampleSource === "enriched_contact"
                  ? "contacto enriquecido"
                  : "fallback: nome do proprietário"}
              </span>
              <span className="rounded bg-indigo-500/15 px-1.5 py-0.5 text-[9px] font-semibold text-indigo-300">
                {activePreview.niche_label}
              </span>
            </div>
            <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-[11px] text-slate-400 md:grid-cols-3">
              <div>
                <dt className="text-slate-600">Destinatário (empresa)</dt>
                <dd className="text-slate-200">{recipient?.company_name ?? "your company"}</dd>
              </div>
              <div>
                <dt className="text-slate-600">Contacto</dt>
                <dd className="text-slate-200">{recipient?.contact_name ?? "there"}</dd>
              </div>
              <div>
                <dt className="text-slate-600">E-mail destinatário</dt>
                <dd className="text-slate-200">{recipient?.email ?? "— (a enriquecer)"}</dd>
              </div>
              <div>
                <dt className="text-slate-600">Oportunidade (endereço)</dt>
                <dd className="text-slate-200">{opportunity?.address ?? "—"}</dd>
              </div>
              <div>
                <dt className="text-slate-600">Categoria</dt>
                <dd className="text-slate-200">{opportunity?.issue_category ?? "—"}</dd>
              </div>
              <div>
                <dt className="text-slate-600">Oportunidades no nicho</dt>
                <dd className="text-slate-200">{previewCount}</dd>
              </div>
            </dl>
          </div>
        ) : null}

        {/* resultado da simulação (custo + lote rascunho) */}
        {sim ? (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
              <Kpi
                label="Empreiteiros qualificados"
                value={sim.qualified_available}
                sub={`disponíveis em ${sim.city}`}
              />
              <Kpi
                label="Com e-mail"
                value={sim.sendable_recipients ?? 0}
                sub="enfileiráveis agora"
              />
              <Kpi
                label="Tamanho do lote"
                value={sim.batch_size}
                sub={`configurado: ${sim.configured_batch_size}`}
              />
              <Kpi
                label="Custo estimado"
                value={
                  <span className={sim.over_budget ? "text-amber-400" : "text-slate-100"}>
                    {fmtUsd(sim.cost_estimate.total_usd)}
                  </span>
                }
                sub={`teto: ${fmtUsd(Number(sim.max_spend_per_batch_usd) || 0)}`}
              />
              <Kpi
                label="Lote rascunho"
                value={sim.batch ? `#${sim.batch.id}` : "—"}
                sub={sim.batch?.status ?? "—"}
              />
            </div>

            {(sim.sendable_recipients ?? 0) === 0 ? (
              <p className="rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-[11px] text-amber-300">
                Nenhum destinatário com e-mail nesta cidade: o lote enfileira 0. Importe
                contatos B2B com e-mail antes de enviar o lote real.
              </p>
            ) : null}

            {sim.over_budget ? (
              <p className="rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-[11px] text-amber-300">
                Custo estimado acima do teto por lote ({fmtUsd(Number(sim.max_spend_per_batch_usd) || 0)}).
                Reduz o tamanho do lote ou revê a config antes de avançar.
              </p>
            ) : null}

            {/* detalhe do custo */}
            <details className="rounded-lg border border-white/10 p-2">
              <summary className="cursor-pointer text-xs font-semibold text-slate-400">
                Como se chega ao custo
              </summary>
              <ul className="mt-2 space-y-1 text-[11px] text-slate-400">
                <li>Scrape próprio (HTTP): {fmtUsd(sim.cost_estimate.scrape_cost_usd)}</li>
                <li>
                  Fallback Snov: {sim.cost_estimate.snov_emails} e-mail(s) ×{" "}
                  {fmtUsd(sim.cost_estimate.snov_per_email_usd)} ={" "}
                  {fmtUsd(sim.cost_estimate.snov_cost_usd)}
                </li>
                <li>
                  Taxa estimada de fallback:{" "}
                  {Math.round(sim.cost_estimate.snov_fallback_rate * 100)}%
                </li>
              </ul>
            </details>
          </div>
        ) : null}

        {/* prévia editável (gerada por nicho com dados reais) */}
        {activePreview ? (
          <div className="space-y-2">
            <h3 className="flex flex-wrap items-center gap-2 text-[10px] uppercase tracking-wider text-slate-500">
              <span>Prévia do e-mail (editável)</span>
              <span className="inline-flex items-center gap-1 rounded bg-indigo-500/15 px-1.5 py-0.5 text-[9px] font-semibold text-indigo-300">
                <Languages className="h-3 w-3" /> {previewLanguage}
              </span>
              <span className="rounded bg-slate-500/15 px-1.5 py-0.5 text-[9px] font-semibold text-slate-300">
                {activePreview.niche_label}
              </span>
            </h3>
            <label className="block text-[11px] text-slate-500">
              Assunto
              <input
                value={subject}
                onChange={(e) => setSubject(e.target.value)}
                className="mt-1 w-full rounded-lg border border-white/10 bg-[#0b0e14] px-3 py-2 text-xs text-slate-200 outline-none focus:border-indigo-500/50"
              />
            </label>
            <label className="block text-[11px] text-slate-500">
              Corpo
              <textarea
                value={body}
                onChange={(e) => setBody(e.target.value)}
                rows={10}
                spellCheck={false}
                className="mt-1 w-full resize-y rounded-lg border border-white/10 bg-[#0b0e14] px-3 py-2 font-mono text-[11px] leading-relaxed text-slate-200 outline-none focus:border-indigo-500/50"
              />
            </label>
            <p className="text-[10px] text-slate-600">
              Placeholders disponíveis: {(activePreview.placeholders ?? []).map((p) => `{${p}}`).join(", ")}.
              O texto é editável na prévia e na simulação — ainda não persiste. Todo o copy é
              redigido em inglês comercial americano (en-US).
            </p>
          </div>
        ) : null}

        {/* trava de segurança */}
        {sim ? (
          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-3 rounded-lg border border-white/10 bg-white/[0.02] px-3 py-2.5">
              <ShieldAlert
                className={`h-4 w-4 ${sendEnabled ? "text-amber-400" : "text-emerald-400"}`}
              />
              <div className="mr-auto text-[11px] text-slate-400">
                {sendEnabled
                  ? "Envio LIGADO: promover este lote enfileira os e-mails validados; o worker envia respeitando tetos e quiet hours."
                  : "Envio DESLIGADO (send_enabled=0). Liga o envio real acima ou usa só a simulação."}
              </div>
              <button
                onClick={() => void trySend()}
                disabled={!sendEnabled || !sim.batch || sendState.state === "sending"}
                title={sendEnabled ? undefined : "Bloqueado: send_enabled=0"}
                className="inline-flex items-center gap-2 rounded-lg border border-white/10 px-3 py-2 text-xs font-semibold text-slate-400 hover:bg-white/5 disabled:cursor-not-allowed disabled:opacity-40"
              >
                {sendState.state === "sending" ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <SendHorizontal className="h-3.5 w-3.5" />
                )}
                Enviar lote real
              </button>
            </div>
            {sendState.state !== "idle" && sendState.state !== "sending" ? (
              <p
                className={`text-[11px] font-semibold ${
                  sendState.state === "ok"
                    ? "text-emerald-400"
                    : sendState.state === "blocked"
                      ? "text-amber-400"
                      : "text-rose-400"
                }`}
              >
                {sendState.message}
              </p>
            ) : null}
          </div>
        ) : null}
      </div>
    </Card>
  );
}

// --------------------------------------------------------------- acesso

const GRANT_REASONS: { value: string; label: string }[] = [
  { value: "support", label: "Suporte" },
  { value: "vip_test", label: "Teste VIP" },
  { value: "compensation", label: "Compensação" },
  { value: "partner", label: "Parceiro" },
  { value: "other", label: "Outro" },
];

const GRANT_PRESETS = [3, 7, 30] as const;

function newIdempotencyKey(): string {
  try {
    if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
      return crypto.randomUUID();
    }
  } catch {
    /* fallback abaixo */
  }
  return `grant-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function AccessGrantPanel() {
  const [email, setEmail] = useState("");
  const [lookup, setLookup] = useState<AdminAccessLookup | null>(null);
  const [lookupBusy, setLookupBusy] = useState(false);
  const [lookupError, setLookupError] = useState<string | null>(null);
  const [days, setDays] = useState<number>(7);
  const [customDays, setCustomDays] = useState("");
  const [reason, setReason] = useState("support");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [audit, setAudit] = useState<AdminAccessAuditEntry[]>([]);
  const idemRef = useRef<string>(newIdempotencyKey());

  const refreshAudit = useCallback(async () => {
    try {
      const res = await fetchAdminAccessAudit(30);
      setAudit(res.entries || []);
    } catch {
      /* auditoria é secundária; não bloqueia o formulário */
    }
  }, []);

  useEffect(() => {
    void refreshAudit();
  }, [refreshAudit]);

  const effectiveDays = customDays.trim() ? Number(customDays) : days;

  const runLookup = async () => {
    const value = email.trim().toLowerCase();
    if (!value || !value.includes("@")) {
      setLookupError("Introduza um e-mail válido.");
      setLookup(null);
      return;
    }
    setLookupBusy(true);
    setLookupError(null);
    setMessage(null);
    try {
      const res = await lookupAdminUser(value);
      setLookup(res);
    } catch (e) {
      setLookup(null);
      setLookupError(
        e instanceof AdminApiError && e.status === 404
          ? "Conta não encontrada. O utilizador tem de criar conta primeiro."
          : "Não foi possível consultar a conta."
      );
    } finally {
      setLookupBusy(false);
    }
  };

  const submit = async () => {
    if (!lookup) {
      setMessage({ ok: false, text: "Consulte primeiro o e-mail da conta." });
      return;
    }
    if (!Number.isInteger(effectiveDays) || effectiveDays < 1 || effectiveDays > 365) {
      setMessage({ ok: false, text: "Duração inválida (1 a 365 dias)." });
      return;
    }
    if (reason === "other" && !note.trim()) {
      setMessage({ ok: false, text: "Indique a nota para o motivo 'Outro'." });
      return;
    }

    const beforeText = lookup.access.expires_at
      ? `atual: ${lookup.access.status} até ${fmtDt(lookup.access.expires_at)}`
      : `atual: ${lookup.access.status}`;
    let question = `Conceder ${effectiveDays} dia(s) a ${lookup.user.email}?\n\n${beforeText}\nO acesso será SOMADO à expiração existente.`;
    if (lookup.user.is_admin) {
      question += "\n\nATENÇÃO: esta é uma conta de ADMINISTRADOR. A ação gera alerta de segurança.";
    }
    if (!window.confirm(question)) return;
    if (lookup.user.is_admin) {
      // Confirmação extra exigida para contas administrativas.
      if (
        !window.confirm(
          `Confirmar novamente: conceder ${effectiveDays} dia(s) a ${lookup.user.email} (ADMIN)?`
        )
      )
        return;
    }

    setBusy(true);
    setMessage(null);
    try {
      const res = await grantAdminAccess({
        email: lookup.user.email,
        days: effectiveDays,
        reason,
        note: note.trim() || undefined,
        idempotency_key: idemRef.current,
      });
      idemRef.current = newIdempotencyKey();
      setMessage({
        ok: true,
        text: res.duplicate
          ? `Pedido já aplicado (auditoria #${res.audit_id}).`
          : `Acesso concedido até ${fmtDt(res.after.plan_until)} (auditoria #${res.audit_id}).`,
      });
      setNote("");
      const refreshed = await lookupAdminUser(lookup.user.email).catch(() => null);
      if (refreshed) setLookup(refreshed);
      await refreshAudit();
    } catch (e) {
      setMessage({
        ok: false,
        text:
          e instanceof AdminApiError
            ? e.status === 404
              ? "Conta não encontrada."
              : e.message
            : "Não foi possível conceder o acesso.",
      });
    } finally {
      setBusy(false);
    }
  };

  const undo = async (entry: AdminAccessAuditEntry) => {
    const target = entry.target_email || `#${entry.target_user_id}`;
    if (
      !window.confirm(
        `Reverter a concessão #${entry.id} de ${target}? Só é possível se a expiração não tiver mudado.`
      )
    )
      return;
    try {
      await revokeAdminAccess(entry.id, "reversão no painel");
      setMessage({ ok: true, text: `Concessão #${entry.id} revertida.` });
      setLookup(null);
      await refreshAudit();
    } catch (e) {
      setMessage({
        ok: false,
        text:
          e instanceof AdminApiError && e.status === 409
            ? "A expiração mudou desde a concessão (pagamento posterior). Revisão manual."
            : "Não foi possível reverter a concessão.",
      });
    }
  };

  return (
    <Card
      title="Concessão de acesso (cortesia)"
      icon={<KeyRound className="h-4 w-4" />}
      hint="soma dias ao plan_until; auditoria append-only"
    >
      <div className="space-y-3" data-testid="admin-access-grant">
        {/* 1. identificar */}
        <div className="flex flex-wrap items-end gap-2">
          <label className="flex-1 min-w-[220px]">
            <span className="text-[10px] uppercase tracking-wider text-slate-500">
              E-mail da conta
            </span>
            <input
              value={email}
              onChange={(e) => {
                setEmail(e.target.value);
                setLookup(null);
                setLookupError(null);
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  void runLookup();
                }
              }}
              placeholder="cliente@exemplo.com"
              data-testid="admin-access-email"
              className="mt-1 w-full rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-sm text-slate-200 outline-none focus:border-indigo-500/50"
            />
          </label>
          <button
            onClick={() => void runLookup()}
            disabled={lookupBusy}
            className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 px-3 py-2 text-xs font-semibold text-slate-300 hover:bg-white/5 disabled:opacity-50"
          >
            {lookupBusy ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Search className="h-3.5 w-3.5" />
            )}
            Procurar
          </button>
        </div>

        {lookupError ? (
          <p className="text-[11px] text-rose-400">{lookupError}</p>
        ) : null}

        {lookup ? (
          <div className="rounded-lg border border-white/10 bg-white/[0.02] px-3 py-2 text-[11px] text-slate-300">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-semibold text-slate-100">{lookup.user.email}</span>
              {lookup.user.is_admin ? (
                <span className="rounded-full bg-amber-500/15 px-2 py-0.5 text-[10px] font-bold text-amber-400">
                  ADMIN
                </span>
              ) : null}
              <span className="text-slate-500">{lookup.user.company_name || "—"}</span>
              <span className="ml-auto text-slate-500">id {lookup.user.id}</span>
            </div>
            <div className="mt-1 flex flex-wrap items-center gap-2">
              <span
                className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${
                  lookup.access.can_access
                    ? "bg-emerald-500/15 text-emerald-400"
                    : "bg-rose-500/15 text-rose-400"
                }`}
              >
                {lookup.access.can_access ? "COM ACESSO" : "SEM ACESSO"}
              </span>
              <span className="text-slate-400">{lookup.access.message}</span>
              {lookup.access.expires_at ? (
                <span className="text-slate-500">
                  expira {fmtDt(lookup.access.expires_at)}
                </span>
              ) : null}
              {lookup.access.access_source === "admin_grant" ? (
                <span className="text-indigo-300">origem: cortesia</span>
              ) : null}
            </div>
          </div>
        ) : null}

        {/* 2. conceder */}
        <div className="grid gap-3 md:grid-cols-3">
          <div>
            <span className="text-[10px] uppercase tracking-wider text-slate-500">
              Duração
            </span>
            <div className="mt-1 flex flex-wrap gap-1.5">
              {GRANT_PRESETS.map((preset) => (
                <button
                  key={preset}
                  onClick={() => {
                    setDays(preset);
                    setCustomDays("");
                  }}
                  data-testid={`admin-access-days-${preset}`}
                  className={`rounded-lg border px-2.5 py-1.5 text-[11px] font-semibold ${
                    !customDays && days === preset
                      ? "border-indigo-500/50 bg-indigo-500/15 text-indigo-300"
                      : "border-white/10 text-slate-300 hover:bg-white/5"
                  }`}
                >
                  {preset} dias
                </button>
              ))}
              <input
                value={customDays}
                onChange={(e) => setCustomDays(e.target.value.replace(/[^0-9]/g, ""))}
                placeholder="custom"
                inputMode="numeric"
                className="w-20 rounded-lg border border-white/10 bg-white/[0.03] px-2 py-1.5 text-[11px] text-slate-200 outline-none focus:border-indigo-500/50"
              />
            </div>
          </div>

          <label>
            <span className="text-[10px] uppercase tracking-wider text-slate-500">
              Motivo
            </span>
            <select
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              className="mt-1 w-full rounded-lg border border-white/10 bg-[#10131a] px-2 py-1.5 text-[11px] text-slate-200"
            >
              {GRANT_REASONS.map((r) => (
                <option key={r.value} value={r.value}>
                  {r.label}
                </option>
              ))}
            </select>
          </label>

          <label>
            <span className="text-[10px] uppercase tracking-wider text-slate-500">
              Nota {reason === "other" ? "(obrigatória)" : "(opcional)"}
            </span>
            <input
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="ex.: ticket #1234"
              className="mt-1 w-full rounded-lg border border-white/10 bg-white/[0.03] px-2 py-1.5 text-[11px] text-slate-200 outline-none focus:border-indigo-500/50"
            />
          </label>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <span className="text-[11px] text-slate-500">
            Nova expiração:{" "}
            <span className="text-slate-300">
              {lookup?.access.expires_at
                ? `soma ${effectiveDays || "?"} dia(s) a ${fmtDt(lookup.access.expires_at)}`
                : `a partir de agora + ${effectiveDays || "?"} dia(s)`}
            </span>
          </span>
          <button
            onClick={() => void submit()}
            disabled={busy || !lookup}
            data-testid="admin-access-confirm"
            className="ml-auto inline-flex items-center gap-1.5 rounded-lg bg-indigo-500 px-3 py-2 text-xs font-semibold text-white hover:bg-indigo-400 disabled:opacity-50"
          >
            {busy ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <KeyRound className="h-3.5 w-3.5" />
            )}
            Confirmar concessão
          </button>
        </div>

        {message ? (
          <p
            className={`rounded border px-2 py-1.5 text-[11px] ${
              message.ok
                ? "border-emerald-500/30 bg-emerald-500/5 text-emerald-300"
                : "border-rose-500/30 bg-rose-500/5 text-rose-300"
            }`}
          >
            {message.text}
          </p>
        ) : null}

        {/* 3. auditoria */}
        <div className="rounded-lg border border-white/10">
          <div className="flex items-center gap-2 border-b border-white/10 px-3 py-2">
            <span className="text-[10px] uppercase tracking-wider text-slate-500">
              Últimas concessões
            </span>
            <button
              onClick={() => void refreshAudit()}
              className="ml-auto inline-flex items-center gap-1 rounded border border-white/10 px-2 py-1 text-[10px] font-semibold text-slate-300 hover:bg-white/5"
            >
              <RefreshCcw className="h-3 w-3" /> Atualizar
            </button>
          </div>
          {audit.length === 0 ? (
            <p className="px-3 py-3 text-[11px] text-slate-500">Sem registos.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-[11px]">
                <thead className="text-[10px] uppercase tracking-wider text-slate-500">
                  <tr>
                    <th className="px-3 py-1.5">Quando</th>
                    <th className="py-1.5">Admin</th>
                    <th className="py-1.5">Conta</th>
                    <th className="py-1.5">Ação</th>
                    <th className="py-1.5">Motivo</th>
                    <th className="py-1.5 text-right">Ações</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/5">
                  {audit.map((entry) => (
                    <tr key={entry.id}>
                      <td className="px-3 py-1.5 text-slate-400">{fmtDt(entry.created_at)}</td>
                      <td className="py-1.5 text-slate-400">{entry.admin_email || "—"}</td>
                      <td className="py-1.5 text-slate-300">{entry.target_email || "—"}</td>
                      <td className="py-1.5">
                        {entry.action === "grant_access" ? (
                          <span className="text-emerald-400">+{entry.days ?? "?"}d</span>
                        ) : (
                          <span className="text-rose-400">revertida</span>
                        )}
                      </td>
                      <td className="py-1.5 text-slate-400">
                        {entry.reason || "—"}
                        {entry.note ? (
                          <span className="ml-1 text-slate-600">· {entry.note}</span>
                        ) : null}
                      </td>
                      <td className="py-1.5 text-right">
                        {entry.action === "grant_access" && entry.reversible ? (
                          <button
                            onClick={() => void undo(entry)}
                            className="inline-flex items-center gap-1 rounded-md border border-rose-500/30 px-2 py-1 text-[10px] font-semibold text-rose-300 hover:bg-rose-500/10"
                          >
                            <Undo2 className="h-3 w-3" /> Reverter
                          </button>
                        ) : (
                          <span className="text-[10px] text-slate-600">
                            {entry.action === "grant_access" ? "não reversível" : "—"}
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </Card>
  );
}

// --------------------------------------------------------------- billing

function BillingFunnelPanel() {
  const [data, setData] = useState<AdminBillingFunnel | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchAdminBillingFunnel()
      .then(setData)
      .catch((e) =>
        setError(
          e instanceof AdminApiError ? e.message : "Falha ao carregar o funil de checkout."
        )
      );
  }, []);

  const f = data?.funnel;
  return (
    <Card
      title="Funil de checkout"
      icon={<Wallet className="h-4 w-4" />}
      hint="criou → email → pagou"
    >
      <div data-testid="billing-funnel">
        {error ? <p className="text-xs text-rose-400">{error}</p> : null}
        {!f ? (
          <p className="text-xs text-slate-500">A carregar…</p>
        ) : (
          <>
            <div className="grid grid-cols-2 gap-2 md:grid-cols-3">
              {[
                { label: "Sessões criadas", value: f.sessions_created },
                { label: "Com e-mail", value: f.sessions_with_email },
                { label: "Pagas", value: f.sessions_completed },
                { label: "Recuperadas", value: f.sessions_recovered },
                { label: "Abertas", value: f.sessions_open },
                { label: "Expiradas", value: f.sessions_expired },
              ].map((k) => (
                <div key={k.label} className="rounded-lg border border-white/10 p-2">
                  <div className="text-[10px] uppercase tracking-wider text-slate-500">
                    {k.label}
                  </div>
                  <div className="text-lg font-bold text-slate-100">{k.value}</div>
                </div>
              ))}
            </div>
            <div className="mt-2 flex flex-wrap gap-4 text-[11px] text-slate-400">
              <span>
                Captura de e-mail:{" "}
                <strong className="text-slate-200">
                  {(f.email_capture_rate * 100).toFixed(1)}%
                </strong>
              </span>
              <span>
                Conversão:{" "}
                <strong className="text-emerald-400">
                  {(f.conversion_rate * 100).toFixed(1)}%
                </strong>
              </span>
              <span>
                Recuperação:{" "}
                {data?.recovery.enabled ? "ligada" : "desligada"} ·{" "}
                {data?.recovery.after_minutes} min · {data?.recovery.max_reminders} lembrete(s)
              </span>
              <span className="text-slate-600">{data?.open_sessions} sessão(ões) aberta(s)</span>
            </div>
          </>
        )}
      </div>
    </Card>
  );
}

// --------------------------------------------------------------- gate

function GateScreen({ gate, hasToken }: { gate: Gate; hasToken: boolean }) {
  if (gate === "loading") {
    return (
      <div className="flex min-h-screen items-center justify-center gap-3 text-slate-400">
        <Loader2 className="h-5 w-5 animate-spin" /> A validar sessão de administrador…
      </div>
    );
  }

  const message =
    gate === "unauthenticated"
      ? hasToken
        ? "A tua sessão de administrador expirou ou foi substituída por um novo login noutro dispositivo. Volta a entrar para continuar."
        : "Não há sessão iniciada. Entra com uma conta de administrador."
      : gate === "forbidden"
        ? "A tua sessão é válida mas a conta não tem o perfil de administrador."
        : "Não foi possível falar com a API. Verifica se o backend está de pé.";

  return (
    <div className="flex min-h-screen items-center justify-center p-6">
      <div className="max-w-md rounded-2xl border border-white/10 bg-[#10131a] p-6 text-center">
        <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-rose-500/15">
          <Ban className="h-6 w-6 text-rose-400" />
        </div>
        <h1 className="text-lg font-bold text-slate-100">Acesso restrito</h1>
        <p className="mt-2 text-sm text-slate-400">{message}</p>
        <div className="mt-4 flex justify-center gap-2">
          {gate === "unauthenticated" ? (
            <a
              href="/pt/auth"
              className="inline-block rounded-lg bg-indigo-500 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-400"
            >
              Fazer login
            </a>
          ) : null}
          <a
            href="/"
            className="inline-block rounded-lg border border-white/10 px-4 py-2 text-sm font-semibold text-slate-300 hover:bg-white/5"
          >
            Voltar ao início
          </a>
        </div>
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
  const [phoneSamples, setPhoneSamples] = useState<AdminPhoneSampleProgress | null>(null);
  const [push, setPush] = useState<AdminPushMetrics | null>(null);
  const [digestAb, setDigestAb] = useState<AdminDigestAb | null>(null);
  const [planner, setPlanner] = useState<AdminPlannerMetrics | null>(null);
  const [creditLedger, setCreditLedger] = useState<AdminCreditLedgerResponse | null>(null);
  const [creditBalance, setCreditBalance] = useState<AdminCreditBalance | null>(null);
  const [sessions, setSessions] = useState<AdminSession[]>([]);
  const [revoking, setRevoking] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [pushTest, setPushTest] = useState<{ state: "idle" | "sending" | "ok" | "error"; message?: string }>(
    { state: "idle" }
  );

  const load = useCallback(async () => {
    setBusy(true);
    try {
      // searchbug falha isoladamente: a telemetria é secundária e não deve
      // apagar o resto do painel.
      const sb = fetchAdminSearchbug(7, 25).catch(() => null);
      const ps = fetchAdminPhoneSampleProgress(90).catch(() => null);
      const pu = fetchAdminPush(7, 25).catch(() => null);
      const ab = fetchAdminDigestAb(30).catch(() => null);
      const pl = fetchAdminPlanner().catch(() => null);
      const cl = fetchAdminCreditLedger(1, 50).catch(() => null);
      const cb = fetchAdminCreditBalance(1).catch(() => null);
      const ss = fetchAdminSessions(200).catch(() => null);
      const [ov, src, rn, rv, al, sbm, psm, pum, abm, plm, clm, cbm, ssm] = await Promise.all([
        fetchAdminOverview(),
        fetchAdminSources(),
        fetchAdminScraperRuns(15),
        fetchAdminReveals(50, true),
        fetchAdminAlerts(20),
        sb,
        ps,
        pu,
        ab,
        pl,
        cl,
        cb,
        ss,
      ]);
      setOverview(ov);
      setSources(src);
      setRuns(rn.runs);
      setReveals(rv.reveals);
      setAlerts(al.alerts);
      setSearchbug(sbm);
      setPhoneSamples(psm);
      setPush(pum);
      setDigestAb(abm);
      setPlanner(plm);
      setCreditLedger(clm);
      setCreditBalance(cbm);
      setSessions(ssm?.sessions ?? []);
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

  const hasToken =
    typeof window !== "undefined" && !!window.localStorage.getItem(AUTH_TOKEN_KEY);

  const testPush = useCallback(async () => {
    setPushTest({ state: "sending" });
    try {
      const res = await sendAdminTestPush({
        title: "Magic Leads - Teste",
        body: "Se vês isto, as push notifications estão a funcionar neste dispositivo.",
        url: "/dashboard",
      });
      setPushTest({
        state: "ok",
        message: `Aceite para ${res.sent}/${res.subscriptions} dispositivo(s) deste admin.`,
      });
    } catch (e) {
      const msg =
        e instanceof AdminApiError
          ? e.status === 404
            ? "Este browser não está subscrito a notificações. Ativa-as primeiro."
            : e.message
          : "Falha ao enviar o push de teste.";
      setPushTest({ state: "error", message: msg });
    }
  }, []);

  const revokeOne = useCallback(async (sessionId: number) => {
    if (!window.confirm("Revogar esta sessão? O dispositivo cai no próximo pedido.")) return;
    setRevoking(sessionId);
    try {
      await revokeAdminSession(sessionId);
      setSessions((prev) => prev.filter((s) => s.id !== sessionId));
    } catch (e) {
      window.alert(
        e instanceof AdminApiError ? e.message : "Não foi possível revogar a sessão."
      );
    } finally {
      setRevoking(null);
    }
  }, []);

  const revokeAllFromUser = useCallback(
    async (userId: number, email: string) => {
      if (!window.confirm(`Terminar TODAS as sessões de ${email}?`)) return;
      setRevoking(-1);
      try {
        await revokeAdminUserSessions(userId);
        setSessions((prev) => prev.filter((s) => s.user_id !== userId));
      } catch (e) {
        window.alert(
          e instanceof AdminApiError ? e.message : "Não foi possível revogar as sessões."
        );
      } finally {
        setRevoking(null);
      }
    },
    []
  );

  if (gate !== "ok") return <GateScreen gate={gate} hasToken={hasToken} />;

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

      {/* ------------------------------------------------------ outbound */}
      <OutboundPanel />
      <BillingFunnelPanel />

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
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-7">
              <Kpi
                label="Consultas pagas"
                value={searchbug.totals.billed_calls}
                sub={`hoje: ${searchbug.today.billed_calls}`}
              />
              <Kpi
                label="Custo (7d)"
                value={`$${Number(searchbug.totals.cost_usd ?? 0).toFixed(2)}`}
                sub={`hoje: $${Number(searchbug.today.cost_usd ?? 0).toFixed(2)}`}
              />
              <Kpi
                label="Custo/telefone"
                value={
                  searchbug.cost_per_success === null
                    ? "—"
                    : `$${searchbug.cost_per_success.toFixed(2)}`
                }
                sub={`${searchbug.totals.successes} telefones`}
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

            {searchbug.totals.transport_errors > 0 || searchbug.totals.name_mismatches > 0 ? (
              <p className="rounded-lg border border-sky-500/30 bg-sky-500/5 px-3 py-2 text-[11px] text-sky-300">
                {searchbug.totals.transport_errors} falha(s) de transporte (não faturadas) ·{" "}
                {searchbug.totals.name_mismatches} nome(s) não correspondido(s) — telefone não entregue.
              </p>
            ) : null}

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
                        <th className="py-1">Custo</th>
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
                          <td className="py-1.5 text-slate-400">
                            ${Number(c.cost_usd ?? 0).toFixed(2)}
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
                        <th className="py-1">Custo</th>
                        <th className="py-1">Match</th>
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
                            ${Number(r.cost_usd ?? 0).toFixed(2)}
                          </td>
                          <td className="py-1 text-slate-400">
                            {r.name_match === null ? "—" : r.name_match.toFixed(2)}
                          </td>
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

      {/* ------------------------------------------- calibração P2 */}
      <Card
        title="Calibração da confiança (telefone)"
        icon={<Phone className="h-4 w-4" />}
        hint={`amostras dos últimos ${phoneSamples?.days ?? 90} dias`}
      >
        {!phoneSamples ? (
          <p className="text-xs text-slate-500">
            Progresso indisponível. O cartão do cliente não mostra percentagem até
            haver amostras suficientes.
          </p>
        ) : phoneSamples.segments.length === 0 ? (
          <p className="text-xs text-slate-500">
            Sem consultas reais no período. O cartão mostra a percentagem assim que um
            segmento atingir {phoneSamples.min_samples} amostras.
          </p>
        ) : (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <Kpi
                label="Segmentos prontos"
                value={`${phoneSamples.ready_segments}/${phoneSamples.total_segments}`}
                sub={`≥ ${phoneSamples.min_samples} amostras`}
              />
              <Kpi
                label="Amostras (90d)"
                value={phoneSamples.total_samples}
                sub="tentativas reais"
              />
              <Kpi
                label="Menor amostra"
                value={
                  phoneSamples.segments.length
                    ? Math.min(...phoneSamples.segments.map((s) => s.samples))
                    : 0
                }
                sub="por segmento"
              />
              <Kpi
                label="Maior amostra"
                value={
                  phoneSamples.segments.length
                    ? Math.max(...phoneSamples.segments.map((s) => s.samples))
                    : 0
                }
                sub="por segmento"
              />
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="text-[10px] uppercase tracking-wider text-slate-500">
                  <tr>
                    <th className="py-1">Segmento</th>
                    <th className="py-1">Progresso</th>
                    <th className="py-1">Amostras</th>
                    <th className="py-1">%</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/5">
                  {phoneSamples.segments.map((s) => {
                    const pct = Math.min(
                      100,
                      Math.round((s.samples / phoneSamples.min_samples) * 100)
                    );
                    return (
                      <tr key={`${s.city}-${s.owner_class}`}>
                        <td className="py-2 text-slate-300">
                          {s.city} <span className="text-slate-500">· {s.owner_class}</span>
                        </td>
                        <td className="py-2 pr-3">
                          <div className="h-1.5 w-32 overflow-hidden rounded-full bg-white/10">
                            <div
                              className={`h-full rounded-full ${
                                s.ready ? "bg-emerald-500" : "bg-amber-500"
                              }`}
                              style={{ width: `${pct}%` }}
                            />
                          </div>
                        </td>
                        <td className="py-2 font-mono text-slate-400">
                          {s.samples}/{phoneSamples.min_samples}
                        </td>
                        <td className="py-2">
                          {s.ready ? (
                            <span className="text-emerald-400">{s.pct}%</span>
                          ) : (
                            <span className="text-slate-500">faltam {s.needed}</span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {phoneSamples.by_class.length > 0 ? (
              <div>
                <h3 className="mb-1.5 text-[10px] uppercase tracking-wider text-slate-500">
                  Por classe (todas as cidades) — usado como fallback
                </h3>
                <div className="flex flex-wrap gap-1.5">
                  {phoneSamples.by_class.map((c) => (
                    <span
                      key={c.owner_class}
                      className={`rounded-md border px-2 py-1 font-mono text-[11px] ${
                        c.ready
                          ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-400"
                          : "border-white/10 bg-white/[0.02] text-slate-400"
                      }`}
                    >
                      {c.owner_class}{" "}
                      <span className="opacity-70">
                        {c.samples}/{phoneSamples.min_samples}
                        {c.ready ? ` · ${c.pct}%` : ""}
                      </span>
                    </span>
                  ))}
                </div>
              </div>
            ) : null}

            <p className="text-[11px] leading-relaxed text-slate-500">
              A percentagem só é publicada no cartão quando o segmento
              (cidade + classe) ou a classe global atinge {phoneSamples.min_samples}{" "}
              consultas reais. Cache, guards e falhas de transporte não contam como
              amostra.
            </p>
          </div>
        )}
      </Card>

      {/* ------------------------------------------------------ push */}
      <Card
        title="Saúde das push notifications"
        icon={<BellRing className="h-4 w-4" />}
        hint={push ? `últimos ${push.days} dias` : undefined}
      >
        <div className="mb-4 flex flex-wrap items-center gap-3 rounded-lg border border-white/10 bg-white/[0.02] px-3 py-2.5">
          <div className="mr-auto text-xs text-slate-400">
            Envia uma notificação de teste para os dispositivos subscritos desta conta de admin.
          </div>
          <button
            onClick={() => void testPush()}
            disabled={pushTest.state === "sending"}
            className="inline-flex items-center gap-2 rounded-lg bg-indigo-500 px-3 py-2 text-xs font-semibold text-white hover:bg-indigo-400 disabled:opacity-50"
          >
            {pushTest.state === "sending" ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <BellRing className="h-3.5 w-3.5" />
            )}
            Enviar push de teste
          </button>
          {pushTest.state === "ok" ? (
            <span className="text-[11px] font-semibold text-emerald-400">{pushTest.message}</span>
          ) : null}
          {pushTest.state === "error" ? (
            <span className="text-[11px] font-semibold text-rose-400">{pushTest.message}</span>
          ) : null}
        </div>
        {!push ? (
          <p className="text-xs text-slate-500">
            Sem telemetria de push. O buffer também regista tentativas bloqueadas
            (sem VAPID, push desligado ou sem dispositivo subscrito).
          </p>
        ) : (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
              <Kpi
                label="Subscrições mortas"
                value={push.totals.expired}
                sub={`hoje: ${push.today.expired} · ${push.live_subscriptions}/${push.total_subscriptions} ativas`}
              />
              <Kpi
                label="Aceites (não entregues)"
                value={push.totals.accepted}
                sub={`hoje: ${push.today.accepted}`}
              />
              <Kpi
                label="Cliques"
                value={push.totals.clicks ?? 0}
                sub="notificações abertas"
              />
              <Kpi
                label="CTR"
                value={push.ctr === null ? "—" : `${Math.round(push.ctr * 100)}%`}
                sub="cliques / aceites"
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

            {push.totals.no_subscriptions > 0 ? (
              <p className="rounded-lg bg-amber-500/10 px-3 py-2 text-[11px] text-amber-300">
                {push.totals.no_subscriptions} tentativa(s) para utilizador(es) com push ligado
                mas nenhum dispositivo subscrito. O utilizador tem de ativar as notificações
                no browser/PWA — não é falha de entrega.
              </p>
            ) : null}

            {push.totals.rejected_dead > 0 ? (
              <p className="rounded-lg bg-rose-500/10 px-3 py-2 text-[11px] text-rose-300">
                {push.totals.rejected_dead} subscrição(ões) com VAPID inválido (401/403) removida(s)
                da base — estavam a acumular tentativas que nunca entregariam nada.
              </p>
            ) : null}

            {push.dlq && (push.dlq.dropped > 0 || push.dlq.pending > 0) ? (
              <p className="rounded-lg bg-amber-500/10 px-3 py-2 text-[11px] text-amber-300">
                DLQ de notificações in-app: {push.dlq.pending} pendente(s) e {push.dlq.dropped}{" "}
                descartado(s) por retenção (ring buffer).
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

      {/* ------------------------------------------------ digest A/B (B3) */}
      <Card
        title="Digest · teste A/B"
        icon={<FlaskConical className="h-4 w-4" />}
        hint={digestAb ? `últimos ${digestAb.days} dias` : undefined}
      >
        {!digestAb || digestAb.arms.length === 0 ? (
          <p className="text-xs text-slate-500">
            Sem digests suficientes para comparar variantes.
          </p>
        ) : (
          <div className="space-y-3">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="text-[10px] uppercase tracking-wider text-slate-500">
                  <tr>
                    <th className="py-1">Variante</th>
                    <th className="py-1">Criados</th>
                    <th className="py-1">Com push</th>
                    <th className="py-1">Cliques</th>
                    <th className="py-1">CTR</th>
                    <th className="py-1">Amostra</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/5">
                  {digestAb.arms.map((a) => (
                    <tr key={a.variant}>
                      <td className="py-1 font-mono uppercase text-slate-300">
                        {a.variant}
                        {digestAb.leader === a.variant ? (
                          <span className="ml-2 rounded bg-emerald-500/15 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-300">
                            líder
                          </span>
                        ) : null}
                      </td>
                      <td className="py-1 text-slate-400">{a.sent}</td>
                      <td className="py-1 text-slate-400">{a.pushed}</td>
                      <td className="py-1 text-slate-400">{a.clicks}</td>
                      <td className="py-1 text-indigo-300">
                        {a.ctr === null ? "—" : `${Math.round(a.ctr * 100)}%`}
                      </td>
                      <td className="py-1">
                        {a.sample_ok ? (
                          <span className="text-emerald-400">ok</span>
                        ) : (
                          <span className="text-amber-400">
                            {a.pushed}/{digestAb.min_samples}
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="text-[11px] text-slate-500">
              {digestAb.leader
                ? `Variante ${digestAb.leader.toUpperCase()} à frente com amostra suficiente.`
                : `Sem vencedor declarado: são necessários ${digestAb.min_samples} envios com push por braço.`}{" "}
              CTR = cliques / digests com push entregue.
            </p>
          </div>
        )}
      </Card>

      {/* ------------------------------------------------ alert planner */}
      <Card
        title="Alert Planner · hoje"
        icon={<Activity className="h-4 w-4" />}
        hint={planner ? `${planner.day} (UTC) · teto ${planner.limit}/utilizador` : undefined}
      >
        {!planner ? (
          <p className="text-xs text-slate-500">Sem telemetria do Alert Planner.</p>
        ) : (
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <Kpi label="Alertas hoje" value={planner.alerts_today} sub="orçamento combinado" />
              <Kpi label="Utilizadores ativos" value={planner.users_active} sub="consumiram vaga hoje" />
              <Kpi label="No teto" value={planner.users_at_cap} sub={`>= ${planner.limit} alertas`} />
              <Kpi label="Digests hoje" value={planner.digests_today} sub="excedente (não conta no teto)" />
            </div>

            {planner.by_category.length > 0 ? (
              <div className="space-y-1">
                <h3 className="text-[10px] uppercase tracking-wider text-slate-500">Por categoria</h3>
                {planner.by_category.map((c) => {
                  const max = Math.max(...planner.by_category.map((x) => x.alerts), 1);
                  return (
                    <div key={c.category} className="flex items-center gap-2 text-xs">
                      <span className="w-28 shrink-0 truncate font-mono text-slate-400" title={c.category}>
                        {c.category}
                      </span>
                      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-white/5">
                        <div
                          className="h-full rounded-full bg-indigo-500/70"
                          style={{ width: `${(c.alerts / max) * 100}%` }}
                        />
                      </div>
                      <span className="w-8 shrink-0 text-right text-slate-500">{c.alerts}</span>
                    </div>
                  );
                })}
              </div>
            ) : (
              <p className="text-xs text-slate-500">Sem alertas despachados hoje.</p>
            )}
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

      {/* -------------------------------------------------- concessão */}
      <AccessGrantPanel />

      {/* -------------------------------------------------- sessões */}
      <Card
        title="Sessões ativas"
        icon={<ShieldAlert className="h-4 w-4" />}
        hint={`${sessions.length} dispositivo(s)`}
      >
        <div data-testid="admin-sessions">
          {sessions.length === 0 ? (
            <p className="text-xs text-slate-500">Sem sessões ativas.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="text-[10px] uppercase tracking-wider text-slate-500">
                  <tr>
                    <th className="py-1.5">Utilizador</th>
                    <th className="py-1.5">Dispositivo</th>
                    <th className="py-1.5">IP</th>
                    <th className="py-1.5">Última atividade</th>
                    <th className="py-1.5">Expira</th>
                    <th className="py-1.5 text-right">Ações</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/5">
                  {sessions.map((s) => (
                    <tr key={s.id}>
                      <td className="py-1.5">
                        <div className="font-medium text-slate-200">{s.email}</div>
                        <div className="text-[10px] text-slate-500">
                          {s.company_name || "—"}
                          {s.is_admin ? " · admin" : ""}
                        </div>
                      </td>
                      <td className="py-1.5 text-slate-400">{s.device_info || "—"}</td>
                      <td className="py-1.5 font-mono text-[11px] text-slate-400">
                        {s.ip_address || "—"}
                      </td>
                      <td className="py-1.5 text-slate-400">{fmtDt(s.last_active_at)}</td>
                      <td className="py-1.5 text-slate-400">{fmtDt(s.expires_at)}</td>
                      <td className="py-1.5 text-right">
                        <div className="flex justify-end gap-1.5">
                          <button
                            onClick={() => void revokeOne(s.id)}
                            disabled={revoking !== null}
                            className="rounded-md border border-rose-500/30 px-2 py-1 text-[11px] font-semibold text-rose-300 hover:bg-rose-500/10 disabled:opacity-50"
                          >
                            {revoking === s.id ? "…" : "Revogar"}
                          </button>
                          <button
                            onClick={() => void revokeAllFromUser(s.user_id, s.email)}
                            disabled={revoking !== null}
                            title="Terminar todas as sessões deste utilizador"
                            className="rounded-md border border-white/10 px-2 py-1 text-[11px] font-semibold text-slate-300 hover:bg-white/5 disabled:opacity-50"
                          >
                            Todas
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p className="mt-2 text-[10px] text-slate-600">
            A revogação apaga a sessão na hora; o dispositivo perde acesso no pedido
            seguinte (401). Expiração padrão: 30 dias de inatividade.
          </p>
        </div>
      </Card>

      <footer className="flex items-center gap-2 pt-2 text-[11px] text-slate-600">
        <Users className="h-3 w-3" />
        Push e Searchbug medem custo e entrega através de buffer próprio: uma falha de escrita
        nunca affecta um pedido de utilizador. As duas métricas entram no painel sem transacção
        no caminho crítico.
      </footer>
    </div>
  );
}

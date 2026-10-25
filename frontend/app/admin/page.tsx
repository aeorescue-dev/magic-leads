"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Activity,
  AlertTriangle,
  Ban,
  BellRing,
  CheckCircle2,
  Database,
  Languages,
  Loader2,
  Mail,
  RefreshCcw,
  Search,
  Send,
  SendHorizontal,
  ShieldAlert,
  Sparkles,
  Users,
  Wallet,
} from "lucide-react";

import {
  AdminAlert,
  AdminApiError,
  AdminOutboundConfigResponse,
  AdminOutboundPreview,
  AdminOutboundSimulation,
  AdminOutboundStatus,
  AdminOverview,
  AdminPlannerMetrics,
  AdminPushMetrics,
  AdminReveal,
  AdminScraperRun,
  AdminSearchbugMetrics,
  AdminSources,
    AdminCreditBackfillResponse,
    AdminCreditBalance,
    AdminCreditLedgerEvent,
    AdminCreditLedgerResponse,
    AdminCreditReconcileResponse,
  fetchAdminAlerts,
  fetchAdminOutboundConfig,
  fetchAdminOutboundStatus,
  fetchAdminOverview,
  fetchAdminPlanner,
  fetchAdminPush,
  fetchAdminReveals,
  fetchAdminScraperRuns,
  fetchAdminSearchbug,
  fetchAdminSources,
    fetchAdminCreditBalance,
    fetchAdminCreditBackfill,
    fetchAdminCreditLedger,
    fetchAdminCreditReconcile,
  generateAdminOutboundPreview,
  sendAdminOutbound,
  sendAdminTestPush,
  simulateAdminOutbound,
  triggerAdminOutboundWorker,
  updateAdminOutboundConfig,
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
  const d = new Date(value.includes("T") ? value : value.replace(" ", "T"));
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
  const [toggling, setToggling] = useState(false);

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

  useEffect(() => {
    void loadConfig();
  }, [loadConfig]);

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
            {status ? (
              <span className="ml-auto text-[11px] text-slate-500">
                fila {status.queued} · enviados hoje {status.sent_today} · enriquecidos{" "}
                {status.enriched_today} · {fmtUsd(status.spend_today_usd)}
              </span>
            ) : null}
          </div>
          <p className="text-[10px] text-slate-600">
            Envio real pela Gmail API com warm-up por caixa, tetos diários e quiet hours (UTC).
            EmailListVerify {status?.enrichment_configured ? "configurado" : "não configurado"}.
            {status?.quiet_hours_now ? " Agora em quiet hours — o worker não envia." : ""}
            {status && status.mailboxes.length === 0
              ? " Sem caixas de envio configuradas — o envio fica em espera."
              : ""}
          </p>
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
  const [push, setPush] = useState<AdminPushMetrics | null>(null);
  const [planner, setPlanner] = useState<AdminPlannerMetrics | null>(null);
  const [creditLedger, setCreditLedger] = useState<AdminCreditLedgerResponse | null>(null);
  const [creditBalance, setCreditBalance] = useState<AdminCreditBalance | null>(null);
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
      const pu = fetchAdminPush(7, 25).catch(() => null);
      const pl = fetchAdminPlanner().catch(() => null);
      const cl = fetchAdminCreditLedger(1, 50).catch(() => null);
      const cb = fetchAdminCreditBalance(1).catch(() => null);
      const [ov, src, rn, rv, al, sbm, pum, plm, clm, cbm] = await Promise.all([
        fetchAdminOverview(),
        fetchAdminSources(),
        fetchAdminScraperRuns(15),
        fetchAdminReveals(50, true),
        fetchAdminAlerts(20),
        sb,
        pu,
        pl,
        cl,
        cb,
      ]);
      setOverview(ov);
      setSources(src);
      setRuns(rn.runs);
      setReveals(rv.reveals);
      setAlerts(al.alerts);
      setSearchbug(sbm);
      setPush(pum);
      setPlanner(plm);
      setCreditLedger(clm);
      setCreditBalance(cbm);
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

      <footer className="flex items-center gap-2 pt-2 text-[11px] text-slate-600">
        <Users className="h-3 w-3" />
        Push e Searchbug medem custo e entrega através de buffer próprio: uma falha de escrita
        nunca affecta um pedido de utilizador. As duas métricas entram no painel sem transacção
        no caminho crítico.
      </footer>
    </div>
  );
}

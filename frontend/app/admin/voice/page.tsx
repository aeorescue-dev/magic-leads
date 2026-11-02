"use client";

import {
  AlertTriangle,
  ArrowLeft,
  Ban,
  Building2,
  CalendarClock,
  CheckCircle2,
  Cloud,
  Database,
  Gauge,
  Globe2,
  Link2,
  Loader2,
  MapPin,
  Phone,
  PhoneCall,
  PhoneOutgoing,
  Play,
  Plus,
  RefreshCcw,
  Rocket,
  ShieldCheck,
  Square,
  Upload,
  Users,
  X,
} from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import useSWR from "swr";

import {
  AdminApiError,
  buildShowcasePages,
  checkVoiceDnc,
  createVoiceSource,
  dialVoiceContact,
  downloadVoiceTemplate,
  fetchShowcaseStats,
  fetchVoiceCampaigns,
  fetchVoiceMetrics,
  fetchVoiceQueue,
  fetchVoiceSegments,
  fetchVoiceSources,
  fetchVoiceStats,
  importVoiceDnc,
  ingestVoice,
  logVoiceCall,
  resumeVoiceCampaign,
  sendVoiceShowcase,
  startVoiceCampaign,
  stopVoiceCampaign,
  suppressVoicePhone,
  syncLicensingSources,
  syncVoiceSource,
  type VoiceCampaign,
  type VoiceCompany,
  type VoiceMetrics,
  type VoiceSegment,
  type VoiceSource,
} from "@/lib/admin-api";
import { fmtWhen } from "@/lib/system-health";

type VoiceTab = "overview" | "campaigns" | "segments" | "sources";

const VOICE_TABS: Array<{ id: VoiceTab; label: string }> = [
  { id: "overview", label: "Visão Geral" },
  { id: "campaigns", label: "Campanhas" },
  { id: "segments", label: "Segmentos" },
  { id: "sources", label: "Fontes" },
];

const OUTCOMES: Array<{ value: string; label: string }> = [
  { value: "connected", label: "Falou com responsável" },
  { value: "voicemail", label: "Voicemail" },
  { value: "no_answer", label: "Sem resposta" },
  { value: "busy", label: "Ocupado" },
  { value: "callback", label: "Pediu callback" },
  { value: "meeting_booked", label: "Reunião marcada" },
  { value: "not_interested", label: "Sem interesse (suprimir)" },
  { value: "wrong_number", label: "Número errado (suprimir)" },
  { value: "do_not_call", label: "Não contactar (suprimir)" },
];

const money0 = (value: number) =>
  new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(value);

function cn(...values: Array<string | false | null | undefined>) {
  return values.filter(Boolean).join(" ");
}

type Tone = "slate" | "indigo" | "emerald" | "amber" | "rose" | "sky";

const TONES: Record<Tone, string> = {
  slate: "border-white/10 bg-white/5 text-slate-300",
  indigo: "border-indigo-400/25 bg-indigo-500/10 text-indigo-200",
  emerald: "border-emerald-400/25 bg-emerald-500/10 text-emerald-200",
  amber: "border-amber-400/25 bg-amber-500/10 text-amber-200",
  rose: "border-rose-400/25 bg-rose-500/10 text-rose-200",
  sky: "border-sky-400/25 bg-sky-500/10 text-sky-200",
};

function Badge({ children, tone = "slate" }: { children: ReactNode; tone?: Tone }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-semibold",
        TONES[tone]
      )}
    >
      {children}
    </span>
  );
}

function Card({
  title,
  icon,
  hint,
  action,
  children,
  className,
}: {
  title: string;
  icon: ReactNode;
  hint?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("rounded-2xl border border-white/10 bg-[#10131a] p-4", className)}>
      <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="flex items-center gap-2 text-sm font-bold text-slate-100">
            {icon}
            {title}
          </h2>
          {hint ? <p className="mt-0.5 text-[11px] text-slate-500">{hint}</p> : null}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

function Stat({
  label,
  value,
  sub,
  tone = "slate",
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: Tone;
}) {
  return (
    <div className="rounded-xl border border-white/5 bg-white/[0.02] p-3">
      <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">
        {label}
      </p>
      <p
        className={cn(
          "mt-1 text-xl font-black tabular-nums",
          tone === "emerald"
            ? "text-emerald-300"
            : tone === "amber"
              ? "text-amber-300"
              : tone === "rose"
                ? "text-rose-300"
                : "text-slate-100"
        )}
      >
        {value}
      </p>
      {sub ? <p className="mt-0.5 text-[10px] text-slate-500">{sub}</p> : null}
    </div>
  );
}

function GateScreen({ status }: { status: number }) {
  return (
    <div className="flex min-h-screen items-center justify-center p-6">
      <div className="max-w-md rounded-2xl border border-white/10 bg-[#10131a] p-6 text-center">
        <ShieldCheck className="mx-auto mb-3 h-8 w-8 text-rose-400" />
        <h1 className="text-lg font-bold text-slate-100">
          {status === 403 ? "Sem permissão" : "Sessão expirada"}
        </h1>
        <p className="mt-2 text-sm text-slate-400">
          {status === 403
            ? "A tua conta não tem perfil de administrador."
            : "A tua sessão expirou. Volta a entrar."}
        </p>
        <div className="mt-4 flex justify-center gap-2">
          {status === 401 ? (
            <a href="/pt/auth" className="rounded-lg bg-indigo-500 px-4 py-2 text-sm font-semibold text-white">
              Fazer login
            </a>
          ) : null}
          <a href="/admin" className="rounded-lg border border-white/10 px-4 py-2 text-sm font-semibold text-slate-300">
            Voltar ao Admin
          </a>
        </div>
      </div>
    </div>
  );
}

export default function VoiceB2BPage() {
  const [includeBlocked, setIncludeBlocked] = useState(false);
  const [cityFilter, setCityFilter] = useState("");
  const [tradeFilter, setTradeFilter] = useState("");
  const [quotaTotal, setQuotaTotal] = useState(100);
  const [batchSize, setBatchSize] = useState(25);
  const [includeFallback, setIncludeFallback] = useState(true);
  const [tab, setTab] = useState<VoiceTab>("overview");
  const [sourceName, setSourceName] = useState("");
  const [sourceUrl, setSourceUrl] = useState("");
  const [selected, setSelected] = useState<VoiceCompany | null>(null);
  const [licenseCsv, setLicenseCsv] = useState("");
  const [licenseName, setLicenseName] = useState("MA HIC / licenças");
  const [licenseUrl, setLicenseUrl] = useState("");
  const [dncCsv, setDncCsv] = useState("");
  const [dncSource, setDncSource] = useState("manual_csv");
  const [working, setWorking] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [outcome, setOutcome] = useState("connected");
  const [notes, setNotes] = useState("");
  const [callbackAt, setCallbackAt] = useState("");

  const queueKey = `voice-queue-${includeBlocked}-${cityFilter}-${tradeFilter}`;
  const {
    data: queue,
    error,
    isLoading,
    mutate: mutateQueue,
  } = useSWR(queueKey, () => fetchVoiceQueue(includeBlocked, 250, cityFilter, tradeFilter), {
    refreshInterval: 60_000,
    revalidateOnFocus: true,
  });
  const { data: stats, mutate: mutateStats } = useSWR(
    "voice-stats",
    fetchVoiceStats,
    { refreshInterval: 60_000 }
  );
  const { data: showcaseStats, mutate: mutateShowcase } = useSWR(
    "showcase-stats",
    fetchShowcaseStats,
    { refreshInterval: 60_000 }
  );
  const { data: segmentsData, mutate: mutateSegments } = useSWR(
    "voice-segments",
    () => fetchVoiceSegments(),
    { refreshInterval: 60_000 }
  );
  const { data: campaignsData, mutate: mutateCampaigns } = useSWR(
    "voice-campaigns",
    () => fetchVoiceCampaigns(20),
    { refreshInterval: 5_000 }
  );
  const { data: metrics, mutate: mutateMetrics } = useSWR(
    "voice-metrics",
    () => fetchVoiceMetrics(30),
    { refreshInterval: 60_000 }
  );
  const { data: sourcesData, mutate: mutateSources } = useSWR(
    "voice-sources",
    fetchVoiceSources,
    { refreshInterval: 60_000 }
  );

  const refreshAll = async () => {
    await Promise.all([mutateQueue(), mutateStats()]);
  };

  const callable = useMemo(
    () => queue?.items.filter((item) => item.eligibility.allowed).length ?? 0,
    [queue]
  );

  if (error instanceof AdminApiError && (error.status === 401 || error.status === 403)) {
    return <GateScreen status={error.status} />;
  }

  const readFile = async (file: File | undefined, setter: (value: string) => void) => {
    if (!file) return;
    setter(await file.text());
  };

  const run = async (key: string, fn: () => Promise<string>) => {
    setWorking(key);
    setMessage(null);
    setErrorMsg(null);
    try {
      setMessage(await fn());
      await refreshAll();
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "Falha na operação.");
    } finally {
      setWorking(null);
    }
  };

  const ingestAndProcess = () =>
    run("licenses", async () => {
      if (!licenseCsv.trim()) throw new Error("Escolhe um CSV de licenças/permits.");
      const result = await ingestVoice(licenseCsv, licenseName, licenseUrl);
      setLicenseCsv("");
      await Promise.all([
        mutateQueue(),
        mutateStats(),
        mutateShowcase(),
        mutateSegments(),
      ]);
      return `Ingestão: ${result.import.imported} novas, ${
        result.import.updated ?? 0
      } atualizadas, ${result.import.skipped} ignoradas · ${
        result.showcase.published
      } páginas de vitrine · ${result.segments.length} segmentos cidade+nicho.`;
    });

  const startCampaign = (segment?: VoiceSegment) =>
    run("campaign-start", async () => {
      const city =
        segment && segment.city !== "—" ? segment.city : cityFilter || undefined;
      const trade =
        segment && segment.trade !== "—" ? segment.trade : tradeFilter || undefined;
      const result = await startVoiceCampaign({
        name: segment
          ? `Auto ${segment.city} ${segment.trade}`
          : city || trade
            ? `Auto ${city || "todas"} ${trade || "todos"}`
            : undefined,
        city,
        trade,
        quota_total: quotaTotal,
        batch_size: batchSize,
        include_fallback: segment ? true : includeFallback,
      });
      await Promise.all([
        mutateCampaigns(),
        mutateQueue(),
        mutateStats(),
        mutateMetrics(),
      ]);
      return `Campanha #${result.campaign.id} iniciada: cota ${result.campaign.quota_total ?? result.campaign.max_calls}, lote ${result.campaign.batch_size ?? result.campaign.max_calls} · ${
        city || "todas as cidades"
      } / ${trade || "todos os nichos"}.`;
    });

  const stopCampaign = (campaignId: number) =>
    run(`campaign-stop-${campaignId}`, async () => {
      await stopVoiceCampaign(campaignId);
      await mutateCampaigns();
      return `Campanha #${campaignId} parada.`;
    });

  const resumeCampaign = (campaignId: number) =>
    run(`campaign-resume-${campaignId}`, async () => {
      await resumeVoiceCampaign(campaignId);
      await mutateCampaigns();
      return `Campanha #${campaignId} retomada.`;
    });

  const addSource = () =>
    run("source-add", async () => {
      if (!sourceName.trim() || !sourceUrl.trim()) {
        throw new Error("Nome e URL https da fonte são obrigatórios.");
      }
      const result = await createVoiceSource({
        name: sourceName.trim(),
        kind: "http_csv",
        url: sourceUrl.trim(),
      });
      setSourceName("");
      setSourceUrl("");
      await mutateSources();
      return `Fonte #${result.source.id} criada. Sincroniza para importar.`;
    });

  const syncSource = (sourceId: number) =>
    run(`source-sync-${sourceId}`, async () => {
      const result = await syncVoiceSource(sourceId);
      await Promise.all([
        mutateSources(),
        mutateSegments(),
        mutateStats(),
        mutateShowcase(),
        mutateMetrics(),
      ]);
      if (!result.ok) {
        throw new Error(result.error || "Falha ao sincronizar fonte.");
      }
      return `Fonte #${sourceId} sincronizada.`;
    });

  const syncLicensing = () =>
    run("licensing-sync", async () => {
      const result = await syncLicensingSources();
      await Promise.all([
        mutateSources(),
        mutateSegments(),
        mutateStats(),
        mutateShowcase(),
        mutateMetrics(),
      ]);
      if (!result.ok) {
        throw new Error(result.error || "Falha ao sincronizar licenças.");
      }
      return `Licenças: ${result.import?.imported ?? 0} novas, ${
        result.import?.updated ?? 0
      } atualizadas · ${result.segments ?? 0} segmentos.`;
    });

  const importDnc = () =>
    run("dnc", async () => {
      if (!dncCsv.trim()) throw new Error("Escolhe um CSV DNC.");
      const result = await importVoiceDnc(dncCsv, dncSource);
      setDncCsv("");
      return `DNC: ${result.imported} números carregados, ${result.listed ?? 0} listados.`;
    });

  const markDnc = (listed: boolean) =>
    run("dnc-check", async () => {
      if (!selected) throw new Error("Sem empresa selecionada.");
      await checkVoiceDnc(selected.phone, listed, "manual_admin");
      setSelected(null);
      return listed
        ? "Número marcado como listado no DNC."
        : "Check DNC registado: número limpo.";
    });

  const suppress = () =>
    run("suppress", async () => {
      if (!selected) throw new Error("Sem empresa selecionada.");
      await suppressVoicePhone(selected.phone, "admin_manual");
      setSelected(null);
      return "Número suprimido. Não volta à fila.";
    });

  const submitCall = () =>
    run("call", async () => {
      if (!selected) throw new Error("Sem empresa selecionada.");
      const result = await logVoiceCall(selected.id, {
        outcome,
        notes,
        callback_at: callbackAt ? new Date(callbackAt).toISOString() : null,
      });
      setSelected(null);
      setNotes("");
      setCallbackAt("");
      setOutcome("connected");
      return `Chamada registada: ${result.status}.`;
    });

  const downloadTemplate = async () => {
    setErrorMsg(null);
    try {
      const blob = await downloadVoiceTemplate();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = "magic-leads-voice-template.csv";
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "Falha ao descarregar template.");
    }
  };

  const buildShowcase = () =>
    run("showcase-build", async () => {
      const result = await buildShowcasePages();
      await mutateShowcase();
      return `Vitrine: ${result.published} páginas publicadas de ${result.combos} combinações (mín. ${result.min_items} obras).`;
    });

  const sendShowcase = () =>
    run("showcase-send", async () => {
      if (!selected) throw new Error("Sem empresa selecionada.");
      const result = await sendVoiceShowcase(selected.id, {
        city: selected.city || undefined,
        trade: selected.trade || undefined,
      });
      if (!result.ok) {
        throw new Error(
          result.reason === "no_inventory"
            ? "Sem inventário suficiente para esta cidade/nicho."
            : result.reason || "Falha ao gerar vitrine."
        );
      }
      setSelected(null);
      const emailState = result.email?.sent
        ? "email enviado"
        : result.email?.dry_run
          ? "email em dry-run"
          : `email não enviado (${result.email?.reason || "sem canal"})`;
      return `Vitrine gerada: ${result.link?.url} · ${emailState}`;
    });

  const dialTelnyx = () =>
    run("dial", async () => {
      if (!selected) throw new Error("Sem empresa selecionada.");
      const result = await dialVoiceContact(selected.id, {
        city: selected.city || undefined,
        trade: selected.trade || undefined,
      });
      if (!result.ok) {
        throw new Error(
          result.reason_labels?.join(" · ") ||
            result.reason ||
            "Chamada bloqueada."
        );
      }
      setSelected(null);
      return result.dry_run
        ? `Chamada registada em dry-run (#${result.voice_call_id}).`
        : `Chamada Telnyx #${result.voice_call_id} (${result.status}).`;
    });

  return (
    <main className="mx-auto max-w-[1400px] px-4 py-6 text-slate-200">
      <header className="mb-5 flex flex-wrap items-end justify-between gap-3">
        <div>
          <a
            href="/admin"
            className="mb-1 inline-flex items-center gap-1 text-[11px] font-semibold text-slate-500 hover:text-slate-300"
          >
            <ArrowLeft className="h-3.5 w-3.5" /> Torre de Controlo
          </a>
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="flex items-center gap-2 text-2xl font-black tracking-tight text-white">
              <PhoneCall className="h-6 w-6 text-emerald-400" /> Voice B2B
            </h1>
            <Badge tone="indigo">Piloto {stats?.pilot_state ?? "MA"}</Badge>
            <Badge tone="slate">{stats?.calling_window ?? "08:00–21:00 ET"}</Badge>
          </div>
          <p className="mt-1 text-[11px] text-slate-500">
            Prospeção de pessoas jurídicas · gate can_call() fail-closed · DNC
            máximo {stats?.dnc_max_age_days ?? 31} dias
          </p>
        </div>
        <button
          type="button"
          onClick={() => void refreshAll()}
          className="inline-flex items-center gap-2 rounded-lg border border-white/10 px-3 py-2 text-xs font-semibold text-slate-300 hover:bg-white/5"
        >
          <RefreshCcw className="h-3.5 w-3.5" /> Refresh
        </button>
      </header>

      {message ? (
        <div className="mb-4 rounded-xl border border-emerald-400/20 bg-emerald-500/10 px-3 py-2 text-[11px] text-emerald-200">
          {message}
        </div>
      ) : null}
      {errorMsg ? (
        <div className="mb-4 rounded-xl border border-rose-400/20 bg-rose-500/10 px-3 py-2 text-[11px] text-rose-200">
          {errorMsg}
        </div>
      ) : null}

      <section className="mb-5 grid grid-cols-2 gap-3 md:grid-cols-6">
        <Stat label="Empresas" value={String(stats?.total ?? queue?.total ?? 0)} sub="pessoas jurídicas" />
        <Stat
          label="Chamáveis"
          value={String(stats?.callable ?? queue?.callable ?? callable)}
          tone="emerald"
          sub="passam o gate"
        />
        <Stat label="Bloqueadas" value={String(stats?.blocked ?? 0)} tone="amber" sub="com motivo" />
        <Stat label="Tentativas hoje" value={String(stats?.attempts_today ?? 0)} />
        <Stat label="Reuniões" value={String(stats?.meetings ?? 0)} tone="emerald" />
        <Stat label="DNC listados" value={String(stats?.dnc_listed ?? 0)} tone="rose" sub={`${stats?.dnc_checked ?? 0} checks`} />
      </section>

      <nav className="mb-5 inline-flex flex-wrap gap-1 rounded-xl border border-white/10 bg-white/[0.02] p-1">
        {VOICE_TABS.map((item) => (
          <button
            key={item.id}
            type="button"
            onClick={() => setTab(item.id)}
            className={cn(
              "rounded-lg px-4 py-1.5 text-[11px] font-semibold transition-colors",
              tab === item.id
                ? "bg-emerald-500 text-[#052018]"
                : "text-slate-400 hover:text-slate-200"
            )}
          >
            {item.label}
          </button>
        ))}
      </nav>

      <Card
        title="Visão executiva do funil"
        icon={<Gauge className="h-4 w-4 text-emerald-400" />}
        hint="Últimos 30 dias · voz → clique → checkout → receita"
        action={<Badge tone="slate">30 dias</Badge>}
        className={tab === "overview" ? "" : "hidden"}
      >
        <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
          <Stat
            label="Answer Rate"
            value={`${metrics?.summary.answer_rate ?? 0}%`}
            sub={`${metrics?.summary.answered ?? 0}/${metrics?.summary.dialed ?? 0} atendidas`}
            tone="emerald"
          />
          <Stat
            label="Engagement ≥30s"
            value={`${metrics?.summary.engagement_rate ?? 0}%`}
            sub={`${metrics?.summary.engaged ?? 0} chamadas`}
            tone="emerald"
          />
          <Stat
            label="Showcase CTR"
            value={`${metrics?.summary.showcase_ctr ?? 0}%`}
            sub={`${metrics?.summary.clicks ?? 0} cliques`}
            tone="emerald"
          />
          <Stat
            label="Checkout Rate"
            value={`${metrics?.summary.checkout_rate ?? 0}%`}
            sub={`${metrics?.summary.checkouts ?? 0} checkouts`}
            tone="emerald"
          />
        </div>
        <div className="mt-2 grid grid-cols-2 gap-2 md:grid-cols-4">
          <Stat
            label="Listen médio"
            value={`${metrics?.summary.avg_listen_seconds ?? 0}s`}
            sub="chamadas atendidas"
          />
          <Stat
            label="Receita"
            value={money0(metrics?.summary.revenue_usd ?? 0)}
            tone="emerald"
          />
          <Stat
            label="Custo"
            value={money0(metrics?.summary.cost_usd ?? 0)}
            tone="amber"
          />
          <Stat
            label="Net"
            value={money0(metrics?.summary.net_usd ?? 0)}
            tone={(metrics?.summary.net_usd ?? 0) >= 0 ? "emerald" : "rose"}
          />
        </div>
        {!metrics?.summary.dialed ? (
          <p className="mt-3 text-[10px] text-slate-600">
            Sem chamadas no período. Inicia uma campanha em “Campanhas” para
            alimentar o funil.
          </p>
        ) : null}
      </Card>

      <div
        className={cn(
          "mb-5 grid gap-4 lg:grid-cols-2",
          tab === "sources" ? "" : "hidden"
        )}
      >
        <Card
          title="1. Importar licenças / permits"
        className="hidden"
          icon={<Upload className="h-4 w-4 text-indigo-400" />}
          hint="CSV de Massachusetts (HIC, trades ou permits). Dedupe por telefone."
        >
          <input
            type="file"
            accept=".csv,text/csv"
            onChange={(event) => void readFile(event.target.files?.[0], setLicenseCsv)}
            className="mb-2 block w-full text-[11px] text-slate-400 file:mr-2 file:rounded-lg file:border-0 file:bg-indigo-500/15 file:px-3 file:py-1.5 file:text-[11px] file:font-semibold file:text-indigo-200"
          />
          <div className="grid gap-2 sm:grid-cols-2">
            <input
              value={licenseName}
              onChange={(event) => setLicenseName(event.target.value)}
              placeholder="Nome da fonte"
              className="rounded-lg border border-white/10 bg-black/20 px-2.5 py-1.5 text-[11px] text-slate-200 placeholder:text-slate-600"
            />
            <input
              value={licenseUrl}
              onChange={(event) => setLicenseUrl(event.target.value)}
              placeholder="URL da fonte (opcional)"
              className="rounded-lg border border-white/10 bg-black/20 px-2.5 py-1.5 text-[11px] text-slate-200 placeholder:text-slate-600"
            />
          </div>
          <div className="mt-2 flex items-center justify-between gap-2">
            <button
              type="button"
              onClick={() => void downloadTemplate()}
              className="text-[10px] font-semibold text-indigo-300 hover:text-indigo-200"
            >
              Descarregar template CSV
            </button>
            <button
              type="button"
              onClick={() => void ingestAndProcess()}
              disabled={working === "licenses"}
              className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-500 px-3 py-1.5 text-[11px] font-bold text-white hover:bg-indigo-400 disabled:opacity-50"
            >
              {working === "licenses" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Upload className="h-3.5 w-3.5" />}
              Importar e processar
            </button>
          </div>
          <p className="mt-2 text-[10px] text-slate-600">
            Colunas: company_name, phone, contact_name, city, state, license_number,
            license_status, trade, permit_count, permit_value_usd, years_active,
            employee_estimate.
          </p>
        </Card>

        <Card
          title="2. Importar lista DNC"
          icon={<ShieldCheck className="h-4 w-4 text-emerald-400" />}
          hint="Sem check DNC fresco, a empresa fica bloqueada (fail-closed)."
        >
          <input
            type="file"
            accept=".csv,text/csv"
            onChange={(event) => void readFile(event.target.files?.[0], setDncCsv)}
            className="mb-2 block w-full text-[11px] text-slate-400 file:mr-2 file:rounded-lg file:border-0 file:bg-emerald-500/15 file:px-3 file:py-1.5 file:text-[11px] file:font-semibold file:text-emerald-200"
          />
          <div className="flex items-center gap-2">
            <input
              value={dncSource}
              onChange={(event) => setDncSource(event.target.value)}
              placeholder="Fonte do DNC"
              className="flex-1 rounded-lg border border-white/10 bg-black/20 px-2.5 py-1.5 text-[11px] text-slate-200 placeholder:text-slate-600"
            />
            <button
              type="button"
              onClick={() => void importDnc()}
              disabled={working === "dnc"}
              className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-500 px-3 py-1.5 text-[11px] font-bold text-[#062017] hover:bg-emerald-400 disabled:opacity-50"
            >
              {working === "dnc" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ShieldCheck className="h-3.5 w-3.5" />}
              Importar DNC
            </button>
          </div>
          <p className="mt-2 text-[10px] text-slate-600">
            Formato: phone, listed (1/0). Para um único número, abre a empresa na
            fila e usa “DNC limpo” ou “DNC listado”.
          </p>
        </Card>
      </div>

      <Card
        title="2. Fontes de dados"
        icon={<Cloud className="h-4 w-4 text-sky-400" />}
        hint="Sincronização automática de licenças/permits. Sem upload manual no fluxo do operador."
        action={<Badge tone="slate">HTTPS + allowlist</Badge>}
        className={tab === "sources" ? "" : "hidden"}
      >
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-emerald-400/20 bg-emerald-500/[0.06] p-3">
          <div>
            <p className="text-[11px] font-bold text-emerald-200">
              Base de licenças já ingerida
            </p>
            <p className="text-[10px] text-slate-500">
              Converte `contractor_entities` (NY/TX/IL/MA) em empresas da fila,
              com dedupe, trade inferido, rebuild da vitrine e segmentos.
            </p>
          </div>
          <button
            type="button"
            onClick={() => void syncLicensing()}
            disabled={working === "licensing-sync"}
            className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-500 px-3 py-1.5 text-[11px] font-bold text-[#062017] hover:bg-emerald-400 disabled:opacity-50"
          >
            {working === "licensing-sync" ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Database className="h-3.5 w-3.5" />
            )}
            Sincronizar licenças existentes
          </button>
        </div>
        <div className="mb-3 grid gap-2 sm:grid-cols-[1fr_1.4fr_auto]">
          <input
            value={sourceName}
            onChange={(event) => setSourceName(event.target.value)}
            placeholder="Nome da fonte"
            className="rounded-lg border border-white/10 bg-black/20 px-2.5 py-1.5 text-[11px] text-slate-200 placeholder:text-slate-600"
          />
          <input
            value={sourceUrl}
            onChange={(event) => setSourceUrl(event.target.value)}
            placeholder="https://exemplo.gov/licencas.csv"
            className="rounded-lg border border-white/10 bg-black/20 px-2.5 py-1.5 text-[11px] text-slate-200 placeholder:text-slate-600"
          />
          <button
            type="button"
            onClick={() => void addSource()}
            disabled={working === "source-add"}
            className="inline-flex items-center justify-center gap-1.5 rounded-lg bg-sky-500 px-3 py-1.5 text-[11px] font-bold text-[#04141c] hover:bg-sky-400 disabled:opacity-50"
          >
            {working === "source-add" ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Plus className="h-3.5 w-3.5" />
            )}
            Adicionar
          </button>
        </div>
        <div className="space-y-2">
          {(sourcesData?.sources ?? []).length ? (
            (sourcesData?.sources ?? []).map((source: VoiceSource) => (
              <div
                key={source.id}
                className="flex flex-wrap items-center gap-2 rounded-lg border border-white/5 bg-white/[0.02] px-3 py-2 text-[10px]"
              >
                <span className="font-mono text-slate-500">#{source.id}</span>
                <span className="font-semibold text-slate-200">
                  {source.name}
                </span>
                <Badge
                  tone={
                    source.last_status === "success"
                      ? "emerald"
                      : source.last_status === "error"
                        ? "rose"
                        : "slate"
                  }
                >
                  {source.last_status || "por sincronizar"}
                </Badge>
                <span className="max-w-[280px] truncate text-slate-500">
                  {source.url}
                </span>
                <span className="text-slate-600">
                  {source.last_sync_at ? fmtWhen(source.last_sync_at) : "—"}
                </span>
                <button
                  type="button"
                  onClick={() => void syncSource(source.id)}
                  disabled={working === `source-sync-${source.id}`}
                  className="ml-auto inline-flex items-center gap-1 rounded-md border border-sky-400/30 bg-sky-500/10 px-2 py-1 text-[9px] font-semibold text-sky-200 hover:bg-sky-500/20 disabled:opacity-50"
                >
                  {working === `source-sync-${source.id}` ? (
                    <Loader2 className="h-3 w-3 animate-spin" />
                  ) : (
                    <Cloud className="h-3 w-3" />
                  )}
                  Sincronizar
                </button>
                {source.last_error ? (
                  <p className="w-full text-[9px] text-rose-300">
                    {source.last_error}
                  </p>
                ) : null}
              </div>
            ))
          ) : (
            <p className="text-[10px] text-slate-600">
              Sem fontes configuradas. Adiciona uma URL CSV e sincroniza; o
              pipeline faz parse, dedupe, rebuild da vitrine e segmentos.
            </p>
          )}
        </div>
        <p className="mt-3 text-[9px] text-slate-600">
          O host tem de estar em `VOICE_SOURCE_ALLOWED_HOSTS`. Fontes de
          licenças/permits, não dados de homeowners.
        </p>
      </Card>

      <Card
        title="3. Vitrine por cidade / nicho"
        className={tab === "sources" ? "" : "hidden"}
        icon={<Globe2 className="h-4 w-4 text-emerald-400" />}
        hint="Páginas públicas mascaradas, geradas a partir do inventário do leads.db."
        action={
          <button
            type="button"
            onClick={() => void buildShowcase()}
            disabled={working === "showcase-build"}
            className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-400/30 bg-emerald-500/10 px-2.5 py-1 text-[10px] font-semibold text-emerald-200 hover:bg-emerald-500/20 disabled:opacity-50"
          >
            {working === "showcase-build" ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : (
              <RefreshCcw className="h-3 w-3" />
            )}
            Rebuild pages
          </button>
        }
      >
        <div className="grid grid-cols-3 gap-2 md:grid-cols-6">
          <Stat label="Páginas" value={String(showcaseStats?.pages ?? 0)} tone="emerald" />
          <Stat label="Links" value={String(showcaseStats?.links ?? 0)} />
          <Stat label="Visitas" value={String(showcaseStats?.visits ?? 0)} />
          <Stat label="Checkouts" value={String(showcaseStats?.checkouts ?? 0)} />
          <Stat label="Pagos" value={String(showcaseStats?.completed ?? 0)} tone="emerald" />
          <Stat
            label="Receita"
            value={money0((showcaseStats?.revenue_cents ?? 0) / 100)}
            tone="emerald"
          />
        </div>
        <p className="mt-3 text-[10px] text-slate-600">
          A vitrine só publica com ≥3 oportunidades abertas em 30 dias. Usa
          “Enviar vitrine” no drawer da empresa para gerar o link rastreado e o
          email.
        </p>
      </Card>

      <Card
        title="4. Campanha autónoma"
        className={tab === "campaigns" ? "" : "hidden"}
        icon={<Rocket className="h-4 w-4 text-amber-400" />}
        hint="Consome a fila por cidade/nicho, aplica can_call e dispara Telnyx + vitrine. Sem chaves Telnyx corre em dry-run."
        action={<Badge tone="amber">Auto-scheduler</Badge>}
      >
        <div className="flex flex-wrap items-end gap-3">
          <label className="text-[10px] text-slate-500">
            Cota total
            <input
              type="number"
              min={1}
              max={10000}
              value={quotaTotal}
              onChange={(event) => setQuotaTotal(Number(event.target.value))}
              className="mt-1 block w-24 rounded-lg border border-white/10 bg-black/20 px-2.5 py-1.5 text-[11px] text-slate-200"
            />
          </label>
          <label className="text-[10px] text-slate-500">
            Lote diário
            <input
              type="number"
              min={1}
              max={500}
              value={batchSize}
              onChange={(event) => setBatchSize(Number(event.target.value))}
              className="mt-1 block w-24 rounded-lg border border-white/10 bg-black/20 px-2.5 py-1.5 text-[11px] text-slate-200"
            />
          </label>
          <label className="flex items-center gap-2 pb-2 text-[10px] font-semibold text-slate-400">
            <input
              type="checkbox"
              checked={includeFallback}
              onChange={(event) => setIncludeFallback(event.target.checked)}
              className="accent-amber-400"
            />
            Incluir fallback de cidade
          </label>
          <button
            type="button"
            onClick={() => void startCampaign()}
            disabled={working === "campaign-start"}
            className="inline-flex items-center gap-2 rounded-lg bg-amber-400 px-4 py-2 text-[11px] font-black text-[#1a1405] hover:bg-amber-300 disabled:opacity-50"
          >
            {working === "campaign-start" ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Play className="h-3.5 w-3.5" />
            )}
            Iniciar campanha autónoma
          </button>
          <span className="text-[10px] text-slate-500">
            {cityFilter || "todas as cidades"} · {tradeFilter || "todos os nichos"} ·{" "}
            {includeFallback ? "com fallback" : "só vitrine dedicada"}
          </span>
        </div>
        <div className="mt-4 space-y-2">
          {(campaignsData?.campaigns ?? []).length ? (
            (campaignsData?.campaigns ?? []).map((campaign) => (
              <div
                key={campaign.id}
                className="flex flex-wrap items-center gap-2 rounded-lg border border-white/5 bg-white/[0.02] px-3 py-2 text-[10px]"
              >
                <span className="font-mono text-slate-500">#{campaign.id}</span>
                <span className="font-semibold text-slate-200">
                  {campaign.name}
                </span>
                <Badge
                  tone={
                    campaign.status === "running"
                      ? "emerald"
                      : campaign.status === "completed"
                        ? "sky"
                        : campaign.status === "error"
                          ? "rose"
                          : "slate"
                  }
                >
                  {campaign.status}
                </Badge>
                <span className="text-slate-500">
                  {campaign.calls_started}/
                  {campaign.quota_total ?? campaign.max_calls} chamadas · lote{" "}
                  {campaign.batch_size ?? campaign.max_calls} ·{" "}
                  {campaign.showcases_sent} vitrines · {campaign.skipped} saltos
                </span>
                <span className="text-slate-600">
                  {campaign.city || "todas"} / {campaign.trade || "todos"}
                </span>
                <div className="ml-auto flex items-center gap-1">
                  {campaign.status === "running" ? (
                    <button
                      type="button"
                      onClick={() => void stopCampaign(campaign.id)}
                      disabled={working === `campaign-stop-${campaign.id}`}
                      className="inline-flex items-center gap-1 rounded-md border border-rose-400/30 bg-rose-500/10 px-2 py-1 text-[9px] font-semibold text-rose-200 hover:bg-rose-500/20 disabled:opacity-50"
                    >
                      {working === `campaign-stop-${campaign.id}` ? (
                        <Loader2 className="h-3 w-3 animate-spin" />
                      ) : (
                        <Square className="h-3 w-3" />
                      )}
                      Parar
                    </button>
                  ) : null}
                  {campaign.status === "paused" ? (
                    <button
                      type="button"
                      onClick={() => void resumeCampaign(campaign.id)}
                      disabled={working === `campaign-resume-${campaign.id}`}
                      className="inline-flex items-center gap-1 rounded-md border border-emerald-400/30 bg-emerald-500/10 px-2 py-1 text-[9px] font-semibold text-emerald-200 hover:bg-emerald-500/20 disabled:opacity-50"
                    >
                      {working === `campaign-resume-${campaign.id}` ? (
                        <Loader2 className="h-3 w-3 animate-spin" />
                      ) : (
                        <Play className="h-3 w-3" />
                      )}
                      Continuar lote
                    </button>
                  ) : null}
                </div>
              </div>
            ))
          ) : (
            <p className="text-[10px] text-slate-600">
              Sem campanhas ainda. Inicia uma para consumir a fila automaticamente.
            </p>
          )}
        </div>
      </Card>

      <Card
        title="5. Segmentos cidade + nicho"
        className={tab === "segments" ? "" : "hidden"}
        icon={<Rocket className="h-4 w-4 text-sky-400" />}
        hint="Cada linha é uma fila dinâmica. Iniciar cria uma campanha só para esse segmento."
      >
        <div className="max-h-[420px] overflow-y-auto">
          <table className="w-full min-w-[760px] text-left text-[11px]">
            <thead className="text-slate-500">
              <tr>
                <th className="pb-2 font-semibold">Cidade / nicho</th>
                <th className="pb-2 font-semibold">Prontos</th>
                <th className="pb-2 font-semibold">Vitrine</th>
                <th className="pb-2 text-right font-semibold">Ação</th>
              </tr>
            </thead>
            <tbody>
              {(segmentsData?.segments ?? []).length ? (
                (segmentsData?.segments ?? []).map((segment) => (
                  <tr
                    key={`${segment.city}-${segment.state}-${segment.trade}`}
                    className="border-t border-white/5 align-top"
                  >
                    <td className="py-2 pr-2">
                      <p className="font-semibold text-slate-200">
                        {segment.city}, {segment.state}
                      </p>
                      <p className="text-[10px] text-slate-500">
                        {segment.trade}
                      </p>
                    </td>
                    <td className="py-2 pr-2 text-slate-300">
                      {segment.callable}/{segment.total}
                      {segment.blocked > 0 ? (
                        <span className="text-[9px] text-amber-300">
                          {" "}
                          · {segment.blocked} bloqueados
                        </span>
                      ) : null}
                    </td>
                    <td className="py-2 pr-2">
                      <Badge
                        tone={
                          segment.showcase_mode === "dedicated"
                            ? "emerald"
                            : segment.showcase_mode === "city_fallback"
                              ? "amber"
                              : "rose"
                        }
                      >
                        {segment.showcase_mode === "dedicated"
                          ? "Dedicada"
                          : segment.showcase_mode === "city_fallback"
                            ? "Fallback cidade"
                            : "Sem vitrine"}
                      </Badge>
                      <p className="mt-1 text-[9px] text-slate-600">
                        {segment.showcase_exact} exatos ·{" "}
                        {segment.showcase_city_total} na cidade
                      </p>
                    </td>
                    <td className="py-2 text-right">
                      <button
                        type="button"
                        onClick={() => void startCampaign(segment)}
                        disabled={working === "campaign-start" || segment.callable === 0}
                        className="inline-flex items-center gap-1 rounded-lg border border-sky-400/30 bg-sky-500/10 px-2.5 py-1 text-[10px] font-semibold text-sky-200 hover:bg-sky-500/20 disabled:opacity-40"
                      >
                        <Play className="h-3 w-3" /> Iniciar
                      </button>
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={4} className="py-6 text-center text-[10px] text-slate-600">
                    Sem segmentos. Importa um CSV para criar as filas cidade+nicho.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </Card>

      <Card
        title="6. Cobertura por cidade e nicho"
        className={tab === "segments" ? "" : "hidden"}
        icon={<Globe2 className="h-4 w-4 text-sky-400" />}
        hint="Clique numa cidade ou nicho para filtrar a fila. Dados do voice.db."
        action={
          cityFilter || tradeFilter ? (
            <button
              type="button"
              onClick={() => {
                setCityFilter("");
                setTradeFilter("");
              }}
              className="text-[10px] font-semibold text-slate-400 hover:text-slate-200"
            >
              Limpar filtros
            </button>
          ) : null
        }
      >
        <div className="grid gap-4 md:grid-cols-2">
          <div>
            <p className="mb-2 text-[10px] font-semibold uppercase tracking-wide text-slate-500">
              Por cidade
            </p>
            <div className="space-y-1">
              {(stats?.by_city ?? []).length ? (
                (stats?.by_city ?? []).map((group) => (
                  <button
                    key={`city-${group.name}`}
                    type="button"
                    onClick={() =>
                      setCityFilter((current) =>
                        current === group.name ? "" : group.name
                      )
                    }
                    className={cn(
                      "flex w-full items-center justify-between rounded-lg border px-2.5 py-1.5 text-[11px]",
                      cityFilter === group.name
                        ? "border-sky-400/30 bg-sky-500/10 text-sky-200"
                        : "border-white/5 bg-white/[0.02] text-slate-300 hover:bg-white/[0.05]"
                    )}
                  >
                    <span className="font-semibold">{group.name}</span>
                    <span className="text-[10px] text-slate-500">
                      {group.callable} prontos · {group.total} total
                    </span>
                  </button>
                ))
              ) : (
                <p className="text-[10px] text-slate-600">Sem empresas importadas.</p>
              )}
            </div>
          </div>
          <div>
            <p className="mb-2 text-[10px] font-semibold uppercase tracking-wide text-slate-500">
              Por nicho
            </p>
            <div className="space-y-1">
              {(stats?.by_trade ?? []).length ? (
                (stats?.by_trade ?? []).map((group) => (
                  <button
                    key={`trade-${group.name}`}
                    type="button"
                    onClick={() =>
                      setTradeFilter((current) =>
                        current === group.name ? "" : group.name
                      )
                    }
                    className={cn(
                      "flex w-full items-center justify-between rounded-lg border px-2.5 py-1.5 text-[11px]",
                      tradeFilter === group.name
                        ? "border-indigo-400/30 bg-indigo-500/10 text-indigo-200"
                        : "border-white/5 bg-white/[0.02] text-slate-300 hover:bg-white/[0.05]"
                    )}
                  >
                    <span className="font-semibold">{group.name}</span>
                    <span className="text-[10px] text-slate-500">
                      {group.callable} prontos · {group.total} total
                    </span>
                  </button>
                ))
              ) : (
                <p className="text-[10px] text-slate-600">Sem empresas importadas.</p>
              )}
            </div>
          </div>
        </div>
        <div className="mt-4 border-t border-white/5 pt-3">
          <p className="mb-2 text-[10px] font-semibold uppercase tracking-wide text-slate-500">
            Campanhas
          </p>
          {(stats?.campaigns ?? []).length ? (
            <div className="grid gap-2 sm:grid-cols-2">
              {(stats?.campaigns ?? []).map((campaign) => (
                <div
                  key={campaign.campaign_id}
                  className="rounded-lg border border-white/5 bg-white/[0.02] px-2.5 py-1.5 text-[10px] text-slate-400"
                >
                  <span className="font-semibold text-slate-200">
                    {campaign.campaign_id}
                  </span>
                  <span className="ml-2">
                    {campaign.calls} chamadas · {campaign.showcases} vitrines ·{" "}
                    {campaign.intents} intents
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-[10px] text-slate-600">
              Sem campanhas registadas. O campaign_id é gravado em cada chamada.
            </p>
          )}
        </div>
      </Card>

      <Card
        title="7. Fila de chamadas"
        className={tab === "campaigns" ? "" : "hidden"}
        icon={<Users className="h-4 w-4 text-indigo-400" />}
        hint="Ordenada por score ICP e volume de obras; compliance sempre visível."
        action={
          <div className="flex flex-wrap items-center gap-2">
            <select
              value={cityFilter}
              onChange={(event) => setCityFilter(event.target.value)}
              className="rounded-lg border border-white/10 bg-black/20 px-2 py-1 text-[10px] font-semibold text-slate-300"
            >
              <option value="">Todas as cidades</option>
              {(stats?.by_city ?? []).map((group) => (
                <option key={`filter-city-${group.name}`} value={group.name}>
                  {group.name} ({group.total})
                </option>
              ))}
            </select>
            <select
              value={tradeFilter}
              onChange={(event) => setTradeFilter(event.target.value)}
              className="rounded-lg border border-white/10 bg-black/20 px-2 py-1 text-[10px] font-semibold text-slate-300"
            >
              <option value="">Todos os nichos</option>
              {(stats?.by_trade ?? []).map((group) => (
                <option key={`filter-trade-${group.name}`} value={group.name}>
                  {group.name} ({group.total})
                </option>
              ))}
            </select>
            <label className="inline-flex cursor-pointer items-center gap-2 text-[10px] font-semibold text-slate-400">
              <input
                type="checkbox"
                checked={includeBlocked}
                onChange={(event) => setIncludeBlocked(event.target.checked)}
                className="accent-indigo-400"
              />
              Mostrar bloqueadas
            </label>
          </div>
        }
      >
        {isLoading && !queue ? (
          <div className="flex items-center gap-2 py-8 text-xs text-slate-400">
            <Loader2 className="h-4 w-4 animate-spin" /> A carregar fila…
          </div>
        ) : !queue?.items.length ? (
          <div className="rounded-xl border border-dashed border-white/10 p-8 text-center">
            <Building2 className="mx-auto mb-2 h-6 w-6 text-slate-600" />
            <p className="text-xs text-slate-400">Sem empresas nesta vista.</p>
            <p className="mt-1 text-[10px] text-slate-600">
              Importa licenças/permits de MA e uma lista DNC para começar.
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[980px] text-left text-[11px]">
              <thead className="text-slate-500">
                <tr>
                  <th className="pb-2 font-semibold">Empresa</th>
                  <th className="pb-2 font-semibold">Telefone</th>
                  <th className="pb-2 font-semibold">Local</th>
                  <th className="pb-2 font-semibold">Categoria</th>
                  <th className="pb-2 font-semibold">Obras</th>
                  <th className="pb-2 font-semibold">Score</th>
                  <th className="pb-2 font-semibold">Compliance</th>
                  <th className="pb-2 text-right font-semibold">Ação</th>
                </tr>
              </thead>
              <tbody>
                {queue.items.map((company) => {
                  const allowed = company.eligibility.allowed;
                  return (
                    <tr
                      key={company.id}
                      onClick={() => setSelected(company)}
                      className="cursor-pointer border-t border-white/5 align-top hover:bg-white/[0.03]"
                    >
                      <td className="py-2.5 pr-2">
                        <p className="font-semibold text-slate-100">{company.company_name}</p>
                        <p className="text-[10px] text-slate-500">
                          {company.contact_name || "Responsável n/d"}
                          {company.license_number ? ` · ${company.license_number}` : ""}
                        </p>
                      </td>
                      <td className="py-2.5 pr-2">
                        <a
                          href={`tel:${company.phone}`}
                          onClick={(event) => event.stopPropagation()}
                          className="inline-flex items-center gap-1 font-mono text-[11px] font-semibold text-emerald-300 hover:text-emerald-200"
                        >
                          <Phone className="h-3 w-3" /> {company.phone}
                        </a>
                      </td>
                      <td className="py-2.5 pr-2 text-slate-400">
                        <span className="inline-flex items-center gap-1">
                          <MapPin className="h-3 w-3 text-slate-600" />
                          {company.city || "—"}, {company.state}
                        </span>
                      </td>
                      <td className="py-2.5 pr-2 text-slate-400">{company.trade || "—"}</td>
                      <td className="py-2.5 pr-2 text-slate-400">
                        <span className="font-semibold text-slate-200">{company.permit_count}</span>
                        {company.permit_value_usd > 0 ? (
                          <span className="text-slate-600"> · {money0(company.permit_value_usd)}</span>
                        ) : null}
                      </td>
                      <td className="py-2.5 pr-2">
                        <div className="flex items-center gap-1.5">
                          <div className="h-1.5 w-12 overflow-hidden rounded-full bg-white/10">
                            <div
                              className={cn(
                                "h-full rounded-full",
                                company.score >= 70
                                  ? "bg-emerald-400"
                                  : company.score >= 45
                                    ? "bg-amber-400"
                                    : "bg-slate-500"
                              )}
                              style={{ width: `${Math.min(100, company.score)}%` }}
                            />
                          </div>
                          <span className="text-[10px] tabular-nums text-slate-400">
                            {company.score}
                          </span>
                        </div>
                      </td>
                      <td className="py-2.5 pr-2">
                        {allowed ? (
                          <Badge tone="emerald">
                            <CheckCircle2 className="h-3 w-3" /> Pronto
                          </Badge>
                        ) : (
                          <div className="space-y-0.5">
                            <Badge tone="amber">
                              <AlertTriangle className="h-3 w-3" /> Bloqueado
                            </Badge>
                            <p className="max-w-[180px] text-[9px] leading-tight text-slate-600">
                              {company.eligibility.reason_labels.slice(0, 2).join(" · ")}
                            </p>
                          </div>
                        )}
                      </td>
                      <td className="py-2.5 text-right">
                        <button
                          type="button"
                          onClick={(event) => {
                            event.stopPropagation();
                            setSelected(company);
                          }}
                          className="rounded-lg border border-white/10 px-2.5 py-1 text-[10px] font-semibold text-slate-300 hover:bg-white/5"
                        >
                          Registar
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {selected ? (
        <div
          className="fixed inset-0 z-50 flex justify-end bg-black/60"
          onClick={() => setSelected(null)}
        >
          <aside
            className="h-full w-full max-w-xl overflow-y-auto border-l border-white/10 bg-[#0d1017] p-5"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="mb-4 flex items-start justify-between gap-3">
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">
                  Empresa {selected.id} · score {selected.score}
                </p>
                <h2 className="text-lg font-black text-white">{selected.company_name}</h2>
                <p className="text-[11px] text-slate-400">
                  {selected.contact_name || "Responsável n/d"} · {selected.trade || "categoria n/d"}
                </p>
              </div>
              <button
                type="button"
                onClick={() => setSelected(null)}
                className="rounded-lg border border-white/10 p-1.5 text-slate-400 hover:bg-white/5"
                aria-label="Fechar"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="mb-4 flex flex-wrap gap-2">
              {selected.eligibility.allowed ? (
                <Badge tone="emerald">
                  <CheckCircle2 className="h-3 w-3" /> Pode chamar
                </Badge>
              ) : (
                <Badge tone="amber">
                  <AlertTriangle className="h-3 w-3" /> Bloqueado
                </Badge>
              )}
              <Badge tone="slate">{selected.license_status || "licença n/d"}</Badge>
              <Badge tone="slate">{selected.state}</Badge>
              {selected.eligibility.reason_labels.map((label) => (
                <Badge key={label} tone="rose">
                  {label}
                </Badge>
              ))}
            </div>

            <div className="mb-4 grid grid-cols-2 gap-2 text-[11px]">
              <div className="rounded-lg border border-white/5 bg-white/[0.02] p-2.5">
                <p className="text-[9px] uppercase text-slate-500">Telefone</p>
                <a href={`tel:${selected.phone}`} className="font-mono font-semibold text-emerald-300">
                  {selected.phone}
                </a>
              </div>
              <div className="rounded-lg border border-white/5 bg-white/[0.02] p-2.5">
                <p className="text-[9px] uppercase text-slate-500">Email</p>
                <p className="truncate text-slate-300">{selected.email || "—"}</p>
              </div>
              <div className="rounded-lg border border-white/5 bg-white/[0.02] p-2.5">
                <p className="text-[9px] uppercase text-slate-500">Obras</p>
                <p className="text-slate-300">
                  {selected.permit_count} · {money0(selected.permit_value_usd)}
                </p>
              </div>
              <div className="rounded-lg border border-white/5 bg-white/[0.02] p-2.5">
                <p className="text-[9px] uppercase text-slate-500">Porte / anos</p>
                <p className="text-slate-300">
                  {selected.employee_estimate ?? "—"} emp. · {selected.years_active ?? "—"} anos
                </p>
              </div>
            </div>

            <div className="mb-4 rounded-xl border border-white/5 bg-white/[0.02] p-3">
              <p className="mb-2 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                <ShieldCheck className="h-3 w-3" /> Gate de compliance
              </p>
              <div className="grid grid-cols-2 gap-1 text-[10px] text-slate-400">
                {Object.entries(selected.eligibility.checks).map(([key, ok]) => (
                  <span key={key} className="flex items-center gap-1">
                    <span className={ok ? "text-emerald-300" : "text-rose-300"}>
                      {ok ? "✓" : "✕"}
                    </span>
                    {key}
                  </span>
                ))}
              </div>
              <p className="mt-2 text-[9px] text-slate-600">
                Hora local: {selected.eligibility.local_time}
              </p>
              <div className="mt-2 flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => void markDnc(false)}
                  disabled={working === "dnc-check"}
                  className="rounded-lg border border-emerald-400/30 bg-emerald-500/10 px-2.5 py-1 text-[10px] font-semibold text-emerald-200 hover:bg-emerald-500/20 disabled:opacity-50"
                >
                  DNC limpo
                </button>
                <button
                  type="button"
                  onClick={() => void markDnc(true)}
                  disabled={working === "dnc-check"}
                  className="rounded-lg border border-amber-400/30 bg-amber-500/10 px-2.5 py-1 text-[10px] font-semibold text-amber-200 hover:bg-amber-500/20 disabled:opacity-50"
                >
                  DNC listado
                </button>
                <button
                  type="button"
                  onClick={() => void suppress()}
                  disabled={working === "suppress"}
                  className="inline-flex items-center gap-1 rounded-lg border border-rose-400/30 bg-rose-500/10 px-2.5 py-1 text-[10px] font-semibold text-rose-200 hover:bg-rose-500/20 disabled:opacity-50"
                >
                  <Ban className="h-3 w-3" /> Suprimir
                </button>
              </div>
            </div>

            <div className="mb-3 grid grid-cols-2 gap-2">
              <button
                type="button"
                onClick={() => void sendShowcase()}
                disabled={working === "showcase-send"}
                className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-emerald-400/30 bg-emerald-500/10 px-3 py-2 text-[10px] font-semibold text-emerald-200 hover:bg-emerald-500/20 disabled:opacity-50"
              >
                {working === "showcase-send" ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Link2 className="h-3.5 w-3.5" />
                )}
                Enviar vitrine
              </button>
              <button
                type="button"
                onClick={() => void dialTelnyx()}
                disabled={!selected.eligibility.allowed || working === "dial"}
                className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-indigo-400/30 bg-indigo-500/10 px-3 py-2 text-[10px] font-semibold text-indigo-200 hover:bg-indigo-500/20 disabled:opacity-40"
              >
                {working === "dial" ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <PhoneOutgoing className="h-3.5 w-3.5" />
                )}
                Ligar Telnyx
              </button>
            </div>

            {selected.eligibility.allowed ? (
              <a
                href={`tel:${selected.phone}`}
                className="mb-4 flex w-full items-center justify-center gap-2 rounded-xl bg-emerald-500 px-4 py-2.5 text-sm font-bold text-[#062017] hover:bg-emerald-400"
              >
                <PhoneCall className="h-4 w-4" /> Abrir telefone
              </a>
            ) : (
              <div className="mb-4 rounded-xl border border-amber-400/20 bg-amber-500/10 px-3 py-2.5 text-[11px] text-amber-200">
                Chamada bloqueada pelo gate:{" "}
                {selected.eligibility.reason_labels.join(" · ")}. Resolve o DNC ou
                suprime o contacto antes de ligar.
              </div>
            )}

            <div className="rounded-xl border border-white/5 bg-white/[0.02] p-3">
              <p className="mb-2 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                <CalendarClock className="h-3 w-3" /> Registar chamada
              </p>
              <label className="mb-2 block text-[10px] text-slate-500">
                Resultado
                <select
                  value={outcome}
                  onChange={(event) => setOutcome(event.target.value)}
                  className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 px-2.5 py-1.5 text-[11px] text-slate-200"
                >
                  {OUTCOMES.map((item) => (
                    <option key={item.value} value={item.value}>
                      {item.label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="mb-2 block text-[10px] text-slate-500">
                Callback (opcional)
                <input
                  type="datetime-local"
                  value={callbackAt}
                  onChange={(event) => setCallbackAt(event.target.value)}
                  className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 px-2.5 py-1.5 text-[11px] text-slate-200"
                />
              </label>
              <label className="mb-3 block text-[10px] text-slate-500">
                Notas
                <textarea
                  value={notes}
                  onChange={(event) => setNotes(event.target.value)}
                  rows={3}
                  className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 px-2.5 py-1.5 text-[11px] text-slate-200 placeholder:text-slate-600"
                  placeholder="Contexto da chamada, objeções, próximo passo…"
                />
              </label>
              <button
                type="button"
                onClick={() => void submitCall()}
                disabled={
                  working === "call" ||
                  (!selected.eligibility.allowed &&
                    !["wrong_number", "not_interested", "do_not_call"].includes(
                      outcome
                    ))
                }
                className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-indigo-500 px-3 py-2 text-[11px] font-bold text-white hover:bg-indigo-400 disabled:opacity-50"
              >
                {working === "call" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <CheckCircle2 className="h-3.5 w-3.5" />}
                Guardar resultado
              </button>
              <p className="mt-2 text-[9px] text-slate-600">
                “Sem interesse”, “número errado” e “não contactar” criam supressão
                automática e retiram a empresa da fila.
              </p>
            </div>

            <p className="mt-4 text-[9px] text-slate-600">
              Última tentativa: {selected.last_attempt_at ? fmtWhen(selected.last_attempt_at) : "—"} ·
              consent basis: {selected.consent_basis}
            </p>
          </aside>
        </div>
      ) : null}
    </main>
  );
}

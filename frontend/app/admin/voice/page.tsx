"use client";

import {
  AlertTriangle,
  ArrowLeft,
  Ban,
  Building2,
  CalendarClock,
  CheckCircle2,
  Globe2,
  Link2,
  Loader2,
  MapPin,
  Phone,
  PhoneCall,
  PhoneOutgoing,
  RefreshCcw,
  ShieldCheck,
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
  dialVoiceContact,
  downloadVoiceTemplate,
  fetchShowcaseStats,
  fetchVoiceQueue,
  fetchVoiceStats,
  importVoiceDnc,
  importVoiceLicenses,
  logVoiceCall,
  sendVoiceShowcase,
  suppressVoicePhone,
  type VoiceCompany,
} from "@/lib/admin-api";
import { fmtWhen } from "@/lib/system-health";

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
}: {
  title: string;
  icon: ReactNode;
  hint?: string;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="rounded-2xl border border-white/10 bg-[#10131a] p-4">
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

  const queueKey = includeBlocked ? "voice-queue-blocked" : "voice-queue";
  const {
    data: queue,
    error,
    isLoading,
    mutate: mutateQueue,
  } = useSWR(queueKey, () => fetchVoiceQueue(includeBlocked, 250), {
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

  const importLicenses = () =>
    run("licenses", async () => {
      if (!licenseCsv.trim()) throw new Error("Escolhe um CSV de licenças/permits.");
      const result = await importVoiceLicenses(licenseCsv, licenseName, licenseUrl);
      setLicenseCsv("");
      return `Licenças: ${result.imported} novas, ${result.updated ?? 0} atualizadas, ${result.skipped} ignoradas.`;
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

      <div className="mb-5 grid gap-4 lg:grid-cols-2">
        <Card
          title="1. Importar licenças / permits"
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
              onClick={() => void importLicenses()}
              disabled={working === "licenses"}
              className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-500 px-3 py-1.5 text-[11px] font-bold text-white hover:bg-indigo-400 disabled:opacity-50"
            >
              {working === "licenses" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Upload className="h-3.5 w-3.5" />}
              Importar
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
        title="3. Vitrine por cidade / nicho"
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
        title="4. Fila de chamadas"
        icon={<Users className="h-4 w-4 text-indigo-400" />}
        hint="Ordenada por score ICP e volume de obras; compliance sempre visível."
        action={
          <label className="inline-flex cursor-pointer items-center gap-2 text-[10px] font-semibold text-slate-400">
            <input
              type="checkbox"
              checked={includeBlocked}
              onChange={(event) => setIncludeBlocked(event.target.checked)}
              className="accent-indigo-400"
            />
            Mostrar bloqueadas
          </label>
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

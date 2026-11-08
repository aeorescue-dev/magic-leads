"use client";

import {
  AlertTriangle,
  Activity,
  ArrowLeft,
  Ban,
  BarChart3,
  Building2,
  CalendarClock,
  Check,
  CheckCircle2,
  ChevronDown,
  Cloud,
  Database,
  FileText,
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
  TrendingUp,
  Upload,
  Users,
  X,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import useSWR from "swr";

import {
  AdminApiError,
  approveAllVoiceScripts,
  approveVoiceScript,
  buildShowcasePages,
  checkVoiceDnc,
  createVoiceSource,
  dialVoiceContact,
  downloadVoiceTemplate,
  fetchShowcaseStats,
  fetchVoiceCampaigns,
  fetchVoiceLiquidity,
  fetchVoiceLive,
  fetchVoiceMetrics,
  fetchVoiceQueue,
  fetchVoiceScripts,
  fetchVoiceSegments,
  fetchVoiceSources,
  fetchVoiceStats,
  importVoiceDnc,
  ingestVoice,
  logVoiceCall,
  previewVoiceScript,
  resumeVoiceCampaign,
  saveVoiceScript,
  scrubDnc,
  sendVoiceShowcase,
  startVoiceCampaign,
  startVoiceTestCall,
  stagingClearDnc,
  stopVoiceCampaign,
  suppressVoicePhone,
  syncLicensingSources,
  syncVoiceScript,
  syncVoiceSource,
  type VoiceCampaign,
  type VoiceCompany,
  type VoiceLiquidity,
  type VoiceLive,
  type VoiceMetrics,
  type VoiceMetricsGroup,
  type VoiceRetentionBucket,
  type VoiceScript,
  type VoiceScriptPreview,
  type VoiceSegment,
  type VoiceSource,
  fetchVoiceCompanyScore,
  fetchVoiceScoreDistribution,
  type AdminScoreDetail,
} from "@/lib/admin-api";
import {
  DateField,
  FilterChip,
  ScoreBar,
  ScoreHistogram,
  StatusPill,
} from "@/components/admin/ui";
import { SCORE_RANGES, formatScore, scoreBand, SCORE_BAND_META } from "@/lib/score";
import { fmtWhen } from "@/lib/system-health";

type VoiceTab = "overview" | "campaigns" | "segments" | "scripts" | "sources";

const VOICE_TABS: Array<{ id: VoiceTab; label: string }> = [
  { id: "overview", label: "Visão Geral" },
  { id: "campaigns", label: "Campanhas" },
  { id: "segments", label: "Segmentos" },
  { id: "scripts", label: "Roteiros" },
  { id: "sources", label: "Fontes" },
];

const OUTCOMES: Array<{ value: string; label: string }> = [
  { value: "connected", label: "Falou com responsável" },
  { value: "voicemail", label: "Voicemail" },
  { value: "no_answer", label: "Sem resposta" },
  { value: "busy", label: "Ocupado" },
  { value: "callback", label: "Pediu callback" },
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

const money2 = (value: number) =>
  new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value);

const SCORE_COMPONENTS: Record<string, { label: string; max: number; tone: string }> = {
  demand: { label: "Demanda", max: 1, tone: "from-sky-400 to-cyan-300" },
  trade_confidence: { label: "Confiança do trade", max: 1, tone: "from-violet-400 to-fuchsia-300" },
  license: { label: "Licença", max: 8, tone: "from-emerald-400 to-teal-300" },
  contact: { label: "Contacto", max: 10, tone: "from-amber-400 to-yellow-300" },
  company_strength: { label: "Força da empresa", max: 1, tone: "from-orange-400 to-amber-300" },
  freshness: { label: "Frescura", max: 5, tone: "from-teal-400 to-emerald-300" },
  quality_penalty: { label: "Penalidade", max: 50, tone: "from-rose-500 to-orange-400" },
};

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
    <section
      className={cn(
        "rounded-2xl border border-slate-700/70 bg-[#10131a] p-5 shadow-[0_20px_60px_-40px_rgba(0,0,0,0.9)]",
        className
      )}
    >
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="flex items-center gap-2 text-base font-bold text-white">
            {icon}
            {title}
          </h2>
          {hint ? (
            <p className="mt-1 max-w-3xl text-xs leading-relaxed text-slate-400">
              {hint}
            </p>
          ) : null}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

function SectionHeader({
  eyebrow,
  title,
  description,
  icon,
}: {
  eyebrow: string;
  title: string;
  description: string;
  icon: ReactNode;
}) {
  return (
    <div className="mb-3 mt-2 flex items-start gap-3">
      <div className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-emerald-400/20 bg-emerald-500/10 text-emerald-300">
        {icon}
      </div>
      <div>
        <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-emerald-300/80">
          {eyebrow}
        </p>
        <h2 className="text-lg font-black tracking-tight text-white">{title}</h2>
        <p className="max-w-4xl text-xs leading-relaxed text-slate-400">
          {description}
        </p>
      </div>
    </div>
  );
}

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-[10px] font-bold uppercase tracking-[0.12em] text-slate-400">
        {label}
      </span>
      {children}
      {hint ? <span className="mt-1 block text-[10px] text-slate-500">{hint}</span> : null}
    </label>
  );
}

const FIELD_CLASS =
  "w-full rounded-xl border border-slate-600 bg-slate-950/90 px-3 py-2.5 text-sm font-medium text-white shadow-inner outline-none transition placeholder:text-slate-500 hover:border-slate-500 focus:border-emerald-400 focus:ring-2 focus:ring-emerald-500/20";

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
    <div className="rounded-xl border border-slate-700/60 bg-slate-900/50 p-3">
      <p className="text-[10px] font-bold uppercase tracking-[0.12em] text-slate-400">
        {label}
      </p>
      <p
        className={cn(
          "mt-1 text-2xl font-black tabular-nums tracking-tight",
          tone === "emerald"
            ? "text-emerald-300"
            : tone === "amber"
              ? "text-amber-300"
              : tone === "rose"
                ? "text-rose-300"
                : "text-white"
        )}
      >
        {value}
      </p>
      {sub ? <p className="mt-1 text-[11px] leading-snug text-slate-400">{sub}</p> : null}
    </div>
  );
}

type SelectOption = { value: string; label: string };

function SelectMenu({
  value,
  onChange,
  options,
  placeholder,
  className,
  buttonClassName,
}: {
  value: string;
  onChange: (value: string) => void;
  options: SelectOption[];
  placeholder?: string;
  className?: string;
  buttonClassName?: string;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onDoc = (event: MouseEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  const selected = options.find((option) => option.value === value);
  return (
    <div ref={ref} className={cn("relative", className)}>
      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        aria-haspopup="listbox"
        aria-expanded={open}
        className={cn(
          "flex w-full items-center justify-between gap-2 rounded-xl border border-slate-600 bg-slate-950/90 px-3 py-2.5 text-sm font-semibold text-white shadow-inner transition-colors hover:border-slate-500",
          buttonClassName
        )}
      >
        <span className="truncate">{selected?.label ?? placeholder ?? "Selecionar"}</span>
        <ChevronDown
          className={cn(
            "h-3 w-3 shrink-0 text-slate-400 transition-transform",
            open && "rotate-180"
          )}
        />
      </button>
      {open ? (
        <div
          role="listbox"
          className="absolute z-50 mt-1 max-h-64 w-full min-w-[190px] overflow-auto rounded-lg border border-white/15 bg-[#1a1d24] p-1 shadow-2xl shadow-black/60"
        >
          {options.map((option) => (
            <button
              key={option.value}
              type="button"
              role="option"
              aria-selected={option.value === value}
              onClick={() => {
                onChange(option.value);
                setOpen(false);
              }}
              className={cn(
                "flex w-full items-center justify-between gap-2 rounded-md px-3 py-2 text-left text-xs transition-colors",
                option.value === value
                  ? "bg-emerald-500/15 font-bold text-emerald-200"
                  : "text-slate-200 hover:bg-white/10 hover:text-white"
              )}
            >
              <span className="truncate">{option.label}</span>
              {option.value === value ? <Check className="h-3 w-3" /> : null}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

type GaugeTone = "emerald" | "amber" | "rose";

const GAUGE_TONES: Record<GaugeTone, { ring: string; text: string }> = {
  emerald: { ring: "stroke-emerald-400", text: "text-emerald-300" },
  amber: { ring: "stroke-amber-400", text: "text-amber-300" },
  rose: { ring: "stroke-rose-400", text: "text-rose-300" },
};

function gaugeTone(value: number, green: number, amber: number): GaugeTone {
  if (value >= green) return "emerald";
  if (value >= amber) return "amber";
  return "rose";
}

function GaugeCard({
  label,
  value,
  sub,
  tone,
}: {
  label: string;
  value: number;
  sub: string;
  tone: GaugeTone;
}) {
  const clamped = Math.max(0, Math.min(100, value));
  const colors = GAUGE_TONES[tone];
  return (
    <div className="rounded-xl border border-white/5 bg-white/[0.02] p-3 text-center">
      <svg viewBox="0 0 120 70" className="mx-auto w-full max-w-[150px]">
        <path
          d="M12 60 A48 48 0 0 1 108 60"
          fill="none"
          strokeWidth={10}
          strokeLinecap="round"
          className="stroke-white/10"
        />
        <path
          d="M12 60 A48 48 0 0 1 108 60"
          fill="none"
          strokeWidth={10}
          strokeLinecap="round"
          pathLength={100}
          strokeDasharray={`${clamped} 100`}
          className={colors.ring}
        />
      </svg>
      <div className="-mt-7">
        <p className={cn("text-2xl font-black tabular-nums", colors.text)}>
          {value.toFixed(1)}%
        </p>
        <p className="text-[9px] font-semibold uppercase tracking-wide text-slate-500">
          {label}
        </p>
      </div>
      <p className="mt-2 text-[10px] text-slate-500">{sub}</p>
    </div>
  );
}

function RetentionChart({
  buckets,
  answered,
}: {
  buckets: VoiceRetentionBucket[];
  answered: number;
}) {
  if (!answered) {
    return (
      <div className="rounded-xl border border-dashed border-white/10 p-6 text-center text-[11px] text-slate-600">
        Sem chamadas atendidas para medir retenção de áudio.
      </div>
    );
  }
  return (
    <div className="space-y-3">
      {buckets.map((bucket) => (
        <div key={bucket.seconds}>
          <div className="flex items-center justify-between text-[10px]">
            <span className="font-semibold text-slate-300">
              ≥ {bucket.seconds}s
            </span>
            <span className="text-slate-500 tabular-nums">
              {bucket.pct_of_answered.toFixed(1)}% · {bucket.count} chamadas
            </span>
          </div>
          <div className="mt-1 h-2 overflow-hidden rounded-full bg-white/10">
            <div
              className="h-full rounded-full bg-gradient-to-r from-sky-400 to-emerald-400"
              style={{ width: `${Math.min(100, bucket.pct_of_answered)}%` }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}

function FunnelChart({
  funnel,
}: {
  funnel: VoiceMetrics["funnel"];
}) {
  const steps = [
    { label: "Discadas", value: funnel.dialed, tone: "bg-sky-500/80" },
    { label: "Atendidas", value: funnel.answered, tone: "bg-cyan-500/80" },
    { label: "Aceite (1/Yes)", value: funnel.accepts, tone: "bg-lime-500/80" },
    { label: "Ouviram ≥30s", value: funnel.engaged, tone: "bg-emerald-500/80" },
    { label: "Clique na vitrine", value: funnel.clicks, tone: "bg-teal-500/80" },
    { label: "Checkout", value: funnel.checkouts, tone: "bg-amber-500/80" },
  ];
  const max = Math.max(1, funnel.dialed);
  return (
    <div className="space-y-2">
      {steps.map((step, index) => {
        const prev = index === 0 ? step.value : steps[index - 1].value;
        const width = Math.max(4, (step.value / max) * 100);
        const conversion = prev > 0 ? (step.value / prev) * 100 : 0;
        return (
          <div key={step.label}>
            <div className="flex items-center justify-between text-[10px]">
              <span className="font-semibold text-slate-300">{step.label}</span>
              <span className="text-slate-500 tabular-nums">
                {step.value}
                {index > 0 ? ` · ${conversion.toFixed(1)}% do passo anterior` : ""}
              </span>
            </div>
            <div className="mt-1 h-6 overflow-hidden rounded-lg bg-white/[0.04]">
              <div
                className={cn("h-full rounded-lg", step.tone)}
                style={{ width: `${width}%` }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}

function heatCell(value: number, green: number, amber: number) {
  if (value >= green) return "bg-emerald-500/15 text-emerald-200";
  if (value >= amber) return "bg-amber-500/15 text-amber-200";
  return "bg-rose-500/15 text-rose-200";
}

function HeatmapMatrix({ rows }: { rows: VoiceMetricsGroup[] }) {
  if (!rows.length) {
    return (
      <div className="rounded-xl border border-dashed border-white/10 p-6 text-center text-[11px] text-slate-600">
        Sem chamadas por cidade/nicho no período. Inicia uma campanha para
        alimentar a matriz.
      </div>
    );
  }
  const sorted = [...rows].sort((a, b) => b.net_usd - a.net_usd);
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[1040px] text-left text-[10px]">
        <thead className="text-slate-500">
          <tr>
            <th className="pb-2 font-semibold">Cidade / nicho</th>
            <th className="pb-2 text-right font-semibold">Answer</th>
            <th className="pb-2 text-right font-semibold">Aceite</th>
            <th className="pb-2 text-right font-semibold">Engagement</th>
            <th className="pb-2 text-right font-semibold">CTR</th>
            <th className="pb-2 text-right font-semibold">Assin.</th>
            <th className="pb-2 text-right font-semibold">Receita</th>
            <th className="pb-2 text-right font-semibold">Custo</th>
            <th className="pb-2 text-right font-semibold">Net</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((row) => (
            <tr
              key={`${row.city}-${row.trade}-${row.state ?? ""}`}
              className="border-t border-white/5"
            >
              <td className="py-2 pr-2">
                <p className="font-semibold text-slate-200">{row.city}</p>
                <p className="text-[9px] text-slate-500">{row.trade}</p>
              </td>
              <td className={cn("px-2 py-2 text-right tabular-nums", heatCell(row.answer_rate, 40, 25))}>
                {row.answer_rate.toFixed(1)}%
              </td>
              <td className={cn("px-2 py-2 text-right tabular-nums", heatCell(row.accept_rate ?? 0, 30, 15))}>
                {(row.accept_rate ?? 0).toFixed(1)}%
              </td>
              <td className={cn("px-2 py-2 text-right tabular-nums", heatCell(row.engagement_rate, 50, 30))}>
                {row.engagement_rate.toFixed(1)}%
              </td>
              <td className={cn("px-2 py-2 text-right tabular-nums", heatCell(row.showcase_ctr, 15, 8))}>
                {row.showcase_ctr.toFixed(1)}%
              </td>
              <td className={cn("px-2 py-2 text-right tabular-nums", heatCell(row.subscription_rate ?? 0, 10, 3))}>
                {(row.subscription_rate ?? 0).toFixed(1)}%
              </td>
              <td className="px-2 py-2 text-right text-emerald-200 tabular-nums">
                {money0(row.revenue_usd)}
              </td>
              <td className="px-2 py-2 text-right text-amber-200 tabular-nums">
                {money0(row.cost_usd)}
              </td>
              <td
                className={cn(
                  "px-2 py-2 text-right font-bold tabular-nums",
                  row.net_usd >= 0 ? "text-emerald-300" : "text-rose-300"
                )}
              >
                {money0(row.net_usd)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}


function BreakdownTable({
  rows,
  label,
}: {
  rows: VoiceMetricsGroup[];
  label: (row: VoiceMetricsGroup) => string;
}) {
  if (!rows.length) {
    return (
      <div className="rounded-xl border border-dashed border-white/10 p-5 text-center text-[10px] text-slate-600">
        Sem chamadas no período.
      </div>
    );
  }
  const sorted = [...rows].sort(
    (a, b) =>
      (b.accept_rate ?? 0) - (a.accept_rate ?? 0) ||
      (b.subscription_rate ?? 0) - (a.subscription_rate ?? 0) ||
      b.dialed - a.dialed
  );
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[520px] text-left text-[10px]">
        <thead className="text-slate-500">
          <tr>
            <th className="pb-2 font-semibold">Segmento</th>
            <th className="pb-2 text-right font-semibold">Atend.</th>
            <th className="pb-2 text-right font-semibold">Aceites</th>
            <th className="pb-2 text-right font-semibold">Aceite</th>
            <th className="pb-2 text-right font-semibold">Assin.</th>
            <th className="pb-2 text-right font-semibold">Conv.</th>
            <th className="pb-2 text-right font-semibold">Receita</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((row, index) => {
            const accept = row.accept_rate ?? 0;
            const conversion = row.subscription_rate ?? 0;
            return (
              <tr
                key={`${label(row)}-${index}`}
                className="border-t border-white/5"
              >
                <td className="py-2 pr-2 font-semibold text-slate-200">
                  {label(row)}
                </td>
                <td className="px-2 py-2 text-right tabular-nums text-slate-400">
                  {row.answered}
                </td>
                <td className="px-2 py-2 text-right tabular-nums text-slate-300">
                  {row.accepts ?? 0}
                </td>
                <td
                  className={cn(
                    "px-2 py-2 text-right tabular-nums",
                    heatCell(accept, 30, 15)
                  )}
                >
                  {accept.toFixed(1)}%
                </td>
                <td className="px-2 py-2 text-right tabular-nums text-slate-300">
                  {row.checkouts}
                </td>
                <td
                  className={cn(
                    "px-2 py-2 text-right tabular-nums",
                    heatCell(conversion, 10, 3)
                  )}
                >
                  {conversion.toFixed(1)}%
                </td>
                <td className="px-2 py-2 text-right tabular-nums text-emerald-200">
                  {money0(row.revenue_usd)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
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
  const [scoreRange, setScoreRange] = useState("all");
  const [statusFilter, setStatusFilter] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [scoreDetail, setScoreDetail] = useState<AdminScoreDetail | null>(null);
  const [scoreLoading, setScoreLoading] = useState(false);
  const [page, setPage] = useState(1);
  const pageSize = 20;
  const [quotaTotal, setQuotaTotal] = useState(100);
  const [batchSize, setBatchSize] = useState(25);
  const [includeFallback, setIncludeFallback] = useState(true);
  const [budgetTotal, setBudgetTotal] = useState(100);
  const [budgetDaily, setBudgetDaily] = useState(5);
  const [maxDays, setMaxDays] = useState(30);
  const [startHour, setStartHour] = useState(9);
  const [callInterval, setCallInterval] = useState(30);
  const [metricsDays, setMetricsDays] = useState(30);
  const [tab, setTab] = useState<VoiceTab>("overview");
  const [sourceName, setSourceName] = useState("");
  const [sourceUrl, setSourceUrl] = useState("");
  const [scriptTrade, setScriptTrade] = useState("remodeling");
  const [scriptBody, setScriptBody] = useState("");
  const [scriptDisclosure, setScriptDisclosure] = useState("");
  const [scriptAssistantId, setScriptAssistantId] = useState("");
  const [scriptPreview, setScriptPreview] = useState<VoiceScriptPreview | null>(null);
  const [previewCity, setPreviewCity] = useState("New York");
  const [previewCompany, setPreviewCompany] = useState("Example Contracting");
  const [selected, setSelected] = useState<VoiceCompany | null>(null);
  useEffect(() => {
    if (!selected) {
      setScoreDetail(null);
      return;
    }
    let alive = true;
    setScoreLoading(true);
    fetchVoiceCompanyScore(selected.id)
      .then((detail) => {
        if (alive) setScoreDetail(detail);
      })
      .catch(() => {
        if (alive) setScoreDetail(null);
      })
      .finally(() => {
        if (alive) setScoreLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [selected?.id]);
  const [licenseCsv, setLicenseCsv] = useState("");
  const [licenseName, setLicenseName] = useState("MA HIC / licenças");
  const [licenseUrl, setLicenseUrl] = useState("");
  const [dncCsv, setDncCsv] = useState("");
  const [dncSource, setDncSource] = useState("manual_csv");
  const [dncScrub, setDncScrub] = useState(true);
  const [working, setWorking] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [liveCampaignId, setLiveCampaignId] = useState<number | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [outcome, setOutcome] = useState("connected");
  const [notes, setNotes] = useState("");
  const [callbackAt, setCallbackAt] = useState("");
  const [testPhone, setTestPhone] = useState("");
  const [testCity, setTestCity] = useState("New York");
  const [testState, setTestState] = useState("NY");
  const [testTrade, setTestTrade] = useState("remodeling");
  const [testCompanyName, setTestCompanyName] = useState("");

  const selectedRange =
    SCORE_RANGES.find((range) => range.id === scoreRange) ?? SCORE_RANGES[0];
  const queueFilters = {
    city: cityFilter,
    trade: tradeFilter,
    scoreMin: selectedRange.min,
    scoreMax: selectedRange.max,
    status: statusFilter,
    dateFrom,
    dateTo,
  };
  const queueKey = `voice-queue-${includeBlocked}-${JSON.stringify(queueFilters)}-${page}`;
  const {
    data: queue,
    error,
    isLoading,
    mutate: mutateQueue,
  } = useSWR(
    queueKey,
    () =>
      fetchVoiceQueue(
        includeBlocked,
        pageSize,
        queueFilters,
        "",
        (page - 1) * pageSize
      ),
    {
      refreshInterval: 60_000,
      revalidateOnFocus: true,
    }
  );
  const { data: stats, mutate: mutateStats } = useSWR(
    "voice-stats",
    fetchVoiceStats,
    { refreshInterval: 60_000 }
  );
  const { data: scoreDist, mutate: mutateScoreDist } = useSWR(
    "voice-score-distribution",
    fetchVoiceScoreDistribution,
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
    () => fetchVoiceCampaigns(50),
    { refreshInterval: 5_000 }
  );
  const { data: metrics, mutate: mutateMetrics } = useSWR(
    `voice-metrics-${metricsDays}`,
    () => fetchVoiceMetrics(metricsDays),
    { refreshInterval: 30_000, revalidateOnFocus: true }
  );
  const { data: liveData, mutate: mutateLive } = useSWR<VoiceLive>(
    `voice-live-${liveCampaignId ?? "auto"}`,
    () => fetchVoiceLive(liveCampaignId ?? undefined),
    { refreshInterval: 30_000, revalidateOnFocus: true }
  );
  const { data: liquidityData, mutate: mutateLiquidity } = useSWR<VoiceLiquidity>(
    "voice-liquidity",
    () => fetchVoiceLiquidity(),
    { refreshInterval: 30_000, revalidateOnFocus: true }
  );
  const { data: sourcesData, mutate: mutateSources } = useSWR(
    "voice-sources",
    fetchVoiceSources,
    { refreshInterval: 60_000 }
  );
  const { data: scriptsData, mutate: mutateScripts } = useSWR(
    "voice-scripts",
    fetchVoiceScripts,
    { refreshInterval: 60_000 }
  );
  const scripts = scriptsData?.scripts ?? [];
  const currentScript =
    scripts.find((item) => item.trade_code === scriptTrade) ?? null;

  useEffect(() => {
    if (!currentScript) return;
    setScriptBody(currentScript.body);
    setScriptDisclosure(currentScript.disclosure || "");
    setScriptAssistantId(currentScript.assistant_id || "");
    setScriptPreview(null);
  }, [currentScript?.trade_code, currentScript?.version]);

  const refreshAll = async () => {
    if (refreshing) return;
    setRefreshing(true);
    try {
      // Forca revalidacao de todos os endpoints da pagina, nao apenas a
      // fila e as estatisticas. Um endpoint em erro nao bloqueia os outros.
      await Promise.allSettled([
        mutateQueue(),
        mutateStats(),
        mutateScoreDist(),
        mutateShowcase(),
        mutateSegments(),
        mutateCampaigns(),
        mutateMetrics(),
        mutateLive(),
        mutateLiquidity(),
        mutateSources(),
        mutateScripts(),
      ]);
    } finally {
      setRefreshing(false);
    }
  };

  const callable = useMemo(
    () => queue?.items.filter((item) => item.eligibility.allowed).length ?? 0,
    [queue]
  );
  const liquidityRows = useMemo(
    () =>
      (liquidityData?.rows ?? [])
        .slice()
        .sort(
          (a, b) =>
            Number(b.exact) - Number(a.exact) ||
            b.available - a.available ||
            b.callable - a.callable
        ),
    [liquidityData]
  );

  useEffect(() => {
    setPage(1);
  }, [includeBlocked, cityFilter, tradeFilter, scoreRange, statusFilter, dateFrom, dateTo]);

  const totalItems = queue?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(totalItems / pageSize));
  const pageStart = totalItems === 0 ? 0 : (page - 1) * pageSize + 1;
  const pageEnd = Math.min(page * pageSize, totalItems);

  useEffect(() => {
    if (page > totalPages) setPage(totalPages);
  }, [page, totalPages]);

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
        budget_total_usd: budgetTotal,
        budget_daily_usd: budgetDaily,
        max_days: maxDays,
        start_hour_et: startHour,
        call_interval_seconds: callInterval,
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

  const fireTestCall = () =>
    run("test-call", async () => {
      const phone = testPhone.trim();
      if (!phone) {
        throw new Error("Indica um número US válido no formato +1XXXXXXXXXX.");
      }
      if (!window.confirm(`Ligar agora para ${phone}?`)) {
        throw new Error("Chamada cancelada.");
      }
      const result = await startVoiceTestCall({
        phone,
        city: testCity.trim() || "New York",
        state: testState.trim().toUpperCase() || "NY",
        trade: testTrade,
        company_name: testCompanyName,
      });
      return `Chamada de teste #${result.voice_call_id} (${result.status ?? "dialing"}) — atende e prime 2 para validar o opt-out. Supressão limpa: ${result.suppression_cleared ?? 0}.`;
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

  const saveScript = () =>
    run("script-save", async () => {
      if (!currentScript) throw new Error("Seleciona um roteiro.");
      const result = await saveVoiceScript(scriptTrade, {
        body: scriptBody,
        disclosure: scriptDisclosure,
        assistant_id: scriptAssistantId,
      });
      await mutateScripts();
      return `Roteiro ${scriptTrade} v${result.script.version} guardado como draft.`;
    });

  const approveScript = () =>
    run("script-approve", async () => {
      if (!currentScript) throw new Error("Seleciona um roteiro.");
      await approveVoiceScript(scriptTrade);
      await mutateScripts();
      return `Roteiro ${scriptTrade} aprovado para uso em chamadas.`;
    });

  const approveAllScripts = () =>
    run("scripts-approve-all", async () => {
      const result = await approveAllVoiceScripts(true);
      await mutateScripts();
      const sync = result.sync;
      const syncNote =
        sync?.status === "telnyx_not_configured"
          ? " · sync Telnyx pendente (chaves ausentes)"
          : ` · ${sync?.synced ?? 0} sincronizados`;
      return `Roteiros: ${result.approved} aprovados de ${result.total}${syncNote}.`;
    });

  const previewScript = () =>
    run("script-preview", async () => {
      if (!currentScript) throw new Error("Seleciona um roteiro.");
      const result = await previewVoiceScript(scriptTrade, {
        company: previewCompany,
        city: previewCity,
        permit_count: 12,
      });
      setScriptPreview(result);
      return "Preview do roteiro atualizado.";
    });

  const syncScript = () =>
    run("script-sync", async () => {
      if (!currentScript) throw new Error("Seleciona um roteiro.");
      const result = await syncVoiceScript(scriptTrade);
      await mutateScripts();
      return `Telnyx ${result.mode}: ${result.assistant_id}`;
    });

  const importDnc = () =>
    run("dnc", async () => {
      if (!dncCsv.trim()) throw new Error("Cola ou escolhe uma lista DNC.");
      const result = dncScrub
        ? await scrubDnc(dncCsv, dncSource)
        : { import: await importVoiceDnc(dncCsv, dncSource), scrub: null };
      setDncCsv("");
      await Promise.all([mutateStats(), mutateSegments(), mutateMetrics()]);
      const scrub = result.scrub;
      return `DNC: ${result.import.imported} números · ${
        result.import.listed ?? 0
      } listados · ${result.import.cleaned ?? 0} limpos${
        scrub
          ? ` · base: ${scrub.cleared} limpos / ${scrub.listed} listados`
          : ""
      } · ${result.import.skipped} ignorados.`;
    });

  const stagingClear = () =>
    run("staging-clear", async () => {
      const result = await stagingClearDnc();
      await Promise.all([
        mutateStats(),
        mutateSegments(),
        mutateMetrics(),
        mutateQueue(),
      ]);
      return `Staging: ${result.cleared} telefones desbloqueados · ${result.segments} segmentos.`;
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
            {stats?.staging_mode ? (
              <Badge tone="amber">Staging · dry-run</Badge>
            ) : null}
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
          disabled={refreshing}
          className="inline-flex items-center gap-2 rounded-lg border border-white/10 px-3 py-2 text-xs font-semibold text-slate-300 hover:bg-white/5 disabled:cursor-wait disabled:opacity-50"
        >
          <RefreshCcw className={cn("h-3.5 w-3.5", refreshing && "animate-spin")} />
          {refreshing ? "A atualizar…" : "Refresh"}
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

      <div className="mb-2 flex flex-wrap items-end justify-between gap-1">
        <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-400">
          Resumo da base
        </p>
        <p className="text-[10px] text-slate-500">inventário e gate de chamada</p>
      </div>
      <section className="mb-5 grid grid-cols-2 gap-3 md:grid-cols-6">
        <Stat label="Empresas" value={String(stats?.total ?? queue?.total ?? 0)} sub="pessoas jurídicas" />
        <Stat
          label="Chamáveis"
          value={String(stats?.callable ?? queue?.callable ?? callable)}
          tone="emerald"
          sub="passam o gate"
        />
        <Stat label="Bloqueadas" value={String(stats?.blocked ?? 0)} tone="amber" sub="com motivo" />
        <Stat label="Tentativas hoje" value={String(stats?.attempts_today ?? 0)} sub="chamadas reais desde 00:00 UTC" />
        <Stat label="DNC listados" value={String(stats?.dnc_listed ?? 0)} tone="rose" sub={`${stats?.dnc_checked ?? 0} checks`} />
        <Stat label="Suprimidos" value={String(stats?.suppressed ?? 0)} tone="amber" sub="opt-out / manual" />
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

      <div className={tab === "overview" ? "" : "hidden"}>
        <SectionHeader
          eyebrow="Tempo real"
          title="Operação em tempo real"
          description="Chamadas em curso, ritmo do lote e um test call controlado. Esta área responde a “o que está a acontecer agora”."
          icon={<Activity className="h-4 w-4" />}
        />
      </div>
      <div
        className={cn(
          "mb-6 grid gap-4 xl:grid-cols-[minmax(0,1.65fr)_minmax(340px,0.95fr)]",
          tab === "overview" ? "" : "hidden"
        )}
      >
        <Card
          title="Test Call"
          icon={<PhoneOutgoing className="h-4 w-4 text-emerald-400" />}
          hint="Chamada real de escuta. A tecla 2 suprime o número; o próximo test call limpa a supressão."
          className="order-2 xl:order-2"
        >
          <div className="space-y-3">
            <Field
              label="Número de teste"
              hint="Qualquer número US válido no formato +1XXXXXXXXXX."
            >
              <input
                value={testPhone}
                onChange={(event) => setTestPhone(event.target.value)}
                placeholder="+1XXXXXXXXXX"
                inputMode="tel"
                className={FIELD_CLASS}
              />
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Cidade">
                <input
                  value={testCity}
                  onChange={(event) => setTestCity(event.target.value)}
                  placeholder="New York"
                  className={FIELD_CLASS}
                />
              </Field>
              <Field label="Estado">
                <input
                  value={testState}
                  onChange={(event) => setTestState(event.target.value)}
                  placeholder="NY"
                  maxLength={2}
                  className={cn(FIELD_CLASS, "uppercase")}
                />
              </Field>
            </div>
            <Field label="Nicho">
              <SelectMenu
                value={testTrade}
                onChange={setTestTrade}
                placeholder="Trade"
                className="w-full"
                buttonClassName="w-full"
                options={(scripts.length
                  ? scripts.map((item) => ({
                      value: item.trade_code,
                      label: item.trade_code.replace(/_/g, " "),
                    }))
                  : [{ value: "remodeling", label: "remodeling" }])}
              />
            </Field>
            <Field
              label="Nome da empresa"
              hint="Deixa vazio para ouvir o fallback “Hi Contractor”."
            >
              <input
                value={testCompanyName}
                onChange={(event) => setTestCompanyName(event.target.value)}
                placeholder="Ex.: Example Contracting"
                className={FIELD_CLASS}
              />
            </Field>
            <button
              type="button"
              onClick={() => void fireTestCall()}
              disabled={working === "test-call"}
              className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-emerald-500 px-3 py-2.5 text-xs font-bold text-[#052018] transition hover:bg-emerald-400 disabled:opacity-50"
            >
              {working === "test-call" ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <PhoneCall className="h-4 w-4" />
              )}
              Disparar Test Call
            </button>
            <p className="text-[11px] leading-relaxed text-slate-400">
              O teste mantém a linha aberta até 120 s. A tecla 2 faz opt-out,
              diz “Goodbye” e encerra a chamada.
            </p>
          </div>
        </Card>

      <Card
        title="Live calls"
        icon={<PhoneCall className="h-4 w-4 text-emerald-400" />}
        hint="Campanha de hoje ou a que estiver a correr. Atualiza a cada 30 s; alterna no seletor para ver outra campanha."
        className="order-1 xl:order-1"
        action={
          <label className="flex max-w-full items-center gap-2 text-[11px] text-slate-400">
            <span className="whitespace-nowrap font-semibold uppercase tracking-wide">
              Campanha
            </span>
            <select
              aria-label="Campanha do Live calls"
              value={liveCampaignId === null ? "" : String(liveCampaignId)}
              onChange={(event) =>
                setLiveCampaignId(
                  event.target.value ? Number(event.target.value) : null
                )
              }
              className="max-w-[320px] rounded-lg border border-slate-600 bg-slate-950 px-2.5 py-1.5 text-xs font-medium text-white outline-none focus:border-emerald-400"
            >
              <option value="">Auto — campanha de hoje</option>
              {(campaignsData?.campaigns ?? []).map((campaign) => (
                <option key={campaign.id} value={campaign.id}>
                  #{campaign.id} {campaign.name} · {campaign.calls_started}/
                  {campaign.quota_total ?? campaign.max_calls}
                </option>
              ))}
            </select>
          </label>
        }
      >
        <div className="grid grid-cols-2 gap-2 xl:grid-cols-4">
          <Stat
            label="Campanha"
            value={liveData?.campaign?.status ?? "—"}
            sub={`#${liveData?.campaign?.id ?? "—"} · ${liveData?.campaign?.city ?? ""}`}
          />
          <Stat
            label="Planeadas"
            value={String(liveData?.day_cycle.planned_calls ?? 0)}
            sub={`feitas ${liveData?.day_cycle.calls_done ?? 0}`}
          />
          <Stat
            label="Faltam"
            value={String(liveData?.day_cycle.calls_remaining ?? 0)}
            sub="para fechar o ciclo"
          />
          <Stat
            label="Início"
            value={`${liveData?.campaign?.start_hour_et ?? 9}:00 ET`}
            sub="hora local"
          />
          <Stat
            label="Fim previsto"
            value={
              liveData?.day_cycle.estimated_finish_at
                ? new Date(liveData.day_cycle.estimated_finish_at).toLocaleTimeString(
                    "en-US",
                    {
                      hour: "2-digit",
                      minute: "2-digit",
                      timeZone: "America/New_York",
                    }
                  )
                : "—"
            }
            sub={`${liveData?.day_cycle.estimated_finish_earliest ? "± jitter 60–90s" : ""}`}
          />
          <Stat
            label="Atendidos reais"
            value={String(liveData?.summary.real_attended ?? 0)}
            sub={`${liveData?.summary.answer_rate ?? 0}% resposta`}
          />
          <Stat
            label="Desligados/falhados"
            value={String((liveData?.summary.disconnected ?? 0) + (liveData?.summary.failed ?? 0))}
            sub={`${liveData?.summary.voicemail ?? 0} voicemail · ${liveData?.summary.failed ?? 0} falhas`}
          />
          <Stat
            label="Opt-outs (tecla 2)"
            value={String(liveData?.summary.optouts ?? 0)}
            sub={`${liveData?.summary.optout_rate ?? 0}% · bloqueados`}
          />
        </div>

        <div className="mt-4">
          <div className="flex items-center justify-between text-[10px]">
            <p className="font-semibold uppercase tracking-wide text-slate-500">
              Termómetro da copy — escuta real
            </p>
            <p className="text-slate-500">
              {liveData?.thermometer.total ?? 0} chamadas não-voicemail
            </p>
          </div>
          <div className="mt-1.5 flex h-3 overflow-hidden rounded-full bg-white/5">
            <div
              className="bg-rose-500"
              style={{ width: `${liveData?.thermometer.red_pct ?? 0}%` }}
              title={`<15s: ${liveData?.thermometer.red ?? 0}`}
            />
            <div
              className="bg-amber-400"
              style={{ width: `${liveData?.thermometer.yellow_pct ?? 0}%` }}
              title={`15–39s: ${liveData?.thermometer.yellow ?? 0}`}
            />
            <div
              className="bg-emerald-500"
              style={{ width: `${liveData?.thermometer.green_pct ?? 0}%` }}
              title={`≥40s: ${liveData?.thermometer.green ?? 0}`}
            />
          </div>
          <div className="mt-1 flex justify-between text-[10px]">
            <span className="text-rose-300">
              Vermelho &lt;15s · {liveData?.thermometer.red_pct ?? 0}%
            </span>
            <span className="text-amber-300">
              Amarelo 15–39s · {liveData?.thermometer.yellow_pct ?? 0}%
            </span>
            <span className="text-emerald-300">
              Verde ≥40s · {liveData?.thermometer.green_pct ?? 0}%
            </span>
          </div>
        </div>

        <div className="mt-4 overflow-x-auto rounded-xl border border-slate-700/60">
          <table className="w-full min-w-[680px] text-left text-xs">
            <thead className="bg-slate-900/80 text-[10px] uppercase tracking-[0.12em] text-slate-400">
              <tr>
                <th className="px-3 py-2">Empresa</th>
                <th className="px-3 py-2">Nicho</th>
                <th className="px-3 py-2">Estado</th>
                <th className="px-3 py-2 text-right">Em curso</th>
                <th className="px-3 py-2 text-right">Escuta</th>
              </tr>
            </thead>
            <tbody>
              {(liveData?.active_calls ?? []).map((call) => (
                <tr key={call.id} className="border-t border-slate-800/80">
                  <td className="px-3 py-2 font-medium text-slate-100">
                    {call.company || "—"}
                  </td>
                  <td className="px-3 py-2 text-slate-300">{call.trade || "—"}</td>
                  <td className="px-3 py-2 text-slate-300">{call.status}</td>
                  <td className="px-3 py-2 text-right tabular-nums text-cyan-300">
                    {call.elapsed_seconds}s
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-emerald-300">
                    {call.listen_seconds}s
                  </td>
                </tr>
              ))}
              {!liveData?.active_calls?.length ? (
                <tr>
                  <td colSpan={5} className="px-3 py-6 text-center text-slate-500">
                    Sem chamadas ativas neste instante.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>

      </Card>
      </div>

      <div className={tab === "overview" ? "" : "hidden"}>
        <SectionHeader
          eyebrow="Consolidado"
          title="Desempenho histórico"
          description="Resultados do período escolhido: atendimento, engagement, custo real e retorno. Esta área responde a “o que já aconteceu”."
          icon={<TrendingUp className="h-4 w-4" />}
        />
      </div>
      <Card
        title="Desempenho do período"
        icon={<Gauge className="h-4 w-4 text-emerald-400" />}
        hint="Métricas consolidadas de chamadas, custo e conversão no período selecionado."
        action={
          <SelectMenu
            value={String(metricsDays)}
            onChange={(value) => setMetricsDays(Number(value))}
            placeholder="30 dias"
            className="min-w-[110px]"
            options={[
              { value: "7", label: "7 dias" },
              { value: "30", label: "30 dias" },
              { value: "90", label: "90 dias" },
            ]}
          />
        }
        className={tab === "overview" ? "" : "hidden"}
      >
        <div className="grid grid-cols-2 gap-2 md:grid-cols-3 xl:grid-cols-6">
          <GaugeCard
            label="Answer Rate"
            value={metrics?.summary.answer_rate ?? 0}
            sub={`${metrics?.summary.answered ?? 0}/${metrics?.summary.dialed ?? 0} atendidas`}
            tone={gaugeTone(metrics?.summary.answer_rate ?? 0, 40, 25)}
          />
          <GaugeCard
            label="Drop / Voicemail"
            value={metrics?.summary.drop_rate ?? 0}
            sub={`${metrics?.summary.unanswered ?? 0} sem resposta`}
            tone={
              (metrics?.summary.drop_rate ?? 0) <= 40
                ? "emerald"
                : (metrics?.summary.drop_rate ?? 0) <= 60
                  ? "amber"
                  : "rose"
            }
          />
          <GaugeCard
            label="Engagement ≥30s"
            value={metrics?.summary.engagement_rate ?? 0}
            sub={`${metrics?.summary.engaged ?? 0} chamadas`}
            tone={gaugeTone(metrics?.summary.engagement_rate ?? 0, 50, 30)}
          />
        </div>
        <div className="mt-3 grid grid-cols-2 gap-2 md:grid-cols-4">
          <Stat
            label="Listen médio"
            value={`${metrics?.summary.avg_listen_seconds ?? 0}s`}
            sub="chamadas atendidas"
          />
          <Stat
            label="Custo"
            value={money0(metrics?.summary.cost_usd ?? 0)}
            tone="amber"
          />
          <Stat
            label="Chamadas"
            value={String(metrics?.summary.dialed ?? 0)}
            sub="discadas no período"
          />
          <Stat
            label="Custo / atendida"
            value={money2(
              (metrics?.summary.cost_usd ?? 0) /
                Math.max(1, metrics?.summary.answered ?? 0)
            )}
            tone="amber"
            sub="custo real médio"
          />
        </div>
        <div className="mt-4 overflow-x-auto rounded-xl border border-slate-700/60">
          <table className="w-full min-w-[820px] text-left text-xs">
            <thead className="bg-slate-900/80 text-[10px] uppercase tracking-[0.12em] text-slate-400">
              <tr>
                <th className="px-3 py-2">Discadas</th>
                <th className="px-3 py-2">Atendidas</th>
                <th className="px-3 py-2">Answer rate</th>
                <th className="px-3 py-2">Engajadas ≥30s</th>
                <th className="px-3 py-2">Custo</th>
                <th className="px-3 py-2">Receita</th>
                <th className="px-3 py-2">Net</th>
                <th className="px-3 py-2">Custo / atendida</th>
              </tr>
            </thead>
            <tbody>
              <tr className="border-t border-slate-800 text-slate-200">
                <td className="px-3 py-2 tabular-nums">{metrics?.summary.dialed ?? 0}</td>
                <td className="px-3 py-2 tabular-nums">{metrics?.summary.answered ?? 0}</td>
                <td className="px-3 py-2 tabular-nums text-emerald-300">
                  {metrics?.summary.answer_rate ?? 0}%
                </td>
                <td className="px-3 py-2 tabular-nums">{metrics?.summary.engaged ?? 0}</td>
                <td className="px-3 py-2 tabular-nums text-amber-300">
                  {money2(metrics?.summary.cost_usd ?? 0)}
                </td>
                <td className="px-3 py-2 tabular-nums text-sky-300">
                  {money2(metrics?.summary.revenue_usd ?? 0)}
                </td>
                <td className="px-3 py-2 tabular-nums text-emerald-300">
                  {money2(metrics?.summary.net_usd ?? 0)}
                </td>
                <td className="px-3 py-2 tabular-nums text-amber-300">
                  {money2(
                    (metrics?.summary.cost_usd ?? 0) /
                      Math.max(1, metrics?.summary.answered ?? 0)
                  )}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        {!metrics?.summary.dialed ? (
          <p className="mt-3 text-[11px] text-slate-500">
            Sem chamadas no período. Inicia uma campanha em “Campanhas” para
            alimentar o funil.
          </p>
        ) : null}
      </Card>

      <div
        className={cn(
          "mb-5 grid gap-4 lg:grid-cols-2",
          tab === "overview" ? "" : "hidden"
        )}
      >
        <Card
          title="Funil de conversão"
          icon={<TrendingUp className="h-4 w-4 text-sky-400" />}
          hint="Discadas → atendidas → escuta → vitrine → checkout"
        >
          <FunnelChart
            funnel={
              metrics?.funnel ?? {
                dialed: 0,
                answered: 0,
                engaged: 0,
                accepts: 0,
                clicks: 0,
                checkouts: 0,
                revenue_usd: 0,
              }
            }
          />
        </Card>
        <Card
          title="Retenção de áudio"
          icon={<Activity className="h-4 w-4 text-emerald-400" />}
          hint="% de chamadas atendidas que continuam a ouvir"
        >
          <RetentionChart
            buckets={metrics?.retention ?? []}
            answered={metrics?.summary.answered ?? 0}
          />
        </Card>
      </div>

      <div className={tab === "overview" ? "" : "hidden"}>
        <SectionHeader
          eyebrow="Capacidade"
          title="Cobertura e liquidez"
          description="Stock chamável por cidade e nicho, com separação entre inventário exato e fallback. Tabela operacional, sem duplicar os cards de campanha."
          icon={<Database className="h-4 w-4" />}
        />
        <Card
          title="Liquidez por cidade e nicho"
          icon={<BarChart3 className="h-4 w-4 text-indigo-400" />}
          hint="Top 12 por disponibilidade. Usa os segmentos materializados; reconstrói os segmentos se a tabela estiver vazia."
          className="mb-6"
        >
          <div className="mb-3 flex flex-wrap items-center gap-2 text-xs">
            <span className="rounded-full border border-emerald-400/20 bg-emerald-500/10 px-3 py-1 text-emerald-200">
              Exact disponível: <b>{liquidityData?.exact_available ?? 0}</b>
            </span>
            <span className="rounded-full border border-slate-600/70 bg-slate-900/60 px-3 py-1 text-slate-300">
              Combinações: <b>{liquidityRows.length}</b>
            </span>
            <span className="text-[10px] text-slate-500">
              Atualizado: {liquidityData?.generated_at ? new Date(liquidityData.generated_at).toLocaleString("pt-PT") : "—"}
            </span>
          </div>
          <div className="max-h-[420px] overflow-auto rounded-xl border border-slate-700/60">
            <table className="w-full min-w-[880px] text-left text-xs">
              <thead className="sticky top-0 bg-slate-900/95 text-[10px] uppercase tracking-[0.12em] text-slate-400">
                <tr>
                  <th className="px-3 py-2">Cidade</th>
                  <th className="px-3 py-2">Nicho</th>
                  <th className="px-3 py-2">Escopo</th>
                  <th className="px-3 py-2 text-right">Disponível</th>
                  <th className="px-3 py-2 text-right">Usado 7d</th>
                  <th className="px-3 py-2 text-right">Total</th>
                  <th className="px-3 py-2 text-right">Chamáveis</th>
                  <th className="px-3 py-2 text-right">Vitrine</th>
                </tr>
              </thead>
              <tbody>
                {liquidityRows.slice(0, 12).map((row) => (
                  <tr
                    key={`${row.city}-${row.trade}`}
                    className="border-t border-slate-800/80 text-slate-300 hover:bg-white/[0.03]"
                  >
                    <td className="px-3 py-2 font-semibold text-slate-100">
                      {row.city}
                      <span className="ml-1 text-[10px] text-slate-500">{row.state}</span>
                    </td>
                    <td className="px-3 py-2">{row.trade}</td>
                    <td className="px-3 py-2">
                      <span
                        className={cn(
                          "rounded-full border px-2 py-0.5 text-[10px] font-semibold",
                          row.exact
                            ? "border-emerald-400/20 bg-emerald-500/10 text-emerald-300"
                            : "border-amber-400/20 bg-amber-500/10 text-amber-300"
                        )}
                      >
                        {row.scope}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-right font-bold tabular-nums text-emerald-300">
                      {row.available}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums">{row.used_7d}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{row.total}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{row.callable}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{row.showcase_items}</td>
                  </tr>
                ))}
                {!liquidityRows.length ? (
                  <tr>
                    <td colSpan={8} className="px-3 py-6 text-center text-slate-500">
                      Sem stock materializado. Reconstrói os segmentos na aba
                      “Segmentos”.
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </Card>
      </div>

      <Card
        title="Matriz de conversão cidade × nicho"
        icon={<BarChart3 className="h-4 w-4 text-indigo-400" />}
        hint="Verde = lucro; vermelho = burn. Ordenado por net."
        className="hidden"
      >
        <HeatmapMatrix rows={metrics?.by_city_trade ?? []} />
      </Card>

      <div className="hidden">
        <Card
          title="Aceite por estado"
          icon={<MapPin className="h-4 w-4 text-sky-400" />}
          hint="Aceite = pressionou 1 ou disse yes; assinatura = Stripe concluído."
        >
          <BreakdownTable
            rows={metrics?.by_state ?? []}
            label={(row) => row.state || "—"}
          />
        </Card>
        <Card
          title="Aceite por cidade"
          icon={<Building2 className="h-4 w-4 text-indigo-400" />}
          hint="Ordenado por taxa de aceite da voz."
        >
          <BreakdownTable
            rows={metrics?.by_city ?? []}
            label={(row) => `${row.city}, ${row.state || "—"}`}
          />
        </Card>
        <Card
          title="Aceite por nicho"
          icon={<BarChart3 className="h-4 w-4 text-emerald-400" />}
          hint="Quais trades aceitam mais e convertem em $120."
        >
          <BreakdownTable
            rows={metrics?.by_trade ?? []}
            label={(row) => row.trade}
          />
        </Card>
      </div>

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
          hint="Qualquer lista crua: CSV, TXT, uma coluna ou linhas soltas. O backend deteta telefones e DNC/clean."
        >
          <input
            type="file"
            accept=".csv,.txt,.tsv,text/csv,text/plain"
            onChange={(event) => void readFile(event.target.files?.[0], setDncCsv)}
            className="mb-2 block w-full text-[11px] text-slate-400 file:mr-2 file:rounded-lg file:border-0 file:bg-emerald-500/15 file:px-3 file:py-1.5 file:text-[11px] file:font-semibold file:text-emerald-200"
          />
          <textarea
            value={dncCsv}
            onChange={(event) => setDncCsv(event.target.value)}
            rows={3}
            placeholder="Ou cola aqui a lista crua: 617-555-0123, (214) 555-0199, ..."
            className="mb-2 w-full rounded-lg border border-white/10 bg-black/20 px-2.5 py-1.5 text-[11px] text-slate-200 placeholder:text-slate-600"
          />
          <label className="mb-2 flex items-start gap-2 text-[10px] text-slate-400">
            <input
              type="checkbox"
              checked={dncScrub}
              onChange={(event) => setDncScrub(event.target.checked)}
              className="mt-0.5 accent-emerald-500"
            />
            <span>
              Lista oficial completa — aplicar à base (scrub). Números fora da
              lista ficam limpos; listados ficam bloqueados.
            </span>
          </label>
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
          {stats?.staging_mode ? (
            <div className="mt-3 rounded-lg border border-amber-400/20 bg-amber-500/10 p-2.5">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-[10px] text-amber-200">
                  Staging ativo: DNC em falta é auto-limpo e o Telnyx fica em
                  dry-run.
                </p>
                <button
                  type="button"
                  onClick={() => void stagingClear()}
                  disabled={working === "staging-clear"}
                  className="inline-flex items-center gap-1 rounded-md bg-amber-400 px-2.5 py-1 text-[9px] font-bold text-[#1a1405] hover:bg-amber-300 disabled:opacity-50"
                >
                  {working === "staging-clear" ? (
                    <Loader2 className="h-3 w-3 animate-spin" />
                  ) : (
                    <CheckCircle2 className="h-3 w-3" />
                  )}
                  Desobstruir staging
                </button>
              </div>
            </div>
          ) : null}
          <p className="mt-2 text-[10px] text-slate-600">
            Exemplos aceites: lista de números, CSV com cabeçalhos arbitrários,
            TSV, `phone,listed`, ou números com “clean”/“DNC”. Duplicados são
            consolidados; se houver conflito, prevalece “listado”.
          </p>
        </Card>
      </div>

      <Card
        title="Roteiros de voz"
        icon={<FileText className="h-4 w-4 text-indigo-400" />}
        hint="Inglês US, versionado. Só um roteiro Approved pode ser usado em chamadas reais."
        action={
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone="emerald">
              {scripts.filter((item) => item.status === "approved").length} aprovados
            </Badge>
            <button
              type="button"
              onClick={() => void approveAllScripts()}
              disabled={working === "scripts-approve-all"}
              className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-500 px-3 py-1.5 text-[10px] font-bold text-[#062017] hover:bg-emerald-400 disabled:opacity-50"
            >
              {working === "scripts-approve-all" ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <CheckCircle2 className="h-3.5 w-3.5" />
              )}
              Aprovar Todos
            </button>
          </div>
        }
        className={tab === "scripts" ? "" : "hidden"}
      >
        <div className="grid gap-4 lg:grid-cols-[230px_1fr]">
          <div className="max-h-[560px] space-y-1 overflow-y-auto pr-1">
            {scripts.map((item) => (
              <button
                key={item.trade_code}
                type="button"
                onClick={() => setScriptTrade(item.trade_code)}
                className={cn(
                  "flex w-full items-center justify-between gap-2 rounded-lg border px-2.5 py-2 text-left text-[10px]",
                  scriptTrade === item.trade_code
                    ? "border-indigo-400/30 bg-indigo-500/10 text-indigo-100"
                    : "border-white/5 bg-white/[0.02] text-slate-300 hover:bg-white/[0.05]"
                )}
              >
                <span className="font-semibold">{item.trade_code}</span>
                <span className="flex items-center gap-1">
                  <Badge tone={item.status === "approved" ? "emerald" : "amber"}>
                    {item.status}
                  </Badge>
                  <span className="text-[9px] text-slate-500">v{item.version}</span>
                </span>
              </button>
            ))}
          </div>

          <div className="space-y-3">
            {currentScript ? (
              <>
                <div className="flex flex-wrap items-center gap-2">
                  <p className="text-sm font-black text-white">
                    {currentScript.trade_code}
                  </p>
                  <Badge
                    tone={currentScript.status === "approved" ? "emerald" : "amber"}
                  >
                    {currentScript.status}
                  </Badge>
                  <span className="text-[10px] text-slate-500">
                    versão {currentScript.version}
                  </span>
                </div>

                <label className="block text-[10px] text-slate-500">
                  Telnyx Assistant ID
                  <input
                    value={scriptAssistantId}
                    onChange={(event) => setScriptAssistantId(event.target.value)}
                    placeholder="assistant-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
                    className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 px-2.5 py-1.5 font-mono text-[10px] text-slate-200 placeholder:text-slate-600"
                  />
                </label>

                <label className="block text-[10px] text-slate-500">
                  Disclosure legal (EN)
                  <textarea
                    value={scriptDisclosure}
                    onChange={(event) => setScriptDisclosure(event.target.value)}
                    rows={2}
                    className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 px-2.5 py-1.5 text-[10px] text-slate-200"
                  />
                </label>

                <label className="block text-[10px] text-slate-500">
                  Prompt / instructions (EN)
                  <textarea
                    value={scriptBody}
                    onChange={(event) => setScriptBody(event.target.value)}
                    rows={16}
                    className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 px-2.5 py-2 font-mono text-[10px] leading-relaxed text-slate-200"
                  />
                </label>

                <div className="flex flex-wrap items-end gap-2">
                  <label className="text-[10px] text-slate-500">
                    Empresa (preview)
                    <input
                      value={previewCompany}
                      onChange={(event) => setPreviewCompany(event.target.value)}
                      className="mt-1 block w-40 rounded-lg border border-white/10 bg-black/20 px-2.5 py-1.5 text-[10px] text-slate-200"
                    />
                  </label>
                  <label className="text-[10px] text-slate-500">
                    Cidade (preview)
                    <input
                      value={previewCity}
                      onChange={(event) => setPreviewCity(event.target.value)}
                      className="mt-1 block w-36 rounded-lg border border-white/10 bg-black/20 px-2.5 py-1.5 text-[10px] text-slate-200"
                    />
                  </label>
                  <button
                    type="button"
                    onClick={() => void previewScript()}
                    disabled={working === "script-preview"}
                    className="rounded-lg border border-sky-400/30 bg-sky-500/10 px-3 py-1.5 text-[10px] font-semibold text-sky-200 hover:bg-sky-500/20 disabled:opacity-50"
                  >
                    Preview
                  </button>
                  <button
                    type="button"
                    onClick={() => void saveScript()}
                    disabled={working === "script-save"}
                    className="rounded-lg border border-white/10 px-3 py-1.5 text-[10px] font-semibold text-slate-300 hover:bg-white/5 disabled:opacity-50"
                  >
                    Guardar draft
                  </button>
                  <button
                    type="button"
                    onClick={() => void approveScript()}
                    disabled={working === "script-approve"}
                    className="rounded-lg bg-emerald-500 px-3 py-1.5 text-[10px] font-bold text-[#062017] hover:bg-emerald-400 disabled:opacity-50"
                  >
                    Aprovar
                  </button>
                  <button
                    type="button"
                    onClick={() => void syncScript()}
                    disabled={working === "script-sync"}
                    className="rounded-lg border border-indigo-400/30 bg-indigo-500/10 px-3 py-1.5 text-[10px] font-semibold text-indigo-200 hover:bg-indigo-500/20 disabled:opacity-50"
                  >
                    Sync Telnyx
                  </button>
                </div>

                {scriptPreview ? (
                  <div className="rounded-xl border border-white/10 bg-[#0b0f15] p-3">
                    <p className="mb-2 text-[9px] font-semibold uppercase tracking-wide text-slate-500">
                      Preview renderizado · {scriptPreview.status} · v
                      {scriptPreview.version}
                    </p>
                    <pre className="max-h-72 overflow-auto whitespace-pre-wrap text-[10px] leading-relaxed text-slate-300">
                      {scriptPreview.body}
                    </pre>
                  </div>
                ) : null}
              </>
            ) : (
              <p className="text-[11px] text-slate-600">
                Ainda sem roteiros. O seed inicial cria drafts por trade.
              </p>
            )}
          </div>
        </div>
      </Card>

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
        <div className="grid grid-cols-3 gap-2 md:grid-cols-3">
          <Stat label="Páginas" value={String(showcaseStats?.pages ?? 0)} tone="emerald" />
          <Stat label="Links" value={String(showcaseStats?.links ?? 0)} />
          <Stat label="Visitas" value={String(showcaseStats?.visits ?? 0)} />
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
          <label className="text-[10px] text-slate-500">
            Orçamento total ($)
            <input
              type="number"
              min={0}
              step={1}
              value={budgetTotal}
              onChange={(event) => setBudgetTotal(Number(event.target.value))}
              className="mt-1 block w-24 rounded-lg border border-white/10 bg-black/20 px-2.5 py-1.5 text-[11px] text-slate-200"
            />
          </label>
          <label className="text-[10px] text-slate-500">
            Orçamento / dia ($)
            <input
              type="number"
              min={0}
              step={0.5}
              value={budgetDaily}
              onChange={(event) => setBudgetDaily(Number(event.target.value))}
              className="mt-1 block w-24 rounded-lg border border-white/10 bg-black/20 px-2.5 py-1.5 text-[11px] text-slate-200"
            />
          </label>
          <label className="text-[10px] text-slate-500">
            Máx. dias
            <input
              type="number"
              min={0}
              step={1}
              value={maxDays}
              onChange={(event) => setMaxDays(Number(event.target.value))}
              className="mt-1 block w-20 rounded-lg border border-white/10 bg-black/20 px-2.5 py-1.5 text-[11px] text-slate-200"
            />
          </label>
          <label className="text-[10px] text-slate-500">
            Início (ET)
            <input
              type="number"
              min={0}
              max={23}
              step={1}
              value={startHour}
              onChange={(event) => setStartHour(Number(event.target.value))}
              className="mt-1 block w-20 rounded-lg border border-white/10 bg-black/20 px-2.5 py-1.5 text-[11px] text-slate-200"
            />
          </label>
          <label className="text-[10px] text-slate-500">
            Intervalo (s)
            <input
              type="number"
              min={0}
              step={30}
              value={callInterval}
              onChange={(event) => setCallInterval(Number(event.target.value))}
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
                {campaign.budget_total_usd ? (
                  <span className="text-slate-600">
                    ${campaign.budget_total_usd.toFixed(0)} total · $
                    {(campaign.budget_daily_usd ?? 0).toFixed(2)}/dia ·{" "}
                    {campaign.max_days || "∞"} dias · início{" "}
                    {campaign.start_hour_et ?? 9}:00 ET · intervalo{" "}
                    {campaign.call_interval_seconds ?? 30}s
                  </span>
                ) : null}
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
          <StatusPill state="info">
            {(queue?.total ?? 0).toLocaleString("pt-PT")} empresas
          </StatusPill>
        }
      >
        <div className="mb-4 space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <SelectMenu
              value={cityFilter}
              onChange={setCityFilter}
              placeholder="Todas as cidades"
              className="min-w-[150px]"
              options={[
                { value: "", label: "Todas as cidades" },
                ...(stats?.by_city ?? []).map((group) => ({
                  value: group.name,
                  label: `${group.name} (${group.total})`,
                })),
              ]}
            />
            <SelectMenu
              value={tradeFilter}
              onChange={setTradeFilter}
              placeholder="Todos os nichos"
              className="min-w-[150px]"
              options={[
                { value: "", label: "Todos os nichos" },
                ...(stats?.by_trade ?? []).map((group) => ({
                  value: group.name,
                  label: `${group.name} (${group.total})`,
                })),
              ]}
            />
            <SelectMenu
              value={statusFilter}
              onChange={setStatusFilter}
              placeholder="Todos os estados"
              className="min-w-[140px]"
              options={[
                { value: "", label: "Todos os estados" },
                { value: "ready", label: "Prontas" },
                { value: "do_not_call", label: "Não contactar" },
                { value: "meeting", label: "Reunião" },
                { value: "invalid", label: "Inválidas" },
              ]}
            />
            <DateField label="de" value={dateFrom} onChange={setDateFrom} />
            <DateField label="até" value={dateTo} onChange={setDateTo} />
            <label className="inline-flex cursor-pointer items-center gap-2 rounded-xl border border-white/10 bg-white/[0.03] px-3 py-1.5 text-[10px] font-semibold text-slate-400">
              <input
                type="checkbox"
                checked={includeBlocked}
                onChange={(event) => setIncludeBlocked(event.target.checked)}
                className="accent-emerald-400"
              />
              Mostrar bloqueadas
            </label>
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="mr-1 text-[9px] font-bold uppercase tracking-[0.16em] text-slate-600">
              Score
            </span>
            {SCORE_RANGES.map((range) => (
              <FilterChip
                key={range.id}
                active={scoreRange === range.id}
                onClick={() => setScoreRange(range.id)}
              >
                {range.label}
              </FilterChip>
            ))}
            {scoreRange !== "all" || statusFilter || dateFrom || dateTo ? (
              <button
                type="button"
                onClick={() => {
                  setScoreRange("all");
                  setStatusFilter("");
                  setDateFrom("");
                  setDateTo("");
                }}
                className="ml-1 rounded-full border border-white/10 px-2.5 py-1.5 text-[10px] font-semibold text-slate-500 hover:text-slate-200"
              >
                limpar
              </button>
            ) : null}
          </div>
          {scoreDist ? (
            <div className="grid gap-3 rounded-2xl border border-white/[0.06] bg-white/[0.02] p-3 lg:grid-cols-[1fr_260px]">
              <div className="space-y-2">
                <div className="flex items-center justify-between text-[10px] text-slate-500">
                  <span>distribuição do score V2</span>
                  <span className="tabular-nums">
                    média {formatScore(scoreDist.avg)} · {scoreDist.min}–{scoreDist.max}
                  </span>
                </div>
                <ScoreHistogram buckets={scoreDist.buckets} total={scoreDist.total} />
              </div>
              <div className="flex flex-wrap content-start gap-1.5">
                {(["elite", "strong", "developing", "low"] as const).map((band) => (
                  <span
                    key={band}
                    className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-1 text-[9px] font-bold ${SCORE_BAND_META[band].chip}`}
                  >
                    <span className={`h-1.5 w-1.5 rounded-full ${SCORE_BAND_META[band].dot}`} />
                    {SCORE_BAND_META[band].label}
                  </span>
                ))}
                <p className="mt-2 w-full text-[10px] leading-relaxed text-slate-500">
                  {scoreDist.snapshots.toLocaleString("pt-PT")} snapshots explicáveis ·{" "}
                  {scoreDist.distinct_scores} valores distintos
                </p>
              </div>
            </div>
          ) : null}
        </div>
        {isLoading && !queue ? (
          <div className="flex items-center gap-2 py-8 text-xs text-slate-400">
            <Loader2 className="h-4 w-4 animate-spin" /> A carregar fila…
          </div>
        ) : !queue?.items.length ? (
          <div className="rounded-xl border border-dashed border-white/10 p-8 text-center">
            <Building2 className="mx-auto mb-2 h-6 w-6 text-slate-600" />
            <p className="text-xs text-slate-400">Sem empresas nesta vista.</p>
            <p className="mt-1 text-[10px] text-slate-600">
              Sincroniza licenças em “Fontes” ou ajusta os filtros.
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
                        <ScoreBar score={company.score} />
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
        {queue?.items.length ? (
          <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-white/5 pt-3 text-[10px] text-slate-500">
            <span>
              Mostrando {pageStart}–{pageEnd} de {totalItems}
            </span>
            <div className="flex items-center gap-1.5">
              <button
                type="button"
                onClick={() => setPage((current) => Math.max(1, current - 1))}
                disabled={page <= 1}
                className="rounded-lg border border-white/10 bg-white/[0.03] px-2.5 py-1 font-semibold text-slate-300 hover:bg-white/[0.08] disabled:opacity-35"
              >
                Anterior
              </button>
              <span className="rounded-lg border border-white/10 bg-[#1a1d24] px-2.5 py-1 font-semibold text-white">
                Página {page} de {totalPages}
              </span>
              <button
                type="button"
                onClick={() =>
                  setPage((current) => Math.min(totalPages, current + 1))
                }
                disabled={page >= totalPages}
                className="rounded-lg border border-white/10 bg-white/[0.03] px-2.5 py-1 font-semibold text-slate-300 hover:bg-white/[0.08] disabled:opacity-35"
              >
                Próxima
              </button>
            </div>
          </div>
        ) : null}
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
                <p className="flex flex-wrap items-center gap-2 text-[10px] font-semibold uppercase tracking-wide text-slate-500">
                  <span>Empresa {selected.id}</span>
                  <span
                    className={`rounded-full border px-2 py-0.5 text-[9px] font-bold ${SCORE_BAND_META[scoreBand(selected.score)].chip}`}
                  >
                    {SCORE_BAND_META[scoreBand(selected.score)].label} ·{" "}
                    {formatScore(selected.score)}/65
                  </span>
                  {scoreDetail?.snapshot ? (
                    <span className="rounded-full border border-white/10 bg-white/[0.04] px-2 py-0.5 text-[9px] text-slate-400">
                      {scoreDetail.snapshot.version}
                    </span>
                  ) : null}
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

            <div className="mb-4 rounded-xl border border-white/[0.06] bg-white/[0.02] p-3">
              <div className="mb-2 flex items-center justify-between gap-2">
                <p className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                  <Gauge className="h-3 w-3" /> Score V2 · componentes
                </p>
                <span className="text-[10px] text-slate-500">
                  {scoreDetail?.snapshot?.computed_at
                    ? fmtWhen(scoreDetail.snapshot.computed_at)
                    : "sem snapshot"}
                </span>
              </div>
              <ScoreBar score={scoreDetail?.score ?? selected.score} />
              {scoreLoading ? (
                <div className="mt-3 flex items-center gap-2 text-[10px] text-slate-500">
                  <Loader2 className="h-3 w-3 animate-spin" /> a carregar snapshot…
                </div>
              ) : scoreDetail?.snapshot?.components ? (
                <>
                  <div className="mt-3 grid grid-cols-2 gap-2">
                    {Object.entries(scoreDetail.snapshot.components).map(([key, value]) => {
                      const meta = SCORE_COMPONENTS[key] ?? {
                        label: key.replaceAll("_", " "),
                        max: 1,
                        tone: "from-slate-400 to-slate-300",
                      };
                      const width =
                        key === "quality_penalty"
                          ? Math.min(100, (Number(value) / meta.max) * 100)
                          : Math.max(2, Math.min(100, (Number(value) / meta.max) * 100));
                      return (
                        <div key={key} className="rounded-lg border border-white/[0.05] bg-white/[0.02] p-2">
                          <div className="flex items-center justify-between text-[9px]">
                            <span className="text-slate-500">{meta.label}</span>
                            <span className="font-semibold tabular-nums text-slate-300">
                              {Number(value).toFixed(2)}
                            </span>
                          </div>
                          <div className="mt-1 h-1 overflow-hidden rounded-full bg-white/[0.06]">
                            <div
                              className={`h-full rounded-full bg-gradient-to-r ${meta.tone}`}
                              style={{ width: `${width}%` }}
                            />
                          </div>
                        </div>
                      );
                    })}
                  </div>
                  <div className="mt-2 flex items-center justify-between text-[9px] text-slate-600">
                    <span>
                      penalidade de qualidade{" "}
                      <b className={scoreDetail.snapshot.quality_penalty ? "text-rose-300" : "text-emerald-300"}>
                        {scoreDetail.snapshot.quality_penalty.toFixed(1)}
                      </b>
                    </span>
                    <span>snapshot {scoreDetail.snapshot.company_id}</span>
                  </div>
                </>
              ) : (
                <p className="mt-2 text-[10px] text-slate-500">
                  Sem snapshot explicável para esta empresa.
                </p>
              )}
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

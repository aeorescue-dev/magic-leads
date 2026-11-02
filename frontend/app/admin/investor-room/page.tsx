"use client";

import {
  Activity,
  AlertTriangle,
  ArrowLeft,
  BadgeDollarSign,
  BookOpen,
  Building2,
  CheckCircle2,
  CircleDollarSign,
  Container,
  Database,
  Download,
  FileText,
  FlaskConical,
  Gauge,
  GitBranch,
  Layers,
  Loader2,
  Lock,
  Printer,
  RefreshCcw,
  ShieldCheck,
  Sparkles,
  TrendingUp,
} from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import useSWR from "swr";

import {
  acceptInvestorNda,
  AdminApiError,
  downloadInvestorCsv,
  fetchInvestorRoom,
  refreshInvestorRoom,
  simulateInvestor,
  type InvestorRoom,
  type InvestorSimulation,
} from "@/lib/admin-api";
import { fmtWhen, scoreClasses } from "@/lib/system-health";

type Tab = "overview" | "buyer" | "assumptions";

const TABS: Array<{ id: Tab; label: string }> = [
  { id: "overview", label: "Overview" },
  { id: "buyer", label: "Comprador" },
  { id: "assumptions", label: "Premissas" },
];

const money = (value: number | null | undefined) =>
  value == null
    ? "—"
    : new Intl.NumberFormat("en-US", {
        style: "currency",
        currency: "USD",
        maximumFractionDigits: 0,
      }).format(value);

const money2 = (value: number | null | undefined) =>
  value == null
    ? "—"
    : new Intl.NumberFormat("en-US", {
        style: "currency",
        currency: "USD",
        maximumFractionDigits: 2,
      }).format(value);

const pct = (value: number | null | undefined, digits = 1) =>
  value == null ? "—" : `${value.toFixed(digits)}%`;

/** Milhares arredondados ($127k). */
const kRound = (value: number) => `$${Math.round(value / 1000)}k`;
/** Milhares truncados para o piso total ($421k). */
const kFloor = (value: number) => `$${Math.floor(value / 1000)}k`;
const kNum = (value: number) =>
  value >= 1000 ? `${(value / 1000).toFixed(1)}k` : String(value);

type BadgeTone = "slate" | "indigo" | "emerald" | "amber" | "rose" | "sky";

const BADGE_TONES: Record<BadgeTone, string> = {
  slate: "border-white/10 bg-white/5 text-slate-300",
  indigo: "border-indigo-400/25 bg-indigo-500/10 text-indigo-200",
  emerald: "border-emerald-400/25 bg-emerald-500/10 text-emerald-200",
  amber: "border-amber-400/25 bg-amber-500/10 text-amber-200",
  rose: "border-rose-400/25 bg-rose-500/10 text-rose-200",
  sky: "border-sky-400/25 bg-sky-500/10 text-sky-200",
};

function Badge({
  children,
  tone = "slate",
}: {
  children: ReactNode;
  tone?: BadgeTone;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold tracking-wide",
        BADGE_TONES[tone]
      )}
    >
      {children}
    </span>
  );
}

function confidenceBadge(confidence: string): { label: string; tone: BadgeTone } {
  const value = confidence.toLowerCase();
  if (
    value.includes("amostra") ||
    value.startsWith("baixa") ||
    value.startsWith("low")
  ) {
    return { label: "Amostra em Maturação", tone: "amber" };
  }
  if (value.startsWith("média") || value.startsWith("media") || value.startsWith("medium")) {
    return { label: "Amostra Consolidada", tone: "emerald" };
  }
  return { label: "Histórico Base", tone: "slate" };
}

function reconciliationBadge(status: string): { label: string; tone: BadgeTone } {
  switch (status) {
    case "ok":
      return { label: "Reconciliado", tone: "emerald" };
    case "cash_without_mapping":
      return { label: "Mapeamento Pendente", tone: "amber" };
    case "pro_active_without_access":
      return { label: "Auditoria de Acesso", tone: "amber" };
    case "stripe_events_without_checkout":
    case "access_without_verified_payment":
      return { label: "Reconciliação em Curso", tone: "amber" };
    default:
      return { label: "Em Auditoria", tone: "slate" };
  }
}

function cn(...values: Array<string | false | null | undefined>) {
  return values.filter(Boolean).join(" ");
}

function Card({
  title,
  icon,
  hint,
  children,
  className,
  action,
}: {
  title: string;
  icon: ReactNode;
  hint?: string;
  children: ReactNode;
  className?: string;
  action?: ReactNode;
}) {
  return (
    <section
      className={cn(
        "rounded-2xl border border-white/10 bg-[#10131a] p-5",
        className
      )}
    >
      <div className="mb-4 flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="flex items-center gap-2 text-sm font-bold text-slate-100">
            {icon}
            {title}
          </h2>
          {hint ? (
            <p className="mt-0.5 text-[11px] text-slate-500">{hint}</p>
          ) : null}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

function ScoreRing({ score, size = 112 }: { score: number; size?: number }) {
  const classes = scoreClasses(score);
  const stroke = 9;
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
        <span className={cn("text-2xl font-black tabular-nums", classes.text)}>
          {score.toFixed(0)}
        </span>
        <span className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">
          / 100
        </span>
      </div>
    </div>
  );
}

function Kpi({
  label,
  value,
  sub,
  tone = "slate",
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: "slate" | "emerald" | "amber" | "rose" | "indigo" | "sky";
}) {
  const toneClass = {
    slate: "text-slate-100",
    emerald: "text-emerald-300",
    amber: "text-amber-300",
    rose: "text-rose-300",
    indigo: "text-indigo-300",
    sky: "text-sky-300",
  }[tone];
  return (
    <div className="rounded-xl border border-white/5 bg-white/[0.02] p-3">
      <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">
        {label}
      </p>
      <p className={cn("mt-1 text-lg font-black tabular-nums", toneClass)}>
        {value}
      </p>
      {sub ? <p className="mt-0.5 text-[10px] text-slate-500">{sub}</p> : null}
    </div>
  );
}

function BigStat({
  label,
  value,
  unit,
  sub,
  chips,
  icon,
  accent,
}: {
  label: string;
  value: string;
  unit?: string;
  sub?: string;
  chips?: string[];
  icon: ReactNode;
  accent: { card: string; glow: string; icon: string };
}) {
  return (
    <div
      className={cn(
        "relative overflow-hidden rounded-2xl border p-5",
        accent.card
      )}
    >
      <div
        className={cn(
          "pointer-events-none absolute -right-8 -top-8 h-28 w-28 rounded-full blur-3xl",
          accent.glow
        )}
      />
      <div className="relative flex items-center justify-between">
        <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400">
          {label}
        </p>
        <span className={cn("rounded-lg p-1.5", accent.icon)}>{icon}</span>
      </div>
      <p className="relative mt-3 flex items-baseline gap-1.5">
        <span className="text-3xl font-black tracking-tight text-white tabular-nums">
          {value}
        </span>
        {unit ? (
          <span className="text-xs font-semibold text-slate-400">{unit}</span>
        ) : null}
      </p>
      {sub ? (
        <p className="relative mt-1 text-[11px] text-slate-400">{sub}</p>
      ) : null}
      {chips?.length ? (
        <div className="relative mt-3 flex flex-wrap gap-1.5">
          {chips.map((chip) => (
            <span
              key={chip}
              className="rounded-md bg-white/5 px-2 py-0.5 text-[10px] font-medium text-slate-400"
            >
              {chip}
            </span>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function Bar({
  value,
  max,
  tone = "bg-indigo-400",
}: {
  value: number;
  max: number;
  tone?: string;
}) {
  return (
    <div className="h-1.5 overflow-hidden rounded-full bg-white/10">
      <div
        className={cn("h-full rounded-full", tone)}
        style={{
          width: `${max > 0 ? Math.min(100, (value / max) * 100) : 0}%`,
        }}
      />
    </div>
  );
}

function AuditTrailCard({ rec }: { rec: InvestorRoom["reconciliation"] }) {
  const [open, setOpen] = useState(false);
  const badge = reconciliationBadge(rec.status);
  return (
    <section className="rounded-2xl border border-white/5 bg-white/[0.015] p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <ShieldCheck className="h-3.5 w-3.5 text-slate-500" />
          <h2 className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400">
            Status Financeiro · Audit Trail
          </h2>
          <Badge tone={badge.tone}>{badge.label}</Badge>
        </div>
        <button
          type="button"
          onClick={() => setOpen((value) => !value)}
          className="text-[10px] font-semibold text-slate-500 transition-colors hover:text-slate-300"
        >
          {open ? "Ocultar detalhe" : "Ver detalhe"}
        </button>
      </div>

      <div className="mt-3 grid grid-cols-2 gap-2 md:grid-cols-4">
        {[
          {
            label: "Passes com acesso",
            value: String(rec.access_passes),
            sub: `${rec.pro_active} em base histórica`,
          },
          {
            label: "Passes verificados",
            value: String(rec.verified_paid_passes),
            sub: "em reconciliação",
          },
          {
            label: "Cash Stripe 30d",
            value: money2(rec.cash_30d),
            sub: "sem cobranças mapeadas",
          },
          {
            label: "Checkouts completos",
            value: String(rec.completed_checkouts),
            sub: `${rec.stripe_completed_events} eventos Stripe`,
          },
        ].map((item) => (
          <div
            key={item.label}
            className="rounded-lg border border-white/5 bg-black/10 px-3 py-2"
          >
            <p className="text-[9px] font-semibold uppercase tracking-wide text-slate-500">
              {item.label}
            </p>
            <p className="mt-0.5 text-base font-black text-slate-200 tabular-nums">
              {item.value}
            </p>
            <p className="text-[9px] text-slate-600">{item.sub}</p>
          </div>
        ))}
      </div>

      {open ? (
        <div className="mt-3 space-y-1 border-t border-white/5 pt-3 text-[10px] text-slate-500">
          <p>
            <span className="text-slate-400">Estado técnico:</span> {rec.status}
            {rec.cash_mode ? ` · modo ${rec.cash_mode}` : ""}
            {rec.cash_status ? ` · cash ${rec.cash_status}` : ""}
          </p>
          <p>{rec.details}</p>
        </div>
      ) : null}
    </section>
  );
}

function GateScreen({ status, message }: { status: number; message: string }) {
  return (
    <div className="flex min-h-screen items-center justify-center p-6">
      <div className="max-w-md rounded-2xl border border-white/10 bg-[#10131a] p-6 text-center">
        <ShieldCheck className="mx-auto mb-3 h-8 w-8 text-rose-400" />
        <h1 className="text-lg font-bold text-slate-100">
          {status === 403 ? "Sem permissão" : "Sessão expirada"}
        </h1>
        <p className="mt-2 text-sm text-slate-400">{message}</p>
        <div className="mt-4 flex justify-center gap-2">
          {status === 401 ? (
            <a
              href="/pt/auth"
              className="rounded-lg bg-indigo-500 px-4 py-2 text-sm font-semibold text-white"
            >
              Fazer login
            </a>
          ) : null}
          <a
            href="/admin"
            className="rounded-lg border border-white/10 px-4 py-2 text-sm font-semibold text-slate-300"
          >
            Voltar ao Admin
          </a>
        </div>
      </div>
    </div>
  );
}

function NdaBanner({
  email,
  onAccept,
  busy,
}: {
  email: string;
  onAccept: () => void;
  busy: boolean;
}) {
  return (
    <div className="rounded-2xl border border-amber-500/20 bg-amber-500/5 px-4 py-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Lock className="h-4 w-4 text-amber-300" />
          <p className="text-[11px] text-slate-300">
            NDA necessário para o inventário do Comprador, CSV e PDF.{" "}
            <span className="text-slate-500">Aceite registado para {email}.</span>
          </p>
        </div>
        <button
          type="button"
          onClick={onAccept}
          disabled={busy}
          className="inline-flex items-center gap-2 rounded-lg bg-amber-400 px-4 py-1.5 text-[11px] font-bold text-[#1a1405] transition-colors hover:bg-amber-300 disabled:opacity-50"
        >
          {busy ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <CheckCircle2 className="h-3.5 w-3.5" />
          )}
          Aceitar NDA
        </button>
      </div>
    </div>
  );
}

export default function InvestorRoomPage() {
  const [tab, setTab] = useState<Tab>("overview");
  const [refreshing, setRefreshing] = useState(false);
  const [ndaBusy, setNdaBusy] = useState(false);
  const [exporting, setExporting] = useState(false);
  const { data, error, isLoading, mutate } = useSWR<InvestorRoom>(
    "investor-room",
    fetchInvestorRoom,
    { refreshInterval: 60_000, revalidateOnFocus: true }
  );

  const [simInputs, setSimInputs] = useState({
    contractors: 10,
    mailboxes: 2,
    cities: 4,
    reveals_per_contractor_month: 2,
    monthly_churn: 8,
    multiple: 3.5,
    opex_monthly: 0,
  });
  const [sim, setSim] = useState<InvestorSimulation | null>(null);
  const [simLoading, setSimLoading] = useState(false);

  useEffect(() => {
    if (!data) return;
    let alive = true;
    const timer = window.setTimeout(async () => {
      setSimLoading(true);
      try {
        const result = await simulateInvestor({
          ...simInputs,
          monthly_churn: simInputs.monthly_churn / 100,
        });
        if (alive) setSim(result);
      } catch {
        /* mantém o último resultado */
      } finally {
        if (alive) setSimLoading(false);
      }
    }, 250);
    return () => {
      alive = false;
      window.clearTimeout(timer);
    };
  }, [data, simInputs]);

  const acceptNda = async () => {
    setNdaBusy(true);
    try {
      await acceptInvestorNda();
      await mutate();
    } finally {
      setNdaBusy(false);
    }
  };

  const refresh = async () => {
    setRefreshing(true);
    try {
      await refreshInvestorRoom();
      await mutate();
    } finally {
      setRefreshing(false);
    }
  };

  const exportCsv = async () => {
    if (!data?.nda_accepted) return;
    setExporting(true);
    try {
      const blob = await downloadInvestorCsv();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `magicleads-investor_${data.generated_at.slice(0, 10)}.csv`;
      anchor.click();
      URL.revokeObjectURL(url);
    } finally {
      setExporting(false);
    }
  };

  if (
    error instanceof AdminApiError &&
    (error.status === 401 || error.status === 403)
  ) {
    return (
      <GateScreen
        status={error.status}
        message={
          error.status === 403
            ? "A tua conta não tem perfil de administrador."
            : "A tua sessão expirou. Volta a entrar."
        }
      />
    );
  }
  if (!data && isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center gap-3 text-slate-400">
        <Loader2 className="h-5 w-5 animate-spin" /> A carregar Investor Room…
      </div>
    );
  }
  if (!data) {
    return (
      <div className="flex min-h-screen items-center justify-center p-6">
        <div className="max-w-md rounded-2xl border border-white/10 bg-[#10131a] p-6 text-center">
          <AlertTriangle className="mx-auto mb-3 h-8 w-8 text-amber-400" />
          <h1 className="text-lg font-bold text-slate-100">
            Snapshot indisponível
          </h1>
          <p className="mt-2 text-sm text-slate-400">
            {error instanceof Error
              ? error.message
              : "Falha ao falar com a API."}
          </p>
          <button
            type="button"
            onClick={() => void mutate()}
            className="mt-4 rounded-lg bg-indigo-500 px-4 py-2 text-sm font-semibold text-white"
          >
            Tentar novamente
          </button>
        </div>
      </div>
    );
  }

  const price = data.price_bridge;
  const asset = data.asset;
  const going = data.going_concern;
  const proof = data.proof;
  const rec = data.reconciliation;
  const inventory = data.code_inventory;
  const leadsMetrics = (data.metrics?.leads ?? {}) as Record<string, number>;
  const leadsTotal = Number(leadsMetrics.total ?? 0);
  const confidence = confidenceBadge(proof.confidence);
  const emailSample = confidenceBadge(proof.email.status);

  return (
    <main className="mx-auto max-w-[1320px] px-4 py-6 text-slate-200">
      <style>{`
        @media print {
          .no-print { display: none !important; }
          .print-only { display: block !important; }
          body { background: #fff !important; color: #111 !important; }
          .print-watermark {
            display: block !important;
            position: fixed;
            inset: 0;
            z-index: 9999;
            pointer-events: none;
            opacity: .08;
            color: #b91c1c;
            font-size: 30px;
            font-weight: 800;
            transform: rotate(-28deg);
            place-items: center;
            white-space: pre-line;
            text-align: center;
          }
          @page { margin: 12mm; }
        }
        .print-only { display: none; }
      `}</style>
      <div className="print-only print-watermark">
        {`CONFIDENTIAL · ${data.viewer_email}\n${new Date()
          .toISOString()
          .slice(0, 10)} · ${data.checksum.slice(0, 12)}`}
      </div>

      <header className="mb-6 flex flex-wrap items-end justify-between gap-3">
        <div>
          <a
            href="/admin"
            className="no-print mb-1 inline-flex items-center gap-1 text-[11px] font-semibold text-slate-500 transition-colors hover:text-slate-300"
          >
            <ArrowLeft className="h-3.5 w-3.5" /> Torre de Controlo
          </a>
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="flex items-center gap-2 text-2xl font-black tracking-tight text-white">
              <BadgeDollarSign className="h-6 w-6 text-indigo-400" />
              Investor Room
            </h1>
            <Badge tone={data.nda_accepted ? "emerald" : "amber"}>
              {data.nda_accepted ? "NDA ativo" : "NDA pendente"}
            </Badge>
          </div>
          <p className="mt-1 text-[11px] text-slate-500">
            Executive pitch dashboard · dados agregados · atualizado{" "}
            {fmtWhen(data.generated_at)}
          </p>
        </div>

        <div className="no-print flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => void refresh()}
            disabled={refreshing}
            className="inline-flex items-center gap-2 rounded-lg border border-white/10 px-3 py-2 text-xs font-semibold text-slate-300 transition-colors hover:bg-white/5 disabled:opacity-50"
          >
            {refreshing ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <RefreshCcw className="h-3.5 w-3.5" />
            )}
            Refresh
          </button>
          <button
            type="button"
            onClick={() => void exportCsv()}
            disabled={!data.nda_accepted || exporting}
            className="inline-flex items-center gap-2 rounded-lg border border-emerald-400/30 bg-emerald-500/10 px-3 py-2 text-xs font-semibold text-emerald-200 transition-colors hover:bg-emerald-500/20 disabled:opacity-40"
          >
            {exporting ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Download className="h-3.5 w-3.5" />
            )}
            CSV
          </button>
          <button
            type="button"
            onClick={() => window.print()}
            disabled={!data.nda_accepted}
            className="inline-flex items-center gap-2 rounded-lg border border-white/10 px-3 py-2 text-xs font-semibold text-slate-300 transition-colors hover:bg-white/5 disabled:opacity-40"
          >
            <Printer className="h-3.5 w-3.5" /> PDF
          </button>
        </div>
      </header>

      {!data.nda_accepted ? (
        <div className="no-print mb-4">
          <NdaBanner
            email={data.viewer_email}
            onAccept={() => void acceptNda()}
            busy={ndaBusy}
          />
        </div>
      ) : null}

      <nav className="no-print mb-6 inline-flex flex-wrap gap-1 rounded-xl border border-white/10 bg-white/[0.02] p-1">
        {TABS.map((item) => (
          <button
            key={item.id}
            type="button"
            onClick={() => setTab(item.id)}
            className={cn(
              "rounded-lg px-4 py-1.5 text-[11px] font-semibold transition-colors",
              tab === item.id
                ? "bg-indigo-500 text-white shadow-sm shadow-indigo-500/30"
                : "text-slate-400 hover:text-slate-200"
            )}
          >
            {item.label}
          </button>
        ))}
      </nav>

      {tab === "overview" ? (
        <div className="space-y-5">
          {/* HERO — 3 big numbers */}
          <section className="grid gap-4 md:grid-cols-3">
            <BigStat
              label="Valuation Patrimonial"
              value={`${kFloor(asset.floor_low)} – ${kFloor(asset.floor_high)}`}
              sub="Piso de substituição · tecnologia + dados"
              chips={[
                `Dados ${kRound(asset.data_low)}–${kRound(asset.data_high)}`,
                `IP ${kRound(asset.ip_low)}–${kRound(asset.ip_high)}`,
              ]}
              icon={<Building2 className="h-4 w-4 text-indigo-300" />}
              accent={{
                card: "border-indigo-400/20 bg-gradient-to-br from-indigo-500/[0.16] via-[#10131a] to-[#0b0e14]",
                glow: "bg-indigo-500/25",
                icon: "bg-indigo-500/15",
              }}
            />
            <BigStat
              label="Ticket Base"
              value="$120"
              unit="/ semana"
              sub={`${money(price.mrr_per_pass)} / mês · ${money(price.arr_per_pass)} / ano`}
              chips={["Weekly pass", "Normalização 52/12"]}
              icon={<CircleDollarSign className="h-4 w-4 text-emerald-300" />}
              accent={{
                card: "border-emerald-400/20 bg-gradient-to-br from-emerald-500/[0.12] via-[#10131a] to-[#0b0e14]",
                glow: "bg-emerald-500/20",
                icon: "bg-emerald-500/15",
              }}
            />
            <BigStat
              label="Ativo de Dados"
              value={kNum(asset.owners)}
              unit="proprietários"
              sub={`${asset.fresh7.toLocaleString("en-US")} atualizados ≤7 dias`}
              chips={[
                `${leadsTotal.toLocaleString("en-US")} registos`,
                `${pct(proof.provenance_pct, 0)} proveniência`,
              ]}
              icon={<Database className="h-4 w-4 text-sky-300" />}
              accent={{
                card: "border-sky-400/20 bg-gradient-to-br from-sky-500/[0.12] via-[#10131a] to-[#0b0e14]",
                glow: "bg-sky-500/20",
                icon: "bg-sky-500/15",
              }}
            />
          </section>

          {/* AUDIT — discreto, fora do hero */}
          <AuditTrailCard rec={rec} />

          {/* PATRIMÓNIO */}
          <Card
            title="Composição do património"
            icon={<Layers className="h-4 w-4 text-indigo-400" />}
            hint="Piso de substituição: dados, engenharia e compliance"
            action={<Badge tone="indigo">Piso {kFloor(asset.floor_low)}+</Badge>}
          >
            <div className="grid gap-6 lg:grid-cols-2">
              <div className="space-y-4">
                {[
                  {
                    label: "Dados",
                    low: asset.data_low,
                    high: asset.data_high,
                    tone: "bg-indigo-400",
                    note: `${asset.owners.toLocaleString("en-US")} owners`,
                  },
                  {
                    label: "IP / Engenharia",
                    low: asset.ip_low,
                    high: asset.ip_high,
                    tone: "bg-violet-400",
                    note: "12–18 meses",
                  },
                  {
                    label: "Compliance",
                    low: asset.compliance_low,
                    high: asset.compliance_high,
                    tone: "bg-sky-400",
                    note: "Estrutura e processos",
                  },
                ].map((row) => (
                  <div key={row.label}>
                    <div className="flex items-baseline justify-between gap-2 text-[11px]">
                      <span className="font-semibold text-slate-300">
                        {row.label}
                      </span>
                      <span className="text-slate-400 tabular-nums">
                        {money(row.low)} – {money(row.high)}
                      </span>
                    </div>
                    <div className="mt-1.5">
                      <Bar
                        value={row.high}
                        max={asset.floor_high}
                        tone={row.tone}
                      />
                    </div>
                    <p className="mt-1 text-[10px] text-slate-600">{row.note}</p>
                  </div>
                ))}

                <div className="flex items-baseline justify-between rounded-xl border border-indigo-400/20 bg-indigo-500/5 px-3 py-2.5">
                  <span className="text-[11px] font-bold uppercase tracking-wide text-indigo-200">
                    Piso total
                  </span>
                  <span className="text-lg font-black text-white tabular-nums">
                    {money(asset.floor_low)} – {money(asset.floor_high)}
                  </span>
                </div>
              </div>

              <div className="rounded-xl border border-white/5 bg-white/[0.02] p-4">
                <div className="mb-3 flex items-center gap-2">
                  <TrendingUp className="h-4 w-4 text-indigo-400" />
                  <h3 className="text-[11px] font-bold uppercase tracking-wide text-slate-300">
                    Going concern
                  </h3>
                  <Badge tone="slate">Múltiplos 2×–8×</Badge>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-[11px]">
                    <thead className="text-slate-500">
                      <tr>
                        <th className="pb-1.5">Base</th>
                        <th className="pb-1.5 text-right">ARR</th>
                        <th className="pb-1.5 text-right">EV</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr className="border-t border-white/5">
                        <td className="py-2 text-slate-300">
                          Passes com acesso
                        </td>
                        <td className="py-2 text-right text-slate-300 tabular-nums">
                          {money(going.access_arr)}
                        </td>
                        <td className="py-2 text-right tabular-nums">
                          {money(going.access_ev.low)} –{" "}
                          {money(going.access_ev.high)}
                        </td>
                      </tr>
                      <tr className="border-t border-white/5">
                        <td className="py-2">
                          <div className="flex flex-wrap items-center gap-1.5">
                            <span className="text-slate-300">Base histórica</span>
                            <Badge tone="amber">Dados Históricos Base</Badge>
                          </div>
                        </td>
                        <td className="py-2 text-right text-slate-300 tabular-nums">
                          {money(going.pro_arr)}
                        </td>
                        <td className="py-2 text-right tabular-nums">
                          {money(going.pro_ev.low)} – {money(going.pro_ev.high)}
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </div>
                <p className="mt-3 text-[10px] text-slate-500">
                  O piso patrimonial ancora a negociação enquanto o ARR é baixo.
                </p>
              </div>
            </div>
          </Card>

          {/* SIMULADOR */}
          <Card
            title="Simulador ROI"
            icon={<Sparkles className="h-4 w-4 text-indigo-400" />}
            hint="Ajusta o cenário e vê o impacto em receita, margem e valuation"
            action={
              <Badge tone="emerald">
                {simLoading ? "A recalcular…" : "Recálculo em tempo real"}
              </Badge>
            }
          >
            <div className="grid gap-5 lg:grid-cols-2">
              <div className="space-y-3">
                {[
                  ["contractors", "Empreiteiros pagando $120/semana", 1, 1000, 1],
                  ["mailboxes", "Caixas de outreach", 1, 50, 1],
                  ["cities", "Cidades ativas", 1, 30, 1],
                  [
                    "reveals_per_contractor_month",
                    "Revelações / empreiteiro / mês",
                    0,
                    20,
                    1,
                  ],
                  ["monthly_churn", "Churn mensal (%)", 0.5, 50, 0.5],
                  ["multiple", "Múltiplo de valuation", 2, 8, 0.5],
                  ["opex_monthly", "Opex fixo mensal (USD)", 0, 100000, 500],
                ].map(([key, label, min, max, step]) => (
                  <label key={String(key)} className="block">
                    <div className="flex items-center justify-between text-[11px]">
                      <span className="text-slate-400">{label}</span>
                      <span className="font-mono text-slate-200 tabular-nums">
                        {String(simInputs[key as keyof typeof simInputs])}
                      </span>
                    </div>
                    <input
                      type="range"
                      min={Number(min)}
                      max={Number(max)}
                      step={Number(step)}
                      value={Number(simInputs[key as keyof typeof simInputs])}
                      onChange={(event) =>
                        setSimInputs((prev) => ({
                          ...prev,
                          [key]: Number(event.target.value),
                        }))
                      }
                      className="mt-1 w-full accent-indigo-400"
                    />
                  </label>
                ))}
              </div>

              <div className="rounded-xl border border-white/5 bg-white/[0.02] p-4">
                {simLoading ? (
                  <div className="flex items-center gap-2 text-xs text-slate-400">
                    <Loader2 className="h-4 w-4 animate-spin" /> A recalcular…
                  </div>
                ) : sim ? (
                  <div className="space-y-3">
                    <div className="grid grid-cols-3 gap-2">
                      <Kpi
                        label="MRR"
                        value={money(sim.mrr_normalized)}
                        tone="emerald"
                      />
                      <Kpi
                        label="ARR"
                        value={money(sim.arr_normalized)}
                        tone="emerald"
                      />
                      <Kpi
                        label="Valuation base"
                        value={money(sim.valuation.base)}
                        tone="indigo"
                      />
                    </div>
                    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                      <Kpi label="Semana" value={money(sim.weekly_revenue)} />
                      <Kpi
                        label="Margem bruta"
                        value={pct(sim.gross_margin_pct)}
                        tone="emerald"
                      />
                      <Kpi
                        label="Margem líquida"
                        value={pct(sim.net_margin_pct)}
                        tone={sim.net_margin_pct >= 0 ? "emerald" : "rose"}
                      />
                      <Kpi label="LTV" value={money(sim.ltv)} />
                    </div>
                    <div className="space-y-1 border-t border-white/5 pt-2 text-[10px] text-slate-500">
                      <p>
                        EV range:{" "}
                        <span className="text-slate-300">
                          {money(sim.ev_low)} – {money(sim.ev_high)}
                        </span>
                        {" · "}COGS {money2(sim.cogs_month)}/mês
                      </p>
                      <p>
                        Valuation 2× {money(sim.valuation.low)} · base{" "}
                        {money(sim.valuation.base)} · 8×{" "}
                        {money(sim.valuation.high)}
                      </p>
                    </div>
                  </div>
                ) : (
                  <p className="text-xs text-slate-500">Sem simulação.</p>
                )}
              </div>
            </div>
          </Card>

          {/* PROVA DE DADOS */}
          <Card
            title="Prova de Dados"
            icon={<Gauge className="h-4 w-4 text-indigo-400" />}
            hint="Qualidade, cobertura e operação da base"
            action={<Badge tone={confidence.tone}>{confidence.label}</Badge>}
          >
            <div className="grid gap-5 lg:grid-cols-[auto_1fr]">
              <div className="flex flex-col items-center justify-center gap-2 rounded-xl border border-white/5 bg-white/[0.02] px-6 py-4">
                <ScoreRing score={proof.truth_score} size={96} />
                <span className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">
                  Truth Score
                </span>
              </div>

              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                <Kpi
                  label="Owners"
                  value={pct(proof.owner_coverage_pct)}
                  sub={`${proof.fresh7.toLocaleString("en-US")} frescos`}
                  tone="emerald"
                />
                <Kpi
                  label="Morada"
                  value={pct(proof.address_coverage_pct)}
                  sub="Cobertura da base"
                />
                <Kpi
                  label="Telefone"
                  value={pct(proof.phone.success_pct)}
                  sub={`${proof.phone.error_billed} erros cobrados`}
                  tone="amber"
                />
                <Kpi
                  label="E-mail entregue"
                  value={pct(100 - proof.email.bounce_rate_pct)}
                  sub={`${proof.email.sent} enviados`}
                  tone="sky"
                />
                <Kpi
                  label="Frescura ≤7d"
                  value={pct(proof.fresh7_pct)}
                  tone="amber"
                />
                <Kpi
                  label="Proveniência"
                  value={pct(proof.provenance_pct)}
                  tone="emerald"
                />
                <Kpi
                  label="System Health"
                  value={`${proof.operations.health_score ?? "—"}/100`}
                  tone="emerald"
                />
                <Kpi
                  label="Respostas 30d"
                  value={String(proof.email.replies_30d)}
                  sub={`${proof.email.suppressions} supressões`}
                />
              </div>
            </div>

            <div className="mt-4 grid gap-3 md:grid-cols-3">
              <div className="rounded-xl border border-white/5 bg-white/[0.02] p-3">
                <div className="flex items-center justify-between gap-2">
                  <span className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wide text-slate-500">
                    <Activity className="h-3 w-3 text-amber-300" /> Telefonia
                  </span>
                  <Badge tone="amber">Em Remediação Técnica</Badge>
                </div>
                <div className="mt-2 grid grid-cols-2 gap-1.5 text-[11px] text-slate-400">
                  <span>
                    Chamadas{" "}
                    <strong className="text-slate-200 tabular-nums">
                      {proof.phone.calls}
                    </strong>
                  </span>
                  <span>
                    Custo 30d{" "}
                    <strong className="text-slate-200 tabular-nums">
                      {money2(proof.phone.cost_30d)}
                    </strong>
                  </span>
                  <span>
                    Erros{" "}
                    <strong className="text-amber-200 tabular-nums">
                      {proof.phone.error}
                    </strong>
                  </span>
                  <span>
                    Custo / success{" "}
                    <strong className="text-slate-200 tabular-nums">
                      {money2(proof.phone.cost_per_success)}
                    </strong>
                  </span>
                </div>
              </div>

              <div className="rounded-xl border border-white/5 bg-white/[0.02] p-3">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">
                    E-mail
                  </span>
                  <Badge tone={emailSample.tone}>{emailSample.label}</Badge>
                </div>
                <div className="mt-2 grid grid-cols-2 gap-1.5 text-[11px] text-slate-400">
                  <span>
                    Enviados{" "}
                    <strong className="text-slate-200 tabular-nums">
                      {proof.email.sent}
                    </strong>
                  </span>
                  <span>
                    Bounce{" "}
                    <strong className="text-slate-200 tabular-nums">
                      {pct(proof.email.bounce_rate_pct)}
                    </strong>
                  </span>
                  <span>
                    Respostas{" "}
                    <strong className="text-slate-200 tabular-nums">
                      {proof.email.replies_30d}
                    </strong>
                  </span>
                  <span>
                    Supressões{" "}
                    <strong className="text-slate-200 tabular-nums">
                      {proof.email.suppressions}
                    </strong>
                  </span>
                </div>
              </div>

              <div className="rounded-xl border border-white/5 bg-white/[0.02] p-3">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">
                    Operação
                  </span>
                  <Badge tone="emerald">
                    {proof.operations.health_status ?? "ok"}
                  </Badge>
                </div>
                <div className="mt-2 grid grid-cols-2 gap-1.5 text-[11px] text-slate-400">
                  <span>
                    Health{" "}
                    <strong className="text-emerald-200 tabular-nums">
                      {proof.operations.health_score ?? "—"}/100
                    </strong>
                  </span>
                  <span>
                    Ingestão{" "}
                    <strong className="text-slate-200">ativa</strong>
                  </span>
                  <span>
                    Snapshot{" "}
                    <strong className="text-slate-200">
                      {fmtWhen(proof.operations.captured_at)}
                    </strong>
                  </span>
                  <span>
                    Custo / owner{" "}
                    <strong className="text-slate-200 tabular-nums">
                      {money2(proof.cost_per_owner_cash)}
                    </strong>
                  </span>
                </div>
              </div>
            </div>

            <div className="mt-3 flex flex-wrap items-center gap-2 text-[10px] text-slate-500">
              <Badge tone="amber">Claims · Em Remediação Técnica</Badge>
              <span>{proof.anti_angi.note}</span>
            </div>
          </Card>
        </div>
      ) : null}

      {tab === "buyer" ? (
        <div className="space-y-5">
          {!data.nda_accepted ? (
            <Card
              title="Comprador — NDA necessário"
              icon={<Lock className="h-4 w-4 text-amber-400" />}
            >
              <p className="text-sm text-slate-400">
                Aceita o NDA para ver o inventário de ativos, a cobertura de
                testes e a portabilidade.
              </p>
            </Card>
          ) : (
            <>
              <Card
                title="Inventário de Ativos"
                icon={<FileText className="h-4 w-4 text-indigo-400" />}
                hint="Código, testes, infraestrutura e documentação"
                action={<Badge tone="emerald">CI/CD verde</Badge>}
              >
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-[11px]">
                    <thead className="text-slate-500">
                      <tr>
                        <th className="pb-2 font-semibold">Ativo</th>
                        <th className="pb-2 font-semibold">Métrica</th>
                        <th className="pb-2 text-right font-semibold">
                          Estado
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {[
                        {
                          icon: <FileText className="h-3.5 w-3.5 text-indigo-300" />,
                          asset: "Código backend",
                          metric: `${inventory.python_lines.toLocaleString(
                            "en-US"
                          )} linhas Python`,
                          status: "Entregue",
                          tone: "emerald" as BadgeTone,
                        },
                        {
                          icon: <FileText className="h-3.5 w-3.5 text-sky-300" />,
                          asset: "Código frontend",
                          metric: `${inventory.typescript_lines.toLocaleString(
                            "en-US"
                          )} linhas TS/TSX`,
                          status: "Entregue",
                          tone: "emerald" as BadgeTone,
                        },
                        {
                          icon: <FlaskConical className="h-3.5 w-3.5 text-emerald-300" />,
                          asset: "Testes backend",
                          metric: `${inventory.pytest_tests.toLocaleString(
                            "en-US"
                          )} pytest · ${inventory.test_files} ficheiros`,
                          status: "Verde",
                          tone: "emerald" as BadgeTone,
                        },
                        {
                          icon: <FlaskConical className="h-3.5 w-3.5 text-emerald-300" />,
                          asset: "Testes frontend",
                          metric: `${inventory.vitest_tests} vitest`,
                          status: "Verde",
                          tone: "emerald" as BadgeTone,
                        },
                        {
                          icon: <Gauge className="h-3.5 w-3.5 text-amber-300" />,
                          asset: "Cobertura backend",
                          metric:
                            inventory.coverage_backend_pct == null
                              ? "A medir"
                              : pct(inventory.coverage_backend_pct),
                          status: "Publicada",
                          tone: "sky" as BadgeTone,
                        },
                        {
                          icon: <GitBranch className="h-3.5 w-3.5 text-indigo-300" />,
                          asset: "CI/CD",
                          metric: inventory.ci,
                          status: "Verde",
                          tone: "emerald" as BadgeTone,
                        },
                        {
                          icon: <Container className="h-3.5 w-3.5 text-sky-300" />,
                          asset: "Infraestrutura",
                          metric: inventory.portability,
                          status: "Portável",
                          tone: "indigo" as BadgeTone,
                        },
                        {
                          icon: <BookOpen className="h-3.5 w-3.5 text-slate-300" />,
                          asset: "Documentação",
                          metric: `${inventory.docs} documentos + runbooks`,
                          status: "Incluída",
                          tone: "slate" as BadgeTone,
                        },
                        {
                          icon: <Database className="h-3.5 w-3.5 text-emerald-300" />,
                          asset: "Ativo de dados",
                          metric: `${leadsTotal.toLocaleString(
                            "en-US"
                          )} registos · ${asset.owners.toLocaleString(
                            "en-US"
                          )} owners`,
                          status: `${pct(proof.provenance_pct, 0)} proveniência`,
                          tone: "emerald" as BadgeTone,
                        },
                      ].map((row) => (
                        <tr
                          key={row.asset}
                          className="border-t border-white/5 align-top"
                        >
                          <td className="py-2.5">
                            <div className="flex items-center gap-2 font-semibold text-slate-200">
                              {row.icon}
                              {row.asset}
                            </div>
                          </td>
                          <td className="py-2.5 text-slate-400">
                            {row.metric}
                          </td>
                          <td className="py-2.5 text-right">
                            <Badge tone={row.tone}>{row.status}</Badge>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Card>

              <details className="rounded-xl border border-white/5 bg-white/[0.02] px-4 py-3">
                <summary className="cursor-pointer text-[11px] font-semibold text-slate-400">
                  Notas de due diligence
                </summary>
                <ul className="mt-2 space-y-1 text-[10px] text-slate-500">
                  {inventory.known_debt.map((item) => (
                    <li key={item}>• {item}</li>
                  ))}
                </ul>
              </details>

              <Card
                title="Transição 30 / 60 / 90"
                icon={<TrendingUp className="h-4 w-4 text-indigo-400" />}
                hint="Plano de integração para o comprador"
              >
                <div className="grid gap-3 md:grid-cols-3">
                  {[
                    {
                      step: "30 dias",
                      text: "Acesso, shadowing, credenciais, backups e runbooks.",
                    },
                    {
                      step: "60 dias",
                      text: "Deploy independente, migração de infraestrutura e validação de dados.",
                    },
                    {
                      step: "90 dias",
                      text: "Cutover, suporte, escrow e encerramento.",
                    },
                  ].map((item) => (
                    <div
                      key={item.step}
                      className="rounded-xl border border-white/5 bg-white/[0.02] p-3"
                    >
                      <p className="text-sm font-black text-indigo-200">
                        {item.step}
                      </p>
                      <p className="mt-1 text-[11px] text-slate-400">
                        {item.text}
                      </p>
                    </div>
                  ))}
                </div>
              </Card>
            </>
          )}
        </div>
      ) : null}

      {tab === "assumptions" ? (
        <Card
          title="Premissas versionadas — Gate 0"
          icon={<CheckCircle2 className="h-4 w-4 text-emerald-400" />}
          hint={`Aprovado por ${data.assumptions.approved_by}`}
        >
          <div className="overflow-x-auto">
            <table className="w-full text-left text-[11px]">
              <thead className="text-slate-500">
                <tr>
                  <th className="pb-2 font-semibold">Chave</th>
                  <th className="pb-2 font-semibold">Valor</th>
                  <th className="pb-2 font-semibold">Nota</th>
                </tr>
              </thead>
              <tbody>
                {[
                  ["ticket_price_weekly", "$120", "7 dias por empreiteiro"],
                  ["monthlyization_factor", "52/12 = 4,3333", "não usar 4 semanas"],
                  ["normalized_mrr_per_pass", "$520", "120 × 52/12"],
                  ["arr_per_pass", "$6.240", "520 × 12"],
                  ["multiple_low / base / high", "2× / 3,5× / 8×", "benchmark versionado"],
                  ["replacement_owner_low/high", "$0,50 / $1,50", "custo de substituição"],
                  ["ip_months_low/high", "12 / 18", "engenharia"],
                  ["ip_rate_low/high", "$8k / $15k", "rate mensal"],
                  [
                    "infra_fixed_monthly",
                    money2(data.assumptions.infra_fixed_monthly),
                    "custo fixo input",
                  ],
                ].map(([key, value, note]) => (
                  <tr key={key} className="border-t border-white/5">
                    <td className="py-2 font-mono text-[10px] text-slate-400">
                      {key}
                    </td>
                    <td className="py-2 text-slate-200">{value}</td>
                    <td className="py-2 text-slate-500">{note}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      ) : null}

      <footer className="mt-8 flex flex-wrap items-center gap-2 border-t border-white/5 pt-4 text-[10px] text-slate-600">
        <ShieldCheck className="h-3 w-3" />
        <span>Snapshot v{data.version}</span>
        <span>·</span>
        <span>checksum {data.checksum.slice(0, 12)}</span>
        <span>·</span>
        <span>{fmtWhen(data.generated_at)}</span>
        <span>·</span>
        <span>{data.nda_accepted ? "NDA ativo" : "NDA pendente"}</span>
        <span>·</span>
        <span>dados agregados · read-only</span>
      </footer>
    </main>
  );
}

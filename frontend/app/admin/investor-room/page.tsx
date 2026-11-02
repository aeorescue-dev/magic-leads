"use client";

import {
  Activity,
  AlertTriangle,
  ArrowLeft,
  BadgeDollarSign,
  BarChart3,
  CheckCircle2,
  Database,
  Download,
  FileText,
  Gauge,
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

type Tab = "overview" | "investor" | "proof" | "buyer" | "assumptions";

const TABS: Array<{ id: Tab; label: string }> = [
  { id: "overview", label: "Overview" },
  { id: "investor", label: "Investidor" },
  { id: "proof", label: "Proof of Truth" },
  { id: "buyer", label: "Comprador (1B)" },
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

function Card({
  title,
  icon,
  hint,
  children,
  className,
}: {
  title: string;
  icon: ReactNode;
  hint?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("rounded-2xl border border-white/10 bg-[#10131a] p-4", className)}>
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

function cn(...values: Array<string | false | null | undefined>) {
  return values.filter(Boolean).join(" ");
}

function ScoreRing({ score, size = 112 }: { score: number; size?: number }) {
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
        <span className={cn("text-2xl font-black", classes.text)}>{score.toFixed(0)}</span>
        <span className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">/ 100</span>
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
  tone?: "slate" | "emerald" | "amber" | "rose" | "indigo";
}) {
  const toneClass = {
    slate: "text-slate-100",
    emerald: "text-emerald-300",
    amber: "text-amber-300",
    rose: "text-rose-300",
    indigo: "text-indigo-300",
  }[tone];
  return (
    <div className="rounded-xl border border-white/5 bg-white/[0.02] p-3">
      <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">{label}</p>
      <p className={cn("mt-1 text-lg font-black", toneClass)}>{value}</p>
      {sub ? <p className="mt-0.5 text-[10px] text-slate-500">{sub}</p> : null}
    </div>
  );
}

function Bar({ value, max, tone = "bg-indigo-400" }: { value: number; max: number; tone?: string }) {
  return (
    <div className="h-2 overflow-hidden rounded-full bg-white/10">
      <div className={cn("h-full rounded-full", tone)} style={{ width: `${max > 0 ? Math.min(100, (value / max) * 100) : 0}%` }} />
    </div>
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
    <div className="rounded-2xl border border-amber-500/20 bg-amber-500/5 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="flex items-center gap-2 text-sm font-bold text-amber-200">
            <Lock className="h-4 w-4" /> NDA necessário para dados avançados
          </h2>
          <p className="mt-1 text-[11px] text-slate-400">
            Aceite em 1 clique para desbloquear a aba Comprador, o export CSV e a
            impressão. O aceite fica registado para <strong>{email}</strong>.
          </p>
        </div>
        <button
          type="button"
          onClick={onAccept}
          disabled={busy}
          className="inline-flex items-center gap-2 rounded-lg bg-amber-400 px-4 py-2 text-xs font-bold text-[#1a1405] hover:bg-amber-300 disabled:opacity-50"
        >
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <CheckCircle2 className="h-3.5 w-3.5" />}
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

  if (error instanceof AdminApiError && (error.status === 401 || error.status === 403)) {
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
          <h1 className="text-lg font-bold text-slate-100">Snapshot indisponível</h1>
          <p className="mt-2 text-sm text-slate-400">
            {error instanceof Error ? error.message : "Falha ao falar com a API."}
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

  return (
    <main className="mx-auto max-w-[1400px] px-4 py-6 text-slate-200">
      <style>{`
        @media print {
          .no-print { display: none !important; }
          .print-only { display: block !important; }
          body { background: #fff !important; color: #111 !important; }
          .print-surface { background: #fff !important; color: #111 !important; }
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
            display: grid;
            place-items: center;
            white-space: pre-line;
            text-align: center;
          }
        }
        .print-only { display: none; }
      `}</style>
      <div className="print-only print-watermark">
        {`CONFIDENTIAL · ${data.viewer_email}\n${new Date().toISOString().slice(0, 10)} · ${data.checksum.slice(0, 12)}`}
      </div>

      <header className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div>
          <a href="/admin" className="no-print mb-1 inline-flex items-center gap-1 text-xs font-semibold text-slate-400 hover:text-slate-200">
            <ArrowLeft className="h-3.5 w-3.5" /> Torre de Controlo
          </a>
          <h1 className="flex items-center gap-2 text-xl font-bold text-slate-100">
            <BadgeDollarSign className="h-5 w-5 text-indigo-400" /> Investor Room
          </h1>
          <p className="text-[11px] text-slate-500">
            v{data.version} · snapshot {fmtWhen(data.generated_at)} · checksum {data.checksum.slice(0, 10)} ·{" "}
            {data.nda_accepted ? "NDA aceite" : "NDA pendente"}
          </p>
        </div>
        <div className="no-print flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => void refresh()}
            disabled={refreshing}
            className="inline-flex items-center gap-2 rounded-lg border border-white/10 px-3 py-2 text-xs font-semibold text-slate-300 hover:bg-white/5 disabled:opacity-50"
          >
            {refreshing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCcw className="h-3.5 w-3.5" />}
            Refresh
          </button>
          <button
            type="button"
            onClick={() => void exportCsv()}
            disabled={!data.nda_accepted || exporting}
            className="inline-flex items-center gap-2 rounded-lg border border-emerald-400/30 bg-emerald-500/10 px-3 py-2 text-xs font-semibold text-emerald-200 hover:bg-emerald-500/20 disabled:opacity-40"
          >
            {exporting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Download className="h-3.5 w-3.5" />}
            CSV
          </button>
          <button
            type="button"
            onClick={() => window.print()}
            disabled={!data.nda_accepted}
            className="inline-flex items-center gap-2 rounded-lg border border-white/10 px-3 py-2 text-xs font-semibold text-slate-300 hover:bg-white/5 disabled:opacity-40"
          >
            <Printer className="h-3.5 w-3.5" /> PDF
          </button>
        </div>
      </header>

      {!data.nda_accepted ? (
        <div className="no-print mb-5">
          <NdaBanner email={data.viewer_email} onAccept={() => void acceptNda()} busy={ndaBusy} />
        </div>
      ) : null}

      <nav className="no-print mb-5 flex flex-wrap gap-1 rounded-xl border border-white/10 p-1">
        {TABS.map((item) => (
          <button
            key={item.id}
            type="button"
            onClick={() => setTab(item.id)}
            className={cn(
              "rounded-lg px-3 py-2 text-[11px] font-semibold",
              tab === item.id ? "bg-indigo-500 text-white" : "text-slate-400 hover:text-slate-200"
            )}
          >
            {item.label}
          </button>
        ))}
      </nav>

      {tab === "overview" ? (
        <div className="space-y-5">
          <Card
            title="Preço & run-rate — weekly pass"
            icon={<BadgeDollarSign className="h-4 w-4 text-indigo-400" />}
            hint="Ticket de tabela $120/7 dias; normalização 52/12 (não 4 semanas)"
          >
            <div className="grid gap-3 md:grid-cols-5">
              <Kpi label="Ticket semanal" value="$120" sub="por empreiteiro / 7 dias" tone="indigo" />
              <Kpi label="Equivalente mensal" value="$520" sub="120 × 52/12" />
              <Kpi label="Equivalente anual" value="$6.240" sub="520 × 12" />
              <Kpi label="Passes com acesso" value={String(price.access_passes)} sub={`${price.pro_active} pro active`} />
              <Kpi
                label="MRR normalizado"
                value={money(price.mrr_normalized_access)}
                sub={`${money(price.weekly_run_rate_access)}/semana`}
                tone="emerald"
              />
            </div>
            <div className="mt-3 grid gap-3 md:grid-cols-3">
              <Kpi label="ARR — passes com acesso" value={money(price.arr_normalized_access)} tone="emerald" />
              <Kpi label="ARR — pro active (não verificado)" value={money(price.arr_normalized_pro)} tone="amber" />
              <Kpi
                label="Cash Stripe 30d"
                value={rec.cash_30d == null ? "—" : money2(rec.cash_30d)}
                sub={`status: ${rec.cash_status}`}
                tone={rec.cash_30d == null ? "amber" : "emerald"}
              />
            </div>
            <div className="mt-3 rounded-lg border border-amber-500/20 bg-amber-500/10 p-3 text-[11px] text-amber-100">
              <strong>Reconciliação:</strong> {rec.details} · passes pagos verificados:{" "}
              <strong>{rec.verified_paid_passes}</strong> · checkouts completos: {rec.completed_checkouts} ·
              eventos Stripe completos: {rec.stripe_completed_events}. Estado:{" "}
              <strong>{rec.status}</strong>.
            </div>
          </Card>

          <div className="grid gap-5 xl:grid-cols-2">
            <Card
              title="Piso patrimonial"
              icon={<Database className="h-4 w-4 text-indigo-400" />}
              hint="Custo de substituição/reconstrução — não é valor de mercado"
            >
              <div className="grid grid-cols-3 gap-2">
                <Kpi label="Dados" value={`${money(asset.data_low)}–${money(asset.data_high)}`} sub={`${asset.owners.toLocaleString("en-US")} owners`} />
                <Kpi label="IP/Engenharia" value={`${money(asset.ip_low)}–${money(asset.ip_high)}`} sub="12–18 meses" />
                <Kpi label="Piso total" value={`${money(asset.floor_low)}–${money(asset.floor_high)}`} tone="indigo" />
              </div>
              <div className="mt-3 space-y-2">
                <div className="flex justify-between text-[11px] text-slate-400">
                  <span>Dados</span>
                  <span>{money(asset.data_low)} → {money(asset.data_high)}</span>
                </div>
                <Bar value={asset.data_high} max={asset.floor_high} />
                <div className="flex justify-between text-[11px] text-slate-400">
                  <span>IP/Engenharia</span>
                  <span>{money(asset.ip_low)} → {money(asset.ip_high)}</span>
                </div>
                <Bar value={asset.ip_high} max={asset.floor_high} tone="bg-amber-400" />
              </div>
              <p className="mt-3 text-[10px] text-slate-500">{asset.basis}</p>
            </Card>

            <Card
              title="Going concern vs. piso"
              icon={<TrendingUp className="h-4 w-4 text-indigo-400" />}
              hint="ARR = passes × $6.240; múltiplos 2×–8×"
            >
              <div className="overflow-x-auto">
                <table className="w-full text-left text-[11px]">
                  <thead className="text-slate-500">
                    <tr>
                      <th className="pb-1">Base</th>
                      <th className="pb-1 text-right">ARR</th>
                      <th className="pb-1 text-right">2×</th>
                      <th className="pb-1 text-right">Base</th>
                      <th className="pb-1 text-right">8×</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr className="border-t border-white/5">
                      <td className="py-1.5 text-slate-300">Passes com acesso</td>
                      <td className="py-1.5 text-right text-slate-300">{money(going.access_arr)}</td>
                      <td className="py-1.5 text-right">{money(going.access_ev.low)}</td>
                      <td className="py-1.5 text-right">{money(going.access_ev.base)}</td>
                      <td className="py-1.5 text-right">{money(going.access_ev.high)}</td>
                    </tr>
                    <tr className="border-t border-white/5">
                      <td className="py-1.5 text-slate-300">Pro active (não verificado)</td>
                      <td className="py-1.5 text-right text-slate-300">{money(going.pro_arr)}</td>
                      <td className="py-1.5 text-right">{money(going.pro_ev.low)}</td>
                      <td className="py-1.5 text-right">{money(going.pro_ev.base)}</td>
                      <td className="py-1.5 text-right">{money(going.pro_ev.high)}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <p className="mt-2 text-[10px] text-slate-500">
                O piso patrimonial domina enquanto o ARR for baixo; a partir de ~50 passes, o múltiplo de ARR passa a dominar.
              </p>
            </Card>
          </div>

          <Card
            title="Proof of Performance — resumo"
            icon={<Gauge className="h-4 w-4 text-indigo-400" />}
            hint={`Confiança: ${proof.confidence}`}
          >
            <div className="flex flex-wrap items-center gap-5">
              <ScoreRing score={proof.truth_score} />
              <div className="grid flex-1 gap-2 sm:grid-cols-3">
                <Kpi label="Owners" value={pct(proof.owner_coverage_pct)} sub={`${proof.fresh7} frescos ≤7d`} tone="emerald" />
                <Kpi label="Telefone success" value={pct(proof.phone.success_pct)} sub={`${proof.phone.error_billed} erros cobrados`} tone="rose" />
                <Kpi label="E-mail entregue" value={pct(100 - proof.email.bounce_rate_pct)} sub={`${proof.email.sent} enviados`} tone="amber" />
              </div>
            </div>
            <p className="mt-2 text-[10px] text-slate-500">
              Truth Score pondera proveniência, morada, owner, telefone, frescura e supressão. Telefone: {proof.phone.status}.
            </p>
          </Card>
        </div>
      ) : null}

      {tab === "investor" ? (
        <div className="space-y-5">
          <Card
            title="Unit economics do weekly pass"
            icon={<Activity className="h-4 w-4 text-indigo-400" />}
            hint="Receita, COGS e margem por pass"
          >
            <div className="grid gap-3 md:grid-cols-4">
              <Kpi label="Receita / pass / mês" value={money2(price.mrr_per_pass)} />
              <Kpi label="Receita / pass / ano" value={money(price.arr_per_pass)} />
              <Kpi label="COGS Searchbug / pass" value={money2(data.assumptions.searchbug_cost_per_success * data.assumptions.reveals_per_contractor_month)} />
              <Kpi label="Margem bruta alvo" value="90%+" tone="emerald" />
            </div>
            <p className="mt-2 text-[10px] text-slate-500">
              COGS variável inclui Searchbug, fees de pagamento e infraestrutura em degraus. Opex fixo entra na margem líquida do simulador.
            </p>
          </Card>

          <Card
            title="Simulador de crescimento"
            icon={<Sparkles className="h-4 w-4 text-indigo-400" />}
            hint="Altera empreiteiros, caixas, cidades, churn e múltiplo; recálculo imediato"
          >
            <div className="grid gap-4 lg:grid-cols-2">
              <div className="space-y-3">
                {[
                  ["contractors", "Empreiteiros pagando $120/semana", 1, 1000, 1],
                  ["mailboxes", "Caixas de outreach", 1, 50, 1],
                  ["cities", "Cidades ativas", 1, 30, 1],
                  ["reveals_per_contractor_month", "Revelações / empreiteiro / mês", 0, 20, 1],
                  ["monthly_churn", "Churn mensal (%)", 0.5, 50, 0.5],
                  ["multiple", "Múltiplo de valuation", 2, 8, 0.5],
                  ["opex_monthly", "Opex fixo mensal (USD)", 0, 100000, 500],
                ].map(([key, label, min, max, step]) => (
                  <label key={String(key)} className="block">
                    <div className="flex items-center justify-between text-[11px]">
                      <span className="text-slate-400">{label}</span>
                      <span className="font-mono text-slate-200">
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
                        setSimInputs((prev) => ({ ...prev, [key]: Number(event.target.value) }))
                      }
                      className="mt-1 w-full accent-indigo-400"
                    />
                  </label>
                ))}
              </div>
              <div className="rounded-xl border border-white/5 bg-white/[0.02] p-3">
                {simLoading ? (
                  <div className="flex items-center gap-2 text-xs text-slate-400">
                    <Loader2 className="h-4 w-4 animate-spin" /> A recalcular…
                  </div>
                ) : sim ? (
                  <div className="space-y-2">
                    <div className="grid grid-cols-2 gap-2">
                      <Kpi label="Semana" value={money(sim.weekly_revenue)} />
                      <Kpi label="MRR" value={money(sim.mrr_normalized)} tone="emerald" />
                      <Kpi label="ARR" value={money(sim.arr_normalized)} tone="emerald" />
                      <Kpi label="Margem bruta" value={pct(sim.gross_margin_pct)} tone="emerald" />
                      <Kpi label="Margem líquida" value={pct(sim.net_margin_pct)} tone={sim.net_margin_pct >= 0 ? "emerald" : "rose"} />
                      <Kpi label="LTV" value={money(sim.ltv)} />
                      <Kpi label="Valuation base" value={money(sim.valuation.base)} tone="indigo" />
                      <Kpi label="EV range" value={`${money(sim.ev_low)}–${money(sim.ev_high)}`} tone="indigo" />
                    </div>
                    <div className="mt-2 space-y-1 text-[10px] text-slate-500">
                      <p>COGS: Searchbug {money2(sim.searchbug_month)} · fees {money2(sim.payment_fees_month)} · infra {money2(sim.infra_month)}</p>
                      <p>Valuation: 2× {money(sim.valuation.low)} · base {money(sim.valuation.base)} · 8× {money(sim.valuation.high)}</p>
                      <p>Piso patrimonial: {money(sim.asset_floor_low)}–{money(sim.asset_floor_high)}</p>
                    </div>
                  </div>
                ) : (
                  <p className="text-xs text-slate-500">Sem simulação.</p>
                )}
              </div>
            </div>
          </Card>

          <Card
            title="Valor patrimonial vs. projeção"
            icon={<BarChart3 className="h-4 w-4 text-indigo-400" />}
            hint="O piso não desaparece com o ARR; é o argumento de negociação"
          >
            <div className="grid gap-3 md:grid-cols-3">
              <Kpi label="Piso patrimonial" value={`${money(asset.floor_low)}–${money(asset.floor_high)}`} tone="indigo" />
              <Kpi label="ARR — passes com acesso" value={money(going.access_arr)} />
              <Kpi label="EV — pro active 8×" value={money(going.pro_ev.high)} tone="amber" />
            </div>
            <p className="mt-2 text-[10px] text-slate-500">
              Oferta/negociação = faixa entre o piso e o going concern + prémio estratégico.
            </p>
          </Card>
        </div>
      ) : null}

      {tab === "proof" ? (
        <div className="space-y-5">
          <Card
            title="Phone Truth — em remediação"
            icon={<Activity className="h-4 w-4 text-rose-400" />}
            hint="Searchbug 30d — não escondemos os erros cobrados"
          >
            <div className="grid gap-3 md:grid-cols-5">
              <Kpi label="Chamadas" value={String(proof.phone.calls)} />
              <Kpi label="Success" value={pct(proof.phone.success_pct)} tone="emerald" />
              <Kpi label="Errors" value={String(proof.phone.error)} tone="rose" sub={`${proof.phone.error_billed} cobrados`} />
              <Kpi label="No results" value={String(proof.phone.no_results)} tone="amber" />
              <Kpi label="Custo / success" value={money2(proof.phone.cost_per_success)} />
            </div>
            <div className="mt-3 grid grid-cols-2 gap-2 text-[11px] text-slate-400 md:grid-cols-4">
              <span>name mismatch: {proof.phone.name_mismatch}</span>
              <span>transport: {proof.phone.transport_error}</span>
              <span>custo 30d: {money2(proof.phone.cost_30d)}</span>
              <span>erros cobrados: {pct(proof.phone.error_pct)}</span>
            </div>
            <p className="mt-2 text-[10px] text-amber-300">
              Selo “em remediação”: separar success/error, reconciliar cobrança e testar provider alternativo.
            </p>
          </Card>

          <div className="grid gap-5 xl:grid-cols-2">
            <Card title="Descoberta & frescura" icon={<Database className="h-4 w-4 text-indigo-400" />}>
              <div className="grid gap-3 md:grid-cols-2">
                <Kpi label="Owner coverage" value={pct(proof.owner_coverage_pct)} tone="emerald" />
                <Kpi label="Morada" value={pct(proof.address_coverage_pct)} />
                <Kpi label="Frescura ≤7d" value={pct(proof.fresh7_pct)} tone="amber" />
                <Kpi label="Proveniência" value={pct(proof.provenance_pct)} />
              </div>
              <p className="mt-2 text-[10px] text-slate-500">
                {proof.fresh7.toLocaleString("en-US")} factos frescos; proveniência = source_type + external_id.
              </p>
            </Card>

            <Card title="E-mail & operação" icon={<ShieldCheck className="h-4 w-4 text-indigo-400" />}>
              <div className="grid gap-3 md:grid-cols-2">
                <Kpi label="Enviados" value={String(proof.email.sent)} />
                <Kpi label="Bounce" value={pct(proof.email.bounce_rate_pct)} tone="amber" />
                <Kpi label="Respostas 30d" value={String(proof.email.replies_30d)} />
                <Kpi label="System Health" value={`${proof.operations.health_score ?? "—"}/100`} tone="emerald" />
              </div>
              <p className="mt-2 text-[10px] text-slate-500">
                Amostra de e-mail: {proof.email.status}. Supressões: {proof.email.suppressions}.
              </p>
            </Card>
          </div>

          <Card
            title="Custo por owner & anti-Angi"
            icon={<Gauge className="h-4 w-4 text-indigo-400" />}
            hint="Claims de concorrentes exigem URL, data e revisão legal"
          >
            <div className="grid gap-3 md:grid-cols-3">
              <Kpi label="Cash / owner" value={money2(proof.cost_per_owner_cash)} />
              <Kpi label="Fully loaded / owner" value={money2(proof.cost_per_owner_loaded)} />
              <Kpi label="Claims" value="pendente" tone="amber" sub={proof.anti_angi.status} />
            </div>
            <p className="mt-2 text-[10px] text-slate-500">
              {proof.anti_angi.note}
            </p>
          </Card>
        </div>
      ) : null}

      {tab === "buyer" ? (
        <div className="space-y-5">
          {!data.nda_accepted ? (
            <Card title="Comprador — NDA necessário" icon={<Lock className="h-4 w-4 text-amber-400" />}>
              <p className="text-sm text-slate-400">
                Aceita o NDA para ver a auditoria de código, dívida técnica e portabilidade.
              </p>
            </Card>
          ) : (
            <>
              <Card title="Inventário técnico" icon={<FileText className="h-4 w-4 text-indigo-400" />} hint="Fase 1B completa o data room e o PDF server-side">
                <div className="grid gap-3 md:grid-cols-4">
                  <Kpi label="Python LOC" value={data.code_inventory.python_lines.toLocaleString("en-US")} />
                  <Kpi label="TS/TSX LOC" value={data.code_inventory.typescript_lines.toLocaleString("en-US")} />
                  <Kpi label="Pytest" value={String(data.code_inventory.pytest_tests)} />
                  <Kpi label="Vitest" value={String(data.code_inventory.vitest_tests)} />
                  <Kpi label="Ficheiros teste" value={String(data.code_inventory.test_files)} />
                  <Kpi label="Docs" value={String(data.code_inventory.docs)} />
                  <Kpi label="Cobertura backend" value={data.code_inventory.coverage_backend_pct == null ? "a medir" : pct(data.code_inventory.coverage_backend_pct)} tone="amber" />
                  <Kpi label="CI" value="verde" tone="emerald" sub={data.code_inventory.ci} />
                </div>
                <p className="mt-3 text-[11px] text-slate-400">{data.code_inventory.portability}</p>
              </Card>
              <Card title="Dívida técnica registada" icon={<AlertTriangle className="h-4 w-4 text-amber-400" />}>
                <ul className="space-y-1 text-[11px] text-slate-400">
                  {data.code_inventory.known_debt.map((item) => (
                    <li key={item}>• {item}</li>
                  ))}
                </ul>
              </Card>
              <Card title="Transição 30/60/90" icon={<TrendingUp className="h-4 w-4 text-indigo-400" />}>
                <div className="grid gap-3 md:grid-cols-3 text-[11px] text-slate-400">
                  <div><strong className="text-slate-200">30 dias</strong><br />Acesso, shadowing, credenciais, backups, runbooks.</div>
                  <div><strong className="text-slate-200">60 dias</strong><br />Deploy independente, migração de infraestrutura, validação de dados.</div>
                  <div><strong className="text-slate-200">90 dias</strong><br />Cutover, suporte, escrow e encerramento.</div>
                </div>
              </Card>
            </>
          )}
        </div>
      ) : null}

      {tab === "assumptions" ? (
        <div className="space-y-5">
          <Card
            title="Premissas versionadas — Gate 0"
            icon={<CheckCircle2 className="h-4 w-4 text-emerald-400" />}
            hint={`Aprovado por ${data.assumptions.approved_by} em ${data.assumptions.approved_at}`}
          >
            <div className="overflow-x-auto">
              <table className="w-full text-left text-[11px]">
                <thead className="text-slate-500">
                  <tr><th className="pb-1">Chave</th><th className="pb-1">Valor</th><th className="pb-1">Nota</th></tr>
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
                    ["infra_fixed_monthly", money2(data.assumptions.infra_fixed_monthly), "custo fixo input"],
                  ].map(([key, value, note]) => (
                    <tr key={key} className="border-t border-white/5">
                      <td className="py-1.5 font-mono text-[10px] text-slate-400">{key}</td>
                      <td className="py-1.5 text-slate-200">{value}</td>
                      <td className="py-1.5 text-slate-500">{note}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="mt-3 text-[10px] text-slate-500">
              Snapshot v{data.version} · checksum {data.checksum.slice(0, 16)}. Alterações de preço exigem nova versão e aprovação.
            </p>
          </Card>
        </div>
      ) : null}

      <footer className="mt-6 flex flex-wrap items-center gap-3 text-[10px] text-slate-600">
        <ShieldCheck className="h-3 w-3" />
        <span>Read-only · dados agregados · NDA para export/Buyer · watermark dinâmica.</span>
        <span>·</span>
        <span>52 semanas/ano; weekly pass, não subscrição mensal.</span>
      </footer>
    </main>
  );
}

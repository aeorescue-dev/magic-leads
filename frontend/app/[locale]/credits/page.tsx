"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useAuth } from "@/lib/auth";
import { useI18n } from "@/lib/i18n";
import { loginUser, registerUser } from "@/lib/api-client";
import {
  CreditLead,
  CreditPack,
  CreditsApiError,
  LedgerEntry,
  RevealPayload,
  Wallet,
  createCreditCheckout,
  getLedger,
  getLeads,
  getPacks,
  getWallet,
  mockPay,
  mockWebhook,
  revealSignal,
} from "@/lib/credits-api";

const COPY = {
  pt: {
    title: "Créditos Magic Leads",
    subtitle: "Staging — dados sintéticos. Nenhum pagamento real.",
    free: "Conta grátis",
    login: "Entrar",
    register: "Criar conta grátis",
    email: "Email",
    password: "Password",
    company: "Empresa",
    wallet: "Carteira",
    credits: "créditos",
    buy: "Comprar",
    packs: "Pacotes de créditos",
    leads: "Sinais ativos",
    reveal: "Revelar sinal — $1,50",
    phoneSoon: "Telefone $3 — Marco 1B",
    mailing: "Mailing pronto",
    noMailing: "Sem mailing",
    exclusive: "Exclusivo",
    exclusiveMine: "Seu exclusivo",
    exclusiveOther: "Exclusivo de outro empreiteiro",
    ledger: "Ledger de créditos",
    empty: "Sem leads sintéticos. Corre o seed de staging.",
    mockPay: "Simular pagamento",
    mockHint: "Staging: o Checkout real será usado quando a chave sk_test estiver configurada.",
    webhook: "Simular webhook duplicado",
    close: "Fechar",
    logout: "Sair",
    success: "Créditos adicionados",
    duplicate: "Evento duplicado — saldo não mudou",
    notEnough: "Saldo insuficiente. Compra um pacote.",
    blocked: "Este lead está exclusivo para outro empreiteiro neste ofício.",
    trade: "Ofício para o reveal",
    all: "Todos",
    address: "Endereço da obra",
    owner: "Proprietário oficial",
    mailingAddress: "Mailing address",
    until: "Exclusivo até",
    noPhone: "Sem telefone — sinal para carta/visita",
  },
  en: {
    title: "Magic Leads Credits",
    subtitle: "Staging — synthetic data. No real payments.",
    free: "Free account",
    login: "Sign in",
    register: "Create free account",
    email: "Email",
    password: "Password",
    company: "Company",
    wallet: "Wallet",
    credits: "credits",
    buy: "Buy",
    packs: "Credit packs",
    leads: "Active signals",
    reveal: "Reveal signal — $1.50",
    phoneSoon: "Phone $3 — Milestone 1B",
    mailing: "Mailing ready",
    noMailing: "No mailing",
    exclusive: "Exclusive",
    exclusiveMine: "Your exclusive",
    exclusiveOther: "Exclusive to another contractor",
    ledger: "Credit ledger",
    empty: "No synthetic leads. Run the staging seed.",
    mockPay: "Simulate payment",
    mockHint: "Staging: the real Checkout will be used once the sk_test key is configured.",
    webhook: "Simulate duplicate webhook",
    close: "Close",
    logout: "Sign out",
    success: "Credits added",
    duplicate: "Duplicate event — balance unchanged",
    notEnough: "Insufficient balance. Buy a pack.",
    blocked: "This lead is exclusive to another contractor in this trade.",
    trade: "Trade for reveal",
    all: "All",
    address: "Job address",
    owner: "Registered owner",
    mailingAddress: "Mailing address",
    until: "Exclusive until",
    noPhone: "No phone — signal for letter/visit",
  },
  es: {
    title: "Créditos Magic Leads",
    subtitle: "Staging — datos sintéticos. Sin pagos reales.",
    free: "Cuenta gratis",
    login: "Entrar",
    register: "Crear cuenta gratis",
    email: "Email",
    password: "Password",
    company: "Empresa",
    wallet: "Cartera",
    credits: "créditos",
    buy: "Comprar",
    packs: "Paquetes de créditos",
    leads: "Señales activas",
    reveal: "Revelar señal — $1,50",
    phoneSoon: "Teléfono $3 — Hito 1B",
    mailing: "Mailing listo",
    noMailing: "Sin mailing",
    exclusive: "Exclusivo",
    exclusiveMine: "Tu exclusivo",
    exclusiveOther: "Exclusivo de otro contratista",
    ledger: "Ledger de créditos",
    empty: "Sin leads sintéticos. Ejecuta el seed de staging.",
    mockPay: "Simular pago",
    mockHint: "Staging: el Checkout real se usará cuando la clave sk_test esté configurada.",
    webhook: "Simular webhook duplicado",
    close: "Cerrar",
    logout: "Salir",
    success: "Créditos añadidos",
    duplicate: "Evento duplicado — saldo sin cambios",
    notEnough: "Saldo insuficiente. Compra un paquete.",
    blocked: "Este lead es exclusivo de otro contratista en este oficio.",
    trade: "Oficio para el reveal",
    all: "Todos",
    address: "Dirección de la obra",
    owner: "Propietario registrado",
    mailingAddress: "Mailing address",
    until: "Exclusivo hasta",
    noPhone: "Sin teléfono — señal para carta/visita",
  },
} as const;

const TRADES = [
  "Plumbing", "Electrical", "Heating", "Paint", "Roof", "Structure",
  "Door_Window", "Unsanitary", "Mold", "Debris", "Rodent", "Elevator",
  "Gas", "Lead", "Grass", "Permit_Rejected",
];

function money(cents: number) {
  return `$${(Math.max(0, cents) / 100).toFixed(2)}`;
}

function idempotencyKey() {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return `idem-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export default function CreditsPage() {
  const { user, loading, signOut } = useAuth();
  const { lang } = useI18n();
  const c = COPY[(lang as keyof typeof COPY) || "pt"] || COPY.pt;
  const [wallet, setWallet] = useState<Wallet | null>(null);
  const [packs, setPacks] = useState<CreditPack[]>([]);
  const [leads, setLeads] = useState<CreditLead[]>([]);
  const [ledger, setLedger] = useState<LedgerEntry[]>([]);
  const [trade, setTrade] = useState("");
  const [reveal, setReveal] = useState<RevealPayload | null>(null);
  const [mockPurchase, setMockPurchase] = useState<{ purchase_id: number; pack: CreditPack } | null>(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [authMode, setAuthMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("qa-buyer+staging@magicleads.app");
  const [password, setPassword] = useState("dev-demo-only");
  const [company, setCompany] = useState("QA Contractor");
  const [authError, setAuthError] = useState("");

  const loadAll = useCallback(async () => {
    if (!user) return;
    try {
      const [w, p, l, lg] = await Promise.all([
        getWallet(),
        getPacks(),
        getLeads({ limit: 60 }),
        getLedger(30),
      ]);
      setWallet(w);
      setPacks(p.packs);
      setLeads(l.leads);
      setLedger(lg.entries);
    } catch (err) {
      if (err instanceof CreditsApiError && err.status === 401) {
        setAuthError(c.login);
      } else {
        setMessage(err instanceof Error ? err.message : "Erro ao carregar créditos");
      }
    }
  }, [user, c.login]);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    if (params.get("checkout") === "success") setMessage("Checkout concluído — a carteira atualiza após o webhook.");
  }, []);

  const onAuth = async (e: React.FormEvent) => {
    e.preventDefault();
    setAuthError("");
    setBusy(true);
    try {
      if (authMode === "register") {
        await registerUser({ email: email.trim(), password, company_name: company.trim() || "QA Contractor", locale: lang });
      } else {
        await loginUser({ email: email.trim(), password });
      }
      window.location.reload();
    } catch (err) {
      setAuthError(err instanceof Error ? err.message : "Erro de autenticação");
    } finally {
      setBusy(false);
    }
  };

  const buy = async (pack: CreditPack) => {
    setBusy(true);
    setMessage("");
    try {
      const res = await createCreditCheckout(pack.code, lang);
      if (res.mock) {
        setMockPurchase({ purchase_id: res.purchase_id, pack });
        setMessage(c.mockHint);
      } else if (res.checkout_url) {
        window.location.href = res.checkout_url;
      }
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Erro no checkout");
    } finally {
      setBusy(false);
    }
  };

  const payMock = async () => {
    if (!mockPurchase) return;
    setBusy(true);
    try {
      const res = await mockPay(mockPurchase.purchase_id);
      setMessage(res.duplicate ? c.duplicate : c.success);
      await loadAll();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Erro no pagamento simulado");
    } finally {
      setBusy(false);
    }
  };

  const webhookTwice = async () => {
    if (!mockPurchase) return;
    setBusy(true);
    try {
      const eventId = `evt_ui_${mockPurchase.purchase_id}`;
      const first = await mockWebhook(mockPurchase.purchase_id, eventId);
      const second = await mockWebhook(mockPurchase.purchase_id, eventId);
      setMessage(
        `Webhook 1: ${first.duplicate ? "duplicado" : "aplicado"} · Webhook 2: ${second.duplicate ? "duplicado" : "aplicado"}`,
      );
      await loadAll();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Erro no webhook");
    } finally {
      setBusy(false);
    }
  };

  const doReveal = async (lead: CreditLead) => {
    setBusy(true);
    setMessage("");
    try {
      const tradeCode = trade || lead.trade_code;
      const res = await revealSignal(lead.id, tradeCode, idempotencyKey());
      setReveal(res.payload);
      await loadAll();
      setMessage(res.duplicate ? c.duplicate : c.success);
    } catch (err) {
      if (err instanceof CreditsApiError) {
        if (err.status === 402) setMessage(c.notEnough);
        else if (err.status === 409) setMessage(c.blocked);
        else setMessage(err.message);
      } else {
        setMessage(err instanceof Error ? err.message : "Erro no reveal");
      }
    } finally {
      setBusy(false);
    }
  };

  const balance = wallet?.balance_cents ?? 0;
  const packCards = useMemo(() => packs, [packs]);

  if (loading) {
    return <main className="flex min-h-screen items-center justify-center bg-[#f6f8fb] text-[#0b1220]">Loading…</main>;
  }

  if (!user) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-[#f6f8fb] p-4">
        <div className="w-full max-w-md rounded-3xl border border-[#dbe4ef] bg-white p-6 shadow-xl sm:p-8">
          <div className="text-[10px] font-black uppercase tracking-[0.18em] text-[#0a8f65]">Staging</div>
          <h1 className="mt-2 text-2xl font-black text-[#0b1220]">{c.title}</h1>
          <p className="mt-1 text-sm text-[#54617a]">{c.subtitle}</p>
          <div className="mt-4 flex rounded-xl bg-[#f1f5f9] p-1">
            <button type="button" onClick={() => setAuthMode("login")} className={`flex-1 rounded-lg px-3 py-2 text-sm font-bold ${authMode === "login" ? "bg-[#0b1220] text-white" : "text-[#54617a]"}`}>{c.login}</button>
            <button type="button" onClick={() => setAuthMode("register")} className={`flex-1 rounded-lg px-3 py-2 text-sm font-bold ${authMode === "register" ? "bg-[#0b1220] text-white" : "text-[#54617a]"}`}>{c.register}</button>
          </div>
          <form onSubmit={onAuth} className="mt-4 space-y-3">
            <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder={c.email} className="w-full rounded-xl border border-[#dbe4ef] px-4 py-3 text-sm outline-none focus:border-[#0a8f65]" />
            <input type="password" required value={password} onChange={(e) => setPassword(e.target.value)} placeholder={c.password} className="w-full rounded-xl border border-[#dbe4ef] px-4 py-3 text-sm outline-none focus:border-[#0a8f65]" />
            {authMode === "register" && (
              <input value={company} onChange={(e) => setCompany(e.target.value)} placeholder={c.company} className="w-full rounded-xl border border-[#dbe4ef] px-4 py-3 text-sm outline-none focus:border-[#0a8f65]" />
            )}
            {authError && <p className="text-xs font-semibold text-rose-600">{authError}</p>}
            <button disabled={busy} className="w-full rounded-xl bg-[#10b981] px-4 py-3 text-sm font-black text-[#06251c] disabled:opacity-50">
              {authMode === "register" ? c.register : c.login}
            </button>
          </form>
          <p className="mt-4 text-[11px] leading-relaxed text-[#94a3b8]">
            Staging accounts: <b>qa-buyer+staging@magicleads.app</b> / <b>dev-demo-only</b> · seed sintético.
          </p>
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-[#f6f8fb] text-[#0b1220]">
      <header className="border-b border-[#dbe4ef] bg-[#0b1220] px-4 py-4 text-white">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4">
          <div>
            <div className="text-[10px] font-black uppercase tracking-[0.2em] text-[#34e0a1]">Staging · Marco 1A</div>
            <h1 className="text-xl font-black">{c.title}</h1>
            <p className="text-xs text-slate-300">{c.subtitle}</p>
          </div>
          <div className="text-right">
            <div className="text-xs text-slate-300">{user.email}</div>
            <button type="button" onClick={() => signOut()} className="mt-1 text-xs font-bold text-[#34e0a1] underline">{c.logout}</button>
          </div>
        </div>
      </header>

      <div className="mx-auto max-w-6xl space-y-6 p-4 sm:p-6">
        {message && (
          <div className="rounded-2xl border border-[#d9f3e8] bg-[#f0fdf7] px-4 py-3 text-sm font-semibold text-[#0a8f65]">
            {message}
          </div>
        )}

        <section className="grid gap-4 md:grid-cols-[1.1fr_1.9fr]">
          <div className="rounded-3xl border border-[#dbe4ef] bg-white p-5 shadow-sm">
            <div className="text-[10px] font-black uppercase tracking-[0.16em] text-[#94a3b8]">{c.wallet}</div>
            <div className="mt-1 text-3xl font-black">{money(balance)}</div>
            <div className="text-sm font-semibold text-[#54617a]">{balance} {c.credits}</div>
            <div className="mt-3 h-2 overflow-hidden rounded-full bg-[#eef2f7]">
              <div className="h-full rounded-full bg-[#10b981]" style={{ width: `${Math.min(100, (balance / 1900) * 100)}%` }} />
            </div>
            <p className="mt-3 text-[11px] leading-relaxed text-[#94a3b8]">
              $1,50 = 150 créditos · $3,00 = 300 créditos · exclusividade 7 dias por ofício.
            </p>
          </div>

          <div className="rounded-3xl border border-[#dbe4ef] bg-white p-5 shadow-sm">
            <div className="flex items-center justify-between">
              <div className="text-[10px] font-black uppercase tracking-[0.16em] text-[#94a3b8]">{c.packs}</div>
              <div className="text-[11px] text-[#94a3b8]">Stripe test / mock</div>
            </div>
            <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {packCards.map((pack) => (
                <button key={pack.code} disabled={busy} onClick={() => buy(pack)} className="rounded-2xl border border-[#dbe4ef] p-3 text-left transition hover:border-[#10b981] disabled:opacity-50">
                  <div className="flex items-baseline justify-between">
                    <span className="text-sm font-black">{pack.label}</span>
                    <span className="text-sm font-black text-[#0a8f65]">{money(pack.price_cents)}</span>
                  </div>
                  <div className="text-[11px] text-[#54617a]">{pack.credits_cents} {c.credits}</div>
                  {pack.bonus_cents > 0 && <div className="text-[10px] font-bold text-[#b45309]">+{pack.bonus_cents} bónus</div>}
                  <div className="mt-2 text-[10px] font-black uppercase tracking-[0.12em] text-[#0a8f65]">{c.buy}</div>
                </button>
              ))}
            </div>
            {mockPurchase && (
              <div className="mt-3 rounded-2xl border border-[#fde68a] bg-[#fffbeb] p-3">
                <div className="text-xs font-bold text-[#92400e]">Mock: {mockPurchase.pack.label} · {money(mockPurchase.pack.price_cents)}</div>
                <div className="mt-2 flex flex-wrap gap-2">
                  <button disabled={busy} onClick={payMock} className="rounded-xl bg-[#0b1220] px-3 py-2 text-xs font-black text-white">{c.mockPay}</button>
                  <button disabled={busy} onClick={webhookTwice} className="rounded-xl border border-[#92400e] px-3 py-2 text-xs font-black text-[#92400e]">{c.webhook}</button>
                </div>
              </div>
            )}
          </div>
        </section>

        <section className="rounded-3xl border border-[#dbe4ef] bg-white p-5 shadow-sm">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <div className="text-[10px] font-black uppercase tracking-[0.16em] text-[#94a3b8]">{c.leads}</div>
              <div className="text-sm font-semibold text-[#54617a]">Dados mascarados até ao reveal. Sem Searchbug na 1A.</div>
            </div>
            <label className="text-xs font-bold text-[#54617a]">
              {c.trade}
              <select value={trade} onChange={(e) => setTrade(e.target.value)} className="ml-2 rounded-lg border border-[#dbe4ef] bg-white px-2 py-1 text-xs">
                <option value="">{c.all}</option>
                {TRADES.map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
            </label>
          </div>
          <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {leads.length === 0 && <p className="text-sm text-[#54617a]">{c.empty}</p>}
            {leads.map((lead) => (
              <article key={lead.id} className="rounded-2xl border border-[#e2e8f0] p-4">
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <div className="text-[10px] font-black uppercase tracking-[0.12em] text-[#0a8f65]">{lead.city} · {lead.trade_code}</div>
                    <h3 className="mt-1 text-sm font-black">{lead.title}</h3>
                  </div>
                  <span className={`rounded-full px-2 py-0.5 text-[9px] font-black ${lead.exclusive ? "bg-[#fef3c7] text-[#b45309]" : "bg-[#e8f9ef] text-[#0a8f65]"}`}>
                    {lead.exclusive ? (lead.exclusive_mine ? c.exclusiveMine : c.exclusive) : "LIVE"}
                  </span>
                </div>
                <p className="mt-2 text-xs font-semibold text-[#54617a]">{lead.address_masked}</p>
                <p className="text-xs text-[#94a3b8]">{lead.owner_masked} · {lead.zone}</p>
                <div className="mt-2 flex flex-wrap gap-1 text-[10px]">
                  <span className={`rounded px-1.5 py-0.5 font-bold ${lead.mailing_ready ? "bg-[#e8f9ef] text-[#0a8f65]" : "bg-[#f1f5f9] text-[#64748b]"}`}>{lead.mailing_ready ? c.mailing : c.noMailing}</span>
                  <span className="rounded bg-[#f1f5f9] px-1.5 py-0.5 font-bold text-[#64748b]">{c.noPhone}</span>
                </div>
                <button
                  disabled={busy || (lead.exclusive && !lead.exclusive_mine)}
                  onClick={() => doReveal(lead)}
                  className="mt-3 w-full rounded-xl bg-[#10b981] px-3 py-2 text-xs font-black text-[#06251c] disabled:cursor-not-allowed disabled:opacity-40"
                >
                  {c.reveal}
                </button>
                <button disabled className="mt-2 w-full rounded-xl border border-[#dbe4ef] px-3 py-2 text-[10px] font-bold text-[#94a3b8]">
                  {c.phoneSoon}
                </button>
              </article>
            ))}
          </div>
        </section>

        <section className="rounded-3xl border border-[#dbe4ef] bg-white p-5 shadow-sm">
          <div className="text-[10px] font-black uppercase tracking-[0.16em] text-[#94a3b8]">{c.ledger}</div>
          <div className="mt-3 overflow-x-auto">
            <table className="w-full min-w-[540px] text-left text-xs">
              <thead className="text-[10px] uppercase tracking-[0.12em] text-[#94a3b8]">
                <tr><th className="py-2">Data</th><th>Tipo</th><th>Créditos</th><th>Saldo</th></tr>
              </thead>
              <tbody>
                {ledger.map((entry) => (
                  <tr key={entry.id} className="border-t border-[#eef2f7]">
                    <td className="py-2 text-[#54617a]">{new Date(entry.created_at).toLocaleString()}</td>
                    <td className="font-semibold">{entry.event_type}</td>
                    <td className={entry.amount < 0 ? "font-black text-rose-600" : "font-black text-[#0a8f65]"}>{entry.amount > 0 ? "+" : ""}{entry.amount}</td>
                    <td className="font-semibold">{entry.balance_after ?? "—"}</td>
                  </tr>
                ))}
                {ledger.length === 0 && <tr><td colSpan={4} className="py-4 text-[#94a3b8]">Sem movimentos.</td></tr>}
              </tbody>
            </table>
          </div>
        </section>
      </div>

      {reveal && (
        <div className="fixed inset-0 z-[1000] flex items-center justify-center bg-[#0b1220]/60 p-4 backdrop-blur-md" onClick={() => setReveal(null)}>
          <div className="w-full max-w-lg rounded-3xl bg-white p-6 shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between">
              <div className="text-[10px] font-black uppercase tracking-[0.16em] text-[#0a8f65]">Sinal desbloqueado</div>
              <button onClick={() => setReveal(null)} className="text-[#94a3b8]">✕</button>
            </div>
            <h2 className="mt-2 text-xl font-black">{reveal.owner_name}</h2>
            <div className="mt-3 space-y-2 text-sm">
              <p><span className="font-black">{c.address}:</span> {reveal.address}, {reveal.city} {reveal.zip_code || ""}</p>
              <p><span className="font-black">{c.owner}:</span> {reveal.owner_name}</p>
              <p><span className="font-black">{c.mailingAddress}:</span> {reveal.mailing_address}</p>
              <p><span className="font-black">{c.until}:</span> {new Date(reveal.exclusive_until).toLocaleDateString()}</p>
              <p className="rounded-xl bg-[#f0fdf7] p-3 text-xs font-semibold text-[#0a8f65]">{c.noPhone}</p>
            </div>
            <button onClick={() => setReveal(null)} className="mt-4 w-full rounded-xl bg-[#0b1220] px-4 py-3 text-sm font-black text-white">{c.close}</button>
          </div>
        </div>
      )}
    </main>
  );
}

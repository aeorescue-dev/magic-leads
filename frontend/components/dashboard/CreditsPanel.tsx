"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
  mockPay,
  mockWebhook,
  revealSignal,
} from "@/lib/credits-api";

const COPY = {
  pt: {
    freemium: "Modo gratuito: vê os sinais. Desbloqueia endereço, proprietário e mailing com créditos.",
    wallet: "Carteira",
    credits: "créditos",
    packs: "Créditos / Planos",
    packHint: "Compra única. Os créditos entram na hora após o pagamento.",
    buy: "Comprar",
    mockPay: "Simular pagamento",
    mockHint: "Staging: Checkout mock ativo. Com chave sk_test passa a Stripe real.",
    webhook: "Simular webhook duplicado",
    signals: "Sinais ativos",
    signalsSub: "Dados mascarados até ao reveal. Sem Searchbug na 1A.",
    city: "Praça",
    all: "Todas",
    trade: "Ofício do reveal",
    reveal: "Revelar sinal — $1,50",
    phoneSoon: "Telefone $3 — Marco 1B",
    mailing: "Mailing pronto",
    noMailing: "Sem mailing",
    exclusive: "Exclusivo",
    mine: "Seu exclusivo",
    noPhone: "Sem telefone — sinal para carta/visita",
    ledger: "Movimentos",
    empty: "Sem sinais sintéticos. Corre o seed de staging.",
    success: "Créditos adicionados",
    duplicate: "Evento duplicado — saldo não mudou",
    notEnough: "Saldo insuficiente. Escolhe um pacote acima.",
    paywallTitle: "Créditos insuficientes",
    paywallHeadline: "Desbloqueia este lead",
    paywallSub: "Este sinal custa $1,50. Escolhe um pacote — os créditos entram na carteira e o lead desbloqueia aqui mesmo.",
    paywallNeed: "Necessário",
    blocked: "Exclusivo para outro empreiteiro neste ofício.",
    address: "Endereço da obra",
    owner: "Proprietário oficial",
    mailingAddress: "Mailing address",
    until: "Exclusivo até",
    close: "Fechar",
  },
  en: {
    freemium: "Free mode: see the signals. Unlock address, owner and mailing with credits.",
    wallet: "Wallet",
    credits: "credits",
    packs: "Credits / Plans",
    packHint: "One-time purchase. Credits land immediately after payment.",
    buy: "Buy",
    mockPay: "Simulate payment",
    mockHint: "Staging: mock Checkout active. With sk_test it becomes real Stripe.",
    webhook: "Simulate duplicate webhook",
    signals: "Active signals",
    signalsSub: "Masked until reveal. No Searchbug in Milestone 1A.",
    city: "Market",
    all: "All",
    trade: "Trade for reveal",
    reveal: "Reveal signal — $1.50",
    phoneSoon: "Phone $3 — Milestone 1B",
    mailing: "Mailing ready",
    noMailing: "No mailing",
    exclusive: "Exclusive",
    mine: "Your exclusive",
    noPhone: "No phone — signal for letter/visit",
    ledger: "Activity",
    empty: "No synthetic signals. Run the staging seed.",
    success: "Credits added",
    duplicate: "Duplicate event — balance unchanged",
    notEnough: "Insufficient balance. Choose a pack above.",
    paywallTitle: "Not enough credits",
    paywallHeadline: "Unlock this lead",
    paywallSub: "This signal costs $1.50. Choose a pack — credits land in your wallet and the lead unlocks right here.",
    paywallNeed: "Required",
    blocked: "Exclusive to another contractor in this trade.",
    address: "Job address",
    owner: "Registered owner",
    mailingAddress: "Mailing address",
    until: "Exclusive until",
    close: "Close",
  },
  es: {
    freemium: "Modo gratuito: ves las señales. Desbloquea dirección, propietario y mailing con créditos.",
    wallet: "Cartera",
    credits: "créditos",
    packs: "Créditos / Planes",
    packHint: "Compra única. Los créditos entran al instante tras el pago.",
    buy: "Comprar",
    mockPay: "Simular pago",
    mockHint: "Staging: Checkout mock activo. Con sk_test pasa a Stripe real.",
    webhook: "Simular webhook duplicado",
    signals: "Señales activas",
    signalsSub: "Datos enmascarados hasta el reveal. Sin Searchbug en el Hito 1A.",
    city: "Plaza",
    all: "Todas",
    trade: "Oficio para el reveal",
    reveal: "Revelar señal — $1,50",
    phoneSoon: "Teléfono $3 — Hito 1B",
    mailing: "Mailing listo",
    noMailing: "Sin mailing",
    exclusive: "Exclusivo",
    mine: "Tu exclusivo",
    noPhone: "Sin teléfono — señal para carta/visita",
    ledger: "Movimientos",
    empty: "Sin señales sintéticas. Ejecuta el seed de staging.",
    success: "Créditos añadidos",
    duplicate: "Evento duplicado — saldo sin cambios",
    notEnough: "Saldo insuficiente. Elige un paquete arriba.",
    paywallTitle: "Créditos insuficientes",
    paywallHeadline: "Desbloquea este lead",
    paywallSub: "Esta señal cuesta $1,50. Elige un paquete — los créditos entran en la cartera y el lead se desbloquea aquí mismo.",
    paywallNeed: "Necesario",
    blocked: "Exclusivo de otro contratista en este oficio.",
    address: "Dirección de la obra",
    owner: "Propietario registrado",
    mailingAddress: "Mailing address",
    until: "Exclusivo hasta",
    close: "Cerrar",
  },
} as const;

const TRADES = [
  "Plumbing", "Electrical", "Heating", "Paint", "Roof", "Structure",
  "Door_Window", "Unsanitary", "Mold", "Debris", "Rodent", "Elevator",
  "Gas", "Lead", "Grass", "Permit_Rejected",
];
const CITIES = ["NYC", "Chicago", "Boston", "Dallas"];

function money(cents: number) {
  return `$${(Math.max(0, cents) / 100).toFixed(2)}`;
}

function key() {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return `idem-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export default function CreditsPanel({
  lang,
  wallet,
  onWallet,
}: {
  lang: string;
  wallet: Wallet | null;
  onWallet: (wallet: Wallet) => void;
}) {
  const c = COPY[(lang as keyof typeof COPY) || "pt"] || COPY.pt;
  const [packs, setPacks] = useState<CreditPack[]>([]);
  const [leads, setLeads] = useState<CreditLead[]>([]);
  const [ledger, setLedger] = useState<LedgerEntry[]>([]);
  const [city, setCity] = useState("");
  const [trade, setTrade] = useState("");
  const [showAll, setShowAll] = useState(false);
  const [mockPurchase, setMockPurchase] = useState<{ id: number; pack: CreditPack } | null>(null);
  const [paywallLead, setPaywallLead] = useState<CreditLead | null>(null);
  const [reveal, setReveal] = useState<RevealPayload | null>(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const packsRef = useRef<HTMLDivElement | null>(null);

  const load = useCallback(async () => {
    try {
      const [p, l, lg] = await Promise.all([
        getPacks(),
        getLeads({ limit: 60 }),
        getLedger(20),
      ]);
      setPacks(p.packs);
      setLeads(l.leads);
      setLedger(lg.entries);
    } catch (err) {
      if (err instanceof CreditsApiError && err.status === 401) return;
      setMessage(err instanceof Error ? err.message : "Erro ao carregar sinais");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const visibleLeads = useMemo(() => {
    const filtered = leads.filter((lead) => (!city || lead.city === city));
    return showAll ? filtered : filtered.slice(0, 9);
  }, [leads, city, showAll]);

  const buy = async (pack: CreditPack) => {
    setBusy(true);
    setMessage("");
    try {
      const res = await createCreditCheckout(pack.code, lang);
      if (res.mock) {
        setMockPurchase({ id: res.purchase_id, pack });
        setMessage(c.mockHint);
      } else if (res.checkout_url) {
        window.location.href = res.checkout_url;
      }
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Checkout error");
    } finally {
      setBusy(false);
    }
  };

  const payMock = async () => {
    if (!mockPurchase) return;
    const pendingLead = paywallLead;
    setBusy(true);
    try {
      const res = await mockPay(mockPurchase.id);
      if (res.wallet) onWallet(res.wallet);
      setMessage(res.duplicate ? c.duplicate : c.success);
      await load();
      setMockPurchase(null);
      setPaywallLead(null);
      // O crédito entrou: desbloqueia o lead que estava à espera na modal.
      if (pendingLead) await doReveal(pendingLead);
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Mock pay error");
    } finally {
      setBusy(false);
    }
  };

  const webhookTwice = async () => {
    if (!mockPurchase) return;
    setBusy(true);
    try {
      const eventId = `evt_panel_${mockPurchase.id}`;
      const first = await mockWebhook(mockPurchase.id, eventId);
      const second = await mockWebhook(mockPurchase.id, eventId);
      if (first.wallet) onWallet(first.wallet);
      setMessage(
        `Webhook 1: ${first.duplicate ? "duplicado" : "aplicado"} · Webhook 2: ${second.duplicate ? "duplicado" : "aplicado"}`,
      );
      await load();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Webhook error");
    } finally {
      setBusy(false);
    }
  };

  async function doReveal(lead: CreditLead) {
    setBusy(true);
    setMessage("");
    try {
      const res = await revealSignal(lead.id, trade || lead.trade_code, key());
      setReveal(res.payload);
      onWallet(res.wallet);
      await load();
      setMessage(res.duplicate ? c.duplicate : c.success);
    } catch (err) {
      if (err instanceof CreditsApiError) {
        if (err.status === 402) {
          setMessage(c.notEnough);
          setPaywallLead(lead);
        } else if (err.status === 409) {
          setMessage(c.blocked);
        } else {
          setMessage(err.message);
        }
      } else {
        setMessage(err instanceof Error ? err.message : "Reveal error");
      }
    } finally {
      setBusy(false);
    }
  }

  const balance = wallet?.balance_cents ?? 0;

  return (
    <section data-testid="credits-panel" className="space-y-4">
      <div ref={packsRef} className="rounded-2xl border border-[var(--sd-border)] bg-[var(--sd-surface)] p-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <div className="text-[10px] font-black uppercase tracking-[0.16em] text-[var(--sd-faint)]">{c.packs}</div>
            <div className="mt-1 text-sm font-bold">{c.wallet}: {money(balance)} · {balance} {c.credits}</div>
            <div className="text-[11px] text-[var(--sd-muted)]">{c.packHint}</div>
          </div>
          <div className="text-right text-[11px] text-[var(--sd-faint)]">$1,50 = 150 · $3,00 = 300</div>
        </div>
        <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
          {packs.map((pack) => (
            <button
              key={pack.code}
              disabled={busy}
              onClick={() => buy(pack)}
              className="rounded-xl border border-[var(--sd-border)] bg-[var(--sd-surface-2)] p-3 text-left transition hover:border-[var(--sd-accent)] disabled:opacity-50"
            >
              <div className="flex items-baseline justify-between gap-1">
                <span className="text-xs font-black">{pack.label}</span>
                <span className="text-xs font-black text-[var(--sd-accent)]">{money(pack.price_cents)}</span>
              </div>
              <div className="text-[10px] text-[var(--sd-muted)]">{pack.credits_cents} {c.credits}</div>
              {pack.bonus_cents > 0 && <div className="text-[9px] font-bold text-amber-500">+{pack.bonus_cents} bónus</div>}
              <div className="mt-1 text-[9px] font-black uppercase tracking-[0.12em] text-[var(--sd-accent)]">{c.buy}</div>
            </button>
          ))}
        </div>
        {mockPurchase && (
          <div className="mt-3 rounded-xl border border-amber-500/30 bg-amber-500/10 p-3">
            <div className="text-[11px] font-bold text-amber-500">Mock: {mockPurchase.pack.label} · {money(mockPurchase.pack.price_cents)}</div>
            <div className="mt-2 flex flex-wrap gap-2">
              <button disabled={busy} onClick={payMock} className="rounded-lg bg-[var(--sd-text)] px-3 py-1.5 text-[10px] font-black text-[var(--sd-surface)]">{c.mockPay}</button>
              <button disabled={busy} onClick={webhookTwice} className="rounded-lg border border-amber-500/40 px-3 py-1.5 text-[10px] font-black text-amber-500">{c.webhook}</button>
            </div>
          </div>
        )}
      </div>

      {message && (
        <div className="rounded-xl border border-[var(--sd-accent)]/30 bg-[var(--sd-accent-soft)] px-4 py-2 text-xs font-semibold text-[var(--sd-accent)]">
          {message}
        </div>
      )}

      <div className="rounded-2xl border border-[var(--sd-border)] bg-[var(--sd-surface)] p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="text-[10px] font-black uppercase tracking-[0.16em] text-[var(--sd-faint)]">{c.signals}</div>
            <div className="text-[11px] text-[var(--sd-muted)]">{c.signalsSub}</div>
          </div>
          <div className="flex flex-wrap gap-2">
            <select value={city} onChange={(e) => setCity(e.target.value)} className="rounded-lg border border-[var(--sd-border)] bg-[var(--sd-surface)] px-2 py-1 text-[11px]">
              <option value="">{c.all} ({c.city})</option>
              {CITIES.map((x) => <option key={x} value={x}>{x}</option>)}
            </select>
            <select value={trade} onChange={(e) => setTrade(e.target.value)} className="rounded-lg border border-[var(--sd-border)] bg-[var(--sd-surface)] px-2 py-1 text-[11px]">
              <option value="">{c.trade}: {c.all}</option>
              {TRADES.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>
        </div>

        <div className="mt-3 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {visibleLeads.length === 0 && <p className="text-sm text-[var(--sd-muted)]">{c.empty}</p>}
          {visibleLeads.map((lead) => (
            <article key={lead.id} className="rounded-xl border border-[var(--sd-border)] bg-[var(--sd-surface-2)] p-3">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <div className="text-[9px] font-black uppercase tracking-[0.12em] text-[var(--sd-accent)]">{lead.city} · {lead.trade_code}</div>
                  <h3 className="mt-1 text-xs font-black">{lead.title}</h3>
                </div>
                <span className={`rounded-full px-2 py-0.5 text-[8px] font-black ${lead.exclusive ? "bg-amber-500/20 text-amber-500" : "bg-[var(--sd-accent-soft)] text-[var(--sd-accent)]"}`}>
                  {lead.exclusive ? (lead.exclusive_mine ? c.mine : c.exclusive) : "LIVE"}
                </span>
              </div>
              <p className="mt-2 text-[11px] font-semibold text-[var(--sd-text)]">{lead.address_masked}</p>
              <p className="text-[10px] text-[var(--sd-muted)]">{lead.owner_masked} · {lead.zone}</p>
              <div className="mt-2 flex flex-wrap gap-1 text-[9px]">
                <span className={`rounded px-1.5 py-0.5 font-bold ${lead.mailing_ready ? "bg-[var(--sd-accent-soft)] text-[var(--sd-accent)]" : "bg-[var(--sd-surface)] text-[var(--sd-muted)]"}`}>{lead.mailing_ready ? c.mailing : c.noMailing}</span>
                <span className="rounded bg-[var(--sd-surface)] px-1.5 py-0.5 font-bold text-[var(--sd-muted)]">{c.noPhone}</span>
              </div>
              <button
                disabled={busy || (lead.exclusive && !lead.exclusive_mine)}
                onClick={() => doReveal(lead)}
                className="mt-3 w-full rounded-lg bg-[var(--sd-accent)] px-3 py-2 text-[10px] font-black text-[var(--sd-accent-text)] disabled:cursor-not-allowed disabled:opacity-40"
              >
                {c.reveal}
              </button>
              <button disabled className="mt-1.5 w-full rounded-lg border border-[var(--sd-border)] px-3 py-1.5 text-[9px] font-bold text-[var(--sd-faint)]">{c.phoneSoon}</button>
            </article>
          ))}
        </div>
        {leads.length > 9 && !showAll && (
          <button onClick={() => setShowAll(true)} className="mt-3 text-[11px] font-bold text-[var(--sd-accent)] underline">Ver todos os {leads.length} sinais</button>
        )}
      </div>

      <div className="rounded-2xl border border-[var(--sd-border)] bg-[var(--sd-surface)] p-4">
        <div className="text-[10px] font-black uppercase tracking-[0.16em] text-[var(--sd-faint)]">{c.ledger}</div>
        <div className="mt-2 overflow-x-auto">
          <table className="w-full min-w-[420px] text-left text-[11px]">
            <thead className="text-[9px] uppercase tracking-[0.1em] text-[var(--sd-faint)]">
              <tr><th className="py-1">Data</th><th>Tipo</th><th>Créditos</th><th>Saldo</th></tr>
            </thead>
            <tbody>
              {ledger.map((e) => (
                <tr key={e.id} className="border-t border-[var(--sd-border)]">
                  <td className="py-1 text-[var(--sd-muted)]">{new Date(e.created_at).toLocaleDateString()}</td>
                  <td className="font-semibold">{e.event_type}</td>
                  <td className={e.amount < 0 ? "font-black text-rose-500" : "font-black text-[var(--sd-accent)]"}>{e.amount > 0 ? "+" : ""}{e.amount}</td>
                  <td className="font-semibold">{e.balance_after ?? "—"}</td>
                </tr>
              ))}
              {ledger.length === 0 && <tr><td colSpan={4} className="py-3 text-[var(--sd-muted)]">Sem movimentos.</td></tr>}
            </tbody>
          </table>
        </div>
      </div>

      {paywallLead && (
        <div
          data-testid="credit-paywall"
          className="fixed inset-0 z-[1100] flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm"
          onClick={() => setPaywallLead(null)}
        >
          <div
            className="max-h-[90vh] w-full max-w-3xl overflow-y-auto rounded-2xl border border-[var(--sd-border)] bg-[var(--sd-surface)] p-5 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="text-[10px] font-black uppercase tracking-[0.16em] text-[var(--sd-accent)]">
                  {c.paywallTitle}
                </div>
                <h2 className="mt-1 text-xl font-black">{c.paywallHeadline}</h2>
                <p className="mt-1 max-w-xl text-xs leading-relaxed text-[var(--sd-muted)]">{c.paywallSub}</p>
              </div>
              <button
                type="button"
                aria-label={c.close}
                onClick={() => setPaywallLead(null)}
                className="rounded-lg px-2 py-1 text-lg text-[var(--sd-faint)] hover:bg-[var(--sd-surface-2)]"
              >
                ✕
              </button>
            </div>

            <div className="mt-3 flex flex-wrap items-center gap-3 rounded-xl border border-[var(--sd-border)] bg-[var(--sd-surface-2)] px-3 py-2 text-xs">
              <span className="text-[var(--sd-muted)]">
                {c.wallet}: <b className="text-[var(--sd-text)]">{money(balance)}</b>
              </span>
              <span className="text-[var(--sd-muted)]">
                {c.paywallNeed}: <b className="text-[var(--sd-accent)]">{money(paywallLead.signal_price_cents)}</b>
              </span>
              <span className="ml-auto text-[10px] font-bold uppercase tracking-[0.12em] text-[var(--sd-faint)]">
                $1,50 = 150 · $3,00 = 300
              </span>
            </div>

            <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {packs.map((pack) => (
                <button
                  key={pack.code}
                  type="button"
                  disabled={busy}
                  onClick={() => buy(pack)}
                  className="rounded-xl border border-[var(--sd-border)] bg-[var(--sd-surface-2)] p-3 text-left transition hover:border-[var(--sd-accent)] disabled:opacity-50"
                >
                  <div className="flex items-baseline justify-between gap-1">
                    <span className="text-xs font-black">{pack.label}</span>
                    <span className="text-xs font-black text-[var(--sd-accent)]">{money(pack.price_cents)}</span>
                  </div>
                  <div className="text-[10px] text-[var(--sd-muted)]">{pack.credits_cents} {c.credits}</div>
                  {pack.bonus_cents > 0 && (
                    <div className="text-[9px] font-bold text-amber-500">+{pack.bonus_cents} bónus</div>
                  )}
                  <div className="mt-1 text-[9px] font-black uppercase tracking-[0.12em] text-[var(--sd-accent)]">
                    {c.buy}
                  </div>
                </button>
              ))}
            </div>

            {mockPurchase && (
              <div className="mt-3 rounded-xl border border-amber-500/30 bg-amber-500/10 p-3">
                <div className="text-[11px] font-bold text-amber-500">
                  Mock: {mockPurchase.pack.label} · {money(mockPurchase.pack.price_cents)}
                </div>
                <div className="mt-2 flex flex-wrap gap-2">
                  <button
                    type="button"
                    disabled={busy}
                    onClick={payMock}
                    className="rounded-lg bg-[var(--sd-text)] px-3 py-1.5 text-[10px] font-black text-[var(--sd-surface)] disabled:opacity-50"
                  >
                    {c.mockPay}
                  </button>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={webhookTwice}
                    className="rounded-lg border border-amber-500/40 px-3 py-1.5 text-[10px] font-black text-amber-500 disabled:opacity-50"
                  >
                    {c.webhook}
                  </button>
                </div>
              </div>
            )}

            <div className="mt-4 flex justify-end">
              <button
                type="button"
                onClick={() => setPaywallLead(null)}
                className="rounded-lg border border-[var(--sd-border)] px-4 py-2 text-xs font-bold text-[var(--sd-muted)] hover:bg-[var(--sd-surface-2)]"
              >
                {c.close}
              </button>
            </div>
          </div>
        </div>
      )}

      {reveal && (
        <div className="fixed inset-0 z-[1000] flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm" onClick={() => setReveal(null)}>
          <div className="w-full max-w-lg rounded-2xl border border-[var(--sd-border)] bg-[var(--sd-surface)] p-5 shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between">
              <div className="text-[10px] font-black uppercase tracking-[0.16em] text-[var(--sd-accent)]">Sinal desbloqueado</div>
              <button onClick={() => setReveal(null)} className="text-[var(--sd-faint)]">✕</button>
            </div>
            <h2 className="mt-2 text-lg font-black">{reveal.owner_name}</h2>
            <div className="mt-3 space-y-1.5 text-sm">
              <p><b>{c.address}:</b> {reveal.address}, {reveal.city} {reveal.zip_code || ""}</p>
              <p><b>{c.owner}:</b> {reveal.owner_name}</p>
              <p><b>{c.mailingAddress}:</b> {reveal.mailing_address}</p>
              <p><b>{c.until}:</b> {new Date(reveal.exclusive_until).toLocaleDateString()}</p>
              <p className="rounded-lg bg-[var(--sd-accent-soft)] p-2 text-xs font-semibold text-[var(--sd-accent)]">{c.noPhone}</p>
            </div>
            <button onClick={() => setReveal(null)} className="mt-4 w-full rounded-lg bg-[var(--sd-text)] px-4 py-2.5 text-sm font-black text-[var(--sd-surface)]">{c.close}</button>
          </div>
        </div>
      )}
    </section>
  );
}

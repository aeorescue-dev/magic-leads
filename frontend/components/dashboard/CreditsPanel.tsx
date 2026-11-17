"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  CreditLead,
  CreditPack,
  CreditsApiError,
  PhoneRevealPayload,
  RevealPayload,
  Wallet,
  createCreditCheckout,
  getLeads,
  getPacks,
  mockPay,
  mockWebhook,
  revealPhone,
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
    signalsSub: "Dados mascarados até ao reveal. Telefone sob consulta.",
    city: "Praça",
    all: "Todas",
    trade: "Ofício",
    reveal: "Revelar sinal — $1,50",
    phoneCta: "Buscar telefone — $3,00",
    phoneUnavailable: "Consulta de telefone indisponível neste momento.",
    phoneNotFound: "Não encontrámos um telefone para este lead.",
    phoneAttemptLimit: "Limite de consultas atingido. Tenta novamente mais tarde.",
    phoneNotEligible: "Este lead não tem telefone elegível.",
    phoneUnlockedTitle: "Telefone desbloqueado",
    phoneLabel: "Telefone",
    paywallPhoneHeadline: "Consulta de telefone",
    paywallPhoneSub: "A consulta custa $3,00. Escolhe um pacote — os créditos entram na carteira e o telefone é consultado na hora.",
    paywallPhoneNeed: "Consulta",
    mailing: "Mailing pronto",
    noMailing: "Sem mailing",
    exclusive: "Exclusivo",
    mine: "Seu exclusivo",
    noPhone: "Telefone sob consulta",
    ledger: "Movimentos",
    empty: "Sem sinais sintéticos. Corre o seed de staging.",
    readyAll: "Todos",
    readyLetter: "Carta / Visita",
    readyPhone: "Com telefone",
    readyLetterBadge: "Pronto para carta",
    readyPhoneBadge: "Telefone verificado",
    readyPhoneEligible: "Telefone sob consulta",
    readyLetterHint: "Endereço exato + owner + mailing.",
    readyPhoneHint: "Consulta na hora — $3,00.",
    coverage: "Cobertura atual: {letter} prontos para carta · {phone} com telefone sob consulta.",
    readyLetterEmpty: "Ainda não há sinais prontos para carta nesta praça.",
    readyLetterEmptyCta: "Ver todos os sinais",
    readyPhoneEmpty: "Sem telefones elegíveis nesta praça. Ajusta a cidade ou o ofício.",
    readyPhoneEmptyCta: "Ver todos os sinais",
    notReady: "Ainda não pronto",
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
    signalsSub: "Masked until reveal. Phone on demand.",
    city: "Market",
    all: "All",
    trade: "Trade",
    reveal: "Reveal signal — $1.50",
    phoneCta: "Find phone — $3.00",
    phoneUnavailable: "Phone lookup is unavailable right now.",
    phoneNotFound: "We couldn't find a phone for this lead.",
    phoneAttemptLimit: "Lookup limit reached. Try again later.",
    phoneNotEligible: "This lead has no phone lookup available.",
    phoneUnlockedTitle: "Phone unlocked",
    phoneLabel: "Phone",
    paywallPhoneHeadline: "Phone lookup",
    paywallPhoneSub: "The lookup costs $3.00. Choose a pack — credits land in your wallet and the phone is looked up on demand.",
    paywallPhoneNeed: "Lookup",
    mailing: "Mailing ready",
    noMailing: "No mailing",
    exclusive: "Exclusive",
    mine: "Your exclusive",
    noPhone: "Phone on demand",
    ledger: "Activity",
    empty: "No synthetic signals. Run the staging seed.",
    readyAll: "All",
    readyLetter: "Letter / Visit",
    readyPhone: "With phone",
    readyLetterBadge: "Ready to mail",
    readyPhoneBadge: "Verified phone",
    readyPhoneEligible: "Phone on demand",
    readyLetterHint: "Exact address + owner + mailing.",
    readyPhoneHint: "On-demand lookup — $3.00.",
    coverage: "Current coverage: {letter} ready to mail · {phone} with phone on demand.",
    readyLetterEmpty: "No signals ready to mail in this market yet.",
    readyLetterEmptyCta: "View all signals",
    readyPhoneEmpty: "No phone-eligible leads in this market. Adjust the city or trade.",
    readyPhoneEmptyCta: "View all signals",
    notReady: "Not ready yet",
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
    signalsSub: "Datos enmascarados hasta el reveal. Teléfono bajo consulta.",
    city: "Plaza",
    all: "Todas",
    trade: "Oficio",
    reveal: "Revelar señal — $1,50",
    phoneCta: "Buscar teléfono — $3,00",
    phoneUnavailable: "La consulta de teléfono no está disponible ahora.",
    phoneNotFound: "No encontramos un teléfono para este lead.",
    phoneAttemptLimit: "Límite de consultas alcanzado. Inténtalo más tarde.",
    phoneNotEligible: "Este lead no tiene teléfono elegible.",
    phoneUnlockedTitle: "Teléfono desbloqueado",
    phoneLabel: "Teléfono",
    paywallPhoneHeadline: "Consulta de teléfono",
    paywallPhoneSub: "La consulta cuesta $3,00. Elige un paquete — los créditos entran en la cartera y el teléfono se consulta al instante.",
    paywallPhoneNeed: "Consulta",
    mailing: "Mailing listo",
    noMailing: "Sin mailing",
    exclusive: "Exclusivo",
    mine: "Tu exclusivo",
    noPhone: "Teléfono bajo consulta",
    ledger: "Movimientos",
    empty: "Sin señales sintéticas. Ejecuta el seed de staging.",
    readyAll: "Todos",
    readyLetter: "Carta / Visita",
    readyPhone: "Con teléfono",
    readyLetterBadge: "Listo para carta",
    readyPhoneBadge: "Teléfono verificado",
    readyPhoneEligible: "Teléfono bajo consulta",
    readyLetterHint: "Dirección exacta + owner + mailing.",
    readyPhoneHint: "Consulta al instante — $3,00.",
    coverage: "Cobertura actual: {letter} listos para carta · {phone} con teléfono bajo consulta.",
    readyLetterEmpty: "Aún no hay señales listas para carta en esta plaza.",
    readyLetterEmptyCta: "Ver todas las señales",
    readyPhoneEmpty: "Sin teléfonos elegibles en esta plaza. Ajusta la ciudad o el oficio.",
    readyPhoneEmptyCta: "Ver todas las señales",
    notReady: "Aún no listo",
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
  readiness: controlledReadiness,
  onReadinessChange,
  city,
  category,
  onCategoryChange,
  onCounts,
}: {
  lang: string;
  wallet: Wallet | null;
  onWallet: (wallet: Wallet) => void;
  readiness?: "all" | "letter" | "phone";
  onReadinessChange?: (key: "all" | "letter" | "phone") => void;
  city?: string;
  category?: string;
  onCategoryChange?: (value: string) => void;
  onCounts?: (counts: { all: number; letter: number; phone: number }) => void;
}) {
  const c = COPY[(lang as keyof typeof COPY) || "pt"] || COPY.pt;
  const [packs, setPacks] = useState<CreditPack[]>([]);
  const [leads, setLeads] = useState<CreditLead[]>([]);
  const [internalReadiness, setInternalReadiness] = useState<"all" | "letter" | "phone">("letter");
  const readiness = controlledReadiness ?? internalReadiness;
  const setReadiness = (key: "all" | "letter" | "phone") => {
    if (onReadinessChange) onReadinessChange(key);
    else setInternalReadiness(key);
  };
  const [counts, setCounts] = useState({ all: 0, letter: 0, phone: 0 });
  const [showAll, setShowAll] = useState(false);
  const [mockPurchase, setMockPurchase] = useState<{ id: number; pack: CreditPack } | null>(null);
  const [paywallLead, setPaywallLead] = useState<CreditLead | null>(null);
  const [paywallAction, setPaywallAction] = useState<"signal" | "phone">("signal");
  const [reveal, setReveal] = useState<RevealPayload | null>(null);
  const [phoneReveal, setPhoneReveal] = useState<PhoneRevealPayload | null>(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [p, l] = await Promise.all([
        getPacks(),
        getLeads({
          limit: 60,
          readiness,
          city: city || undefined,
          trade_code: category || undefined,
        }),
      ]);
      setPacks(p.packs);
      setLeads(l.leads);
      if (l.counts) {
        setCounts(l.counts);
        onCounts?.(l.counts);
      }
    } catch (err) {
      if (err instanceof CreditsApiError && err.status === 401) return;
      setMessage(err instanceof Error ? err.message : "Erro ao carregar sinais");
    }
  }, [readiness, city, category, onCounts]);

  useEffect(() => {
    load();
  }, [load]);

  const visibleLeads = useMemo(() => {
    return showAll ? leads : leads.slice(0, 9);
  }, [leads, showAll]);

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
    const action = paywallAction;
    setBusy(true);
    try {
      const res = await mockPay(mockPurchase.id);
      if (res.wallet) onWallet(res.wallet);
      setMessage(res.duplicate ? c.duplicate : c.success);
      await load();
      setMockPurchase(null);
      setPaywallLead(null);
      // O crédito entrou: desbloqueia o que estava à espera na modal.
      if (pendingLead) {
        if (action === "phone") await doPhoneReveal(pendingLead);
        else await doReveal(pendingLead);
      }
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
      const res = await revealSignal(lead.id, category || lead.trade_code, key());
      setReveal(res.payload);
      onWallet(res.wallet);
      await load();
      setMessage(res.duplicate ? c.duplicate : c.success);
    } catch (err) {
      if (err instanceof CreditsApiError) {
        if (err.status === 402) {
          setMessage(c.notEnough);
          setPaywallAction("signal");
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

  async function doPhoneReveal(lead: CreditLead) {
    setBusy(true);
    setMessage("");
    try {
      const res = await revealPhone(lead.id, category || lead.trade_code, key());
      if (!res.success) {
        setMessage(
          res.error === "phone_unavailable"
            ? c.phoneUnavailable
            : res.error === "attempt_limit"
              ? c.phoneAttemptLimit
              : c.phoneNotFound,
        );
        return;
      }
      if (res.wallet) onWallet(res.wallet);
      if (res.payload) setPhoneReveal(res.payload);
      await load();
    } catch (err) {
      if (err instanceof CreditsApiError) {
        if (err.status === 402) {
          setPaywallAction("phone");
          setPaywallLead(lead);
          setMessage(c.notEnough);
        } else if (err.status === 422) {
          setMessage(c.phoneNotEligible);
        } else {
          setMessage(err.message);
        }
      } else {
        setMessage(err instanceof Error ? err.message : c.phoneUnavailable);
      }
    } finally {
      setBusy(false);
    }
  }

  const requestPhone = (lead: CreditLead) => {
    if (balance < lead.phone_price_cents) {
      setPaywallAction("phone");
      setPaywallLead(lead);
      setMessage(c.notEnough);
      return;
    }
    void doPhoneReveal(lead);
  };
  const readinessTabs = [
    { key: "all" as const, label: c.readyAll, count: counts.all },
    { key: "letter" as const, label: c.readyLetter, count: counts.letter },
    { key: "phone" as const, label: c.readyPhone, count: counts.phone },
  ];

  return (
    <section data-testid="credits-panel" className="space-y-4">
      <div className="flex flex-wrap items-center gap-1.5 rounded-2xl border border-[var(--sd-border)] bg-[var(--sd-surface)] p-2">
        {readinessTabs.map((tab) => {
          const active = tab.key === readiness;
          return (
            <button
              key={tab.key}
              type="button"
              data-testid={`readiness-${tab.key}`}
              onClick={() => {
                setReadiness(tab.key);
                setShowAll(false);
              }}
              aria-pressed={active}
              className={`inline-flex shrink-0 items-center gap-1.5 rounded-xl px-3 py-2 text-[11px] font-black transition ${
                active
                  ? "bg-[var(--sd-accent)] text-[var(--sd-accent-text)] shadow-sm"
                  : "bg-[var(--sd-surface-2)] text-[var(--sd-muted)] hover:text-[var(--sd-text)]"
              }`}
            >
              {tab.label}
              <span
                className={`rounded-full px-1.5 py-0.5 text-[9px] font-black ${
                  active
                    ? "bg-black/10 text-[var(--sd-accent-text)]"
                    : "bg-[var(--sd-surface)] text-[var(--sd-faint)]"
                }`}
              >
                {tab.count}
              </span>
            </button>
          );
        })}
        <span className="ml-auto px-1 text-[10px] font-semibold text-[var(--sd-muted)]">
          {readiness === "letter" ? c.readyLetterHint : readiness === "phone" ? c.readyPhoneHint : ""}
        </span>
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
            <div className="mt-1 text-[10px] text-[var(--sd-faint)]">
              {c.coverage
                .replace("{letter}", String(counts.letter))
                .replace("{phone}", String(counts.phone))}
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            {onCategoryChange ? (
              <select
                value={category ?? ""}
                onChange={(event) => onCategoryChange(event.target.value)}
                className="rounded-lg border border-[var(--sd-border)] bg-[var(--sd-surface)] px-2 py-1 text-[11px]"
              >
                <option value="">{c.trade}: {c.all}</option>
                {TRADES.map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
            ) : null}
          </div>
        </div>

        <div className="mt-3 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {visibleLeads.length === 0 && (
            <div className="col-span-full rounded-xl border border-[var(--sd-border)] bg-[var(--sd-surface-2)] p-6 text-center">
              {readiness === "phone" ? (
                <>
                  <div className="text-3xl">📞</div>
                  <p className="mt-2 text-sm font-semibold text-[var(--sd-text)]">{c.readyPhoneEmpty}</p>
                  <button
                    type="button"
                    onClick={() => setReadiness("letter")}
                    className="mt-3 rounded-lg bg-[var(--sd-accent)] px-3 py-1.5 text-[10px] font-black text-[var(--sd-accent-text)]"
                  >
                    {c.readyPhoneEmptyCta}
                  </button>
                </>
              ) : readiness === "letter" ? (
                <>
                  <div className="text-3xl">✉️</div>
                  <p className="mt-2 text-sm font-semibold text-[var(--sd-text)]">{c.readyLetterEmpty}</p>
                  <button
                    type="button"
                    onClick={() => setReadiness("all")}
                    className="mt-3 rounded-lg bg-[var(--sd-accent)] px-3 py-1.5 text-[10px] font-black text-[var(--sd-accent-text)]"
                  >
                    {c.readyLetterEmptyCta}
                  </button>
                </>
              ) : (
                <p className="text-sm text-[var(--sd-muted)]">{c.empty}</p>
              )}
            </div>
          )}
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
                {lead.signal_ready ? (
                  <span className="rounded bg-[var(--sd-accent-soft)] px-1.5 py-0.5 font-bold text-[var(--sd-accent)]">
                    {c.readyLetterBadge}
                  </span>
                ) : (
                  <span className="rounded bg-[var(--sd-surface)] px-1.5 py-0.5 font-bold text-[var(--sd-muted)]">
                    {c.notReady}
                  </span>
                )}
                {lead.phone_ready ? (
                  <span className="rounded bg-[var(--sd-info-soft)] px-1.5 py-0.5 font-bold text-[var(--sd-info)]">
                    {c.readyPhoneBadge}
                  </span>
                ) : lead.phone_eligible ? (
                  <span className="rounded bg-[var(--sd-info-soft)] px-1.5 py-0.5 font-bold text-[var(--sd-info)]">
                    {c.readyPhoneEligible}
                  </span>
                ) : (
                  <span className="rounded bg-[var(--sd-surface)] px-1.5 py-0.5 font-bold text-[var(--sd-muted)]">
                    {c.noPhone}
                  </span>
                )}
              </div>
              <button
                disabled={busy || !lead.signal_ready || (lead.exclusive && !lead.exclusive_mine)}
                onClick={() => doReveal(lead)}
                className="mt-3 w-full rounded-lg bg-[var(--sd-accent)] px-3 py-2 text-[10px] font-black text-[var(--sd-accent-text)] disabled:cursor-not-allowed disabled:opacity-40"
              >
                {lead.signal_ready ? c.reveal : c.notReady}
              </button>
              <button
                type="button"
                disabled={busy || !(lead.phone_ready || lead.phone_eligible)}
                onClick={() => requestPhone(lead)}
                className="mt-1.5 w-full rounded-lg border border-[var(--sd-border)] px-3 py-1.5 text-[9px] font-bold text-[var(--sd-info)] disabled:cursor-not-allowed disabled:opacity-40"
              >
                {c.phoneCta}
              </button>
            </article>
          ))}
        </div>
        {leads.length > 9 && !showAll && (
          <button onClick={() => setShowAll(true)} className="mt-3 text-[11px] font-bold text-[var(--sd-accent)] underline">Ver todos os {leads.length} sinais</button>
        )}
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
                <h2 className="mt-1 text-xl font-black">
                  {paywallAction === "phone" ? c.paywallPhoneHeadline : c.paywallHeadline}
                </h2>
                <p className="mt-1 max-w-xl text-xs leading-relaxed text-[var(--sd-muted)]">
                  {paywallAction === "phone" ? c.paywallPhoneSub : c.paywallSub}
                </p>
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
                {c.paywallNeed}: <b className="text-[var(--sd-accent)]">{money(paywallAction === "phone" ? paywallLead.phone_price_cents : paywallLead.signal_price_cents)}</b>
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

      {phoneReveal && (
        <div className="fixed inset-0 z-[1050] flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm" onClick={() => setPhoneReveal(null)}>
          <div className="w-full max-w-lg rounded-2xl border border-[var(--sd-border)] bg-[var(--sd-surface)] p-5 shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between">
              <div className="text-[10px] font-black uppercase tracking-[0.16em] text-[var(--sd-info)]">{c.phoneUnlockedTitle}</div>
              <button onClick={() => setPhoneReveal(null)} className="text-[var(--sd-faint)]">✕</button>
            </div>
            <h2 className="mt-2 text-lg font-black">{phoneReveal.owner_name}</h2>
            <div className="mt-3 space-y-1.5 text-sm">
              <p><b>{c.phoneLabel}:</b> <a className="font-black text-[var(--sd-info)] underline" href={`tel:${phoneReveal.phone}`}>{phoneReveal.phone}</a></p>
              <p><b>{c.address}:</b> {phoneReveal.address}, {phoneReveal.city} {phoneReveal.zip_code || ""}</p>
              <p><b>{c.owner}:</b> {phoneReveal.owner_name}</p>
            </div>
            <button onClick={() => setPhoneReveal(null)} className="mt-4 w-full rounded-lg bg-[var(--sd-text)] px-4 py-2.5 text-sm font-black text-[var(--sd-surface)]">{c.close}</button>
          </div>
        </div>
      )}
    </section>
  );
}

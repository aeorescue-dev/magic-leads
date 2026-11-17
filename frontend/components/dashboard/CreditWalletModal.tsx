"use client";

import { useCallback, useEffect, useState } from "react";
import {
  CreditPack,
  LedgerEntry,
  Wallet,
  createCreditCheckout,
  getLedger,
  getPacks,
  getWallet,
  mockPay,
  mockWebhook,
} from "@/lib/credits-api";

const COPY = {
  pt: {
    title: "Créditos / Planos",
    subtitle: "Compra única. Os créditos entram na carteira imediatamente após o pagamento.",
    wallet: "Carteira",
    credits: "créditos",
    packs: "Pacotes",
    buy: "Comprar",
    ledger: "Movimentos",
    empty: "Ainda sem movimentos.",
    date: "Data",
    type: "Tipo",
    amount: "Créditos",
    balance: "Saldo",
    close: "Fechar",
    mockPay: "Simular pagamento",
    webhook: "Simular webhook duplicado",
    success: "Créditos adicionados",
    duplicate: "Evento duplicado — saldo não mudou",
    error: "Não foi possível concluir a operação.",
  },
  en: {
    title: "Credits / Plans",
    subtitle: "One-time purchase. Credits land in your wallet right after payment.",
    wallet: "Wallet",
    credits: "credits",
    packs: "Packs",
    buy: "Buy",
    ledger: "Activity",
    empty: "No activity yet.",
    date: "Date",
    type: "Type",
    amount: "Credits",
    balance: "Balance",
    close: "Close",
    mockPay: "Simulate payment",
    webhook: "Simulate duplicate webhook",
    success: "Credits added",
    duplicate: "Duplicate event — balance unchanged",
    error: "Could not complete the operation.",
  },
  es: {
    title: "Créditos / Planes",
    subtitle: "Compra única. Los créditos entran en la cartera justo después del pago.",
    wallet: "Cartera",
    credits: "créditos",
    packs: "Paquetes",
    buy: "Comprar",
    ledger: "Movimientos",
    empty: "Aún sin movimientos.",
    date: "Fecha",
    type: "Tipo",
    amount: "Créditos",
    balance: "Saldo",
    close: "Cerrar",
    mockPay: "Simular pago",
    webhook: "Simular webhook duplicado",
    success: "Créditos añadidos",
    duplicate: "Evento duplicado — saldo sin cambios",
    error: "No se pudo completar la operación.",
  },
} as const;

function money(cents: number) {
  return `$${(Math.max(0, cents) / 100).toFixed(2)}`;
}

export default function CreditWalletModal({
  open,
  onClose,
  lang,
  wallet,
  onWallet,
}: {
  open: boolean;
  onClose: () => void;
  lang: string;
  wallet: Wallet | null;
  onWallet: (wallet: Wallet) => void;
}) {
  const c = COPY[(lang as keyof typeof COPY) || "pt"] || COPY.pt;
  const [packs, setPacks] = useState<CreditPack[]>([]);
  const [ledger, setLedger] = useState<LedgerEntry[]>([]);
  const [mockPurchase, setMockPurchase] = useState<{ id: number; pack: CreditPack } | null>(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [w, p, l] = await Promise.all([getWallet(), getPacks(), getLedger(30)]);
      onWallet(w);
      setPacks(p.packs);
      setLedger(l.entries);
    } catch (err) {
      setMessage(err instanceof Error ? err.message : c.error);
    }
  }, [onWallet, c.error]);

  useEffect(() => {
    if (!open) return;
    setMessage("");
    setMockPurchase(null);
    void load();
  }, [open, load]);

  if (!open) return null;

  const balance = wallet?.balance_cents ?? 0;

  const buy = async (pack: CreditPack) => {
    setBusy(true);
    setMessage("");
    try {
      const res = await createCreditCheckout(pack.code, lang);
      if (res.mock) {
        setMockPurchase({ id: res.purchase_id, pack });
      } else if (res.checkout_url) {
        window.location.href = res.checkout_url;
      }
    } catch (err) {
      setMessage(err instanceof Error ? err.message : c.error);
    } finally {
      setBusy(false);
    }
  };

  const payMock = async () => {
    if (!mockPurchase) return;
    setBusy(true);
    try {
      const res = await mockPay(mockPurchase.id);
      if (res.wallet) onWallet(res.wallet);
      setMessage(res.duplicate ? c.duplicate : c.success);
      setMockPurchase(null);
      await load();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : c.error);
    } finally {
      setBusy(false);
    }
  };

  const webhookTwice = async () => {
    if (!mockPurchase) return;
    setBusy(true);
    try {
      const eventId = `evt_wallet_${mockPurchase.id}`;
      const first = await mockWebhook(mockPurchase.id, eventId);
      const second = await mockWebhook(mockPurchase.id, eventId);
      if (first.wallet) onWallet(first.wallet);
      setMessage(
        `Webhook 1: ${first.duplicate ? "duplicado" : "aplicado"} · Webhook 2: ${second.duplicate ? "duplicado" : "aplicado"}`,
      );
      await load();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : c.error);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      data-testid="wallet-modal"
      className="fixed inset-0 z-[1200] flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="max-h-[90vh] w-full max-w-4xl overflow-y-auto rounded-2xl border border-[var(--sd-border)] bg-[var(--sd-surface)] p-5 shadow-2xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="text-[10px] font-black uppercase tracking-[0.16em] text-[var(--sd-accent)]">
              {c.title}
            </div>
            <div className="mt-1 text-2xl font-black">
              {c.wallet}: {money(balance)} · {balance} {c.credits}
            </div>
            <p className="mt-1 text-xs text-[var(--sd-muted)]">{c.subtitle}</p>
          </div>
          <button
            type="button"
            aria-label={c.close}
            onClick={onClose}
            className="rounded-lg px-2 py-1 text-lg text-[var(--sd-faint)] hover:bg-[var(--sd-surface-2)]"
          >
            ✕
          </button>
        </div>

        {message ? (
          <div className="mt-3 rounded-xl border border-[var(--sd-accent)]/30 bg-[var(--sd-accent-soft)] px-3 py-2 text-xs font-semibold text-[var(--sd-accent)]">
            {message}
          </div>
        ) : null}

        <div className="mt-4 text-[10px] font-black uppercase tracking-[0.16em] text-[var(--sd-faint)]">
          {c.packs}
        </div>
        <div className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
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
              <div className="text-[10px] text-[var(--sd-muted)]">
                {pack.credits_cents} {c.credits}
              </div>
              {pack.bonus_cents > 0 ? (
                <div className="text-[9px] font-bold text-amber-500">+{pack.bonus_cents} bónus</div>
              ) : null}
              <div className="mt-1 text-[9px] font-black uppercase tracking-[0.12em] text-[var(--sd-accent)]">
                {c.buy}
              </div>
            </button>
          ))}
        </div>

        {mockPurchase ? (
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
        ) : null}

        <div className="mt-5 text-[10px] font-black uppercase tracking-[0.16em] text-[var(--sd-faint)]">
          {c.ledger}
        </div>
        <div className="mt-2 overflow-x-auto">
          <table className="w-full min-w-[480px] text-left text-[11px]">
            <thead className="text-[9px] uppercase tracking-[0.1em] text-[var(--sd-faint)]">
              <tr>
                <th className="py-1">{c.date}</th>
                <th>{c.type}</th>
                <th>{c.amount}</th>
                <th>{c.balance}</th>
              </tr>
            </thead>
            <tbody>
              {ledger.map((entry) => (
                <tr key={entry.id} className="border-t border-[var(--sd-border)]">
                  <td className="py-1 text-[var(--sd-muted)]">
                    {new Date(entry.created_at).toLocaleDateString()}
                  </td>
                  <td className="font-semibold">{entry.event_type}</td>
                  <td className={entry.amount < 0 ? "font-black text-rose-500" : "font-black text-[var(--sd-accent)]"}>
                    {entry.amount > 0 ? "+" : ""}
                    {entry.amount}
                  </td>
                  <td className="font-semibold">{entry.balance_after ?? "—"}</td>
                </tr>
              ))}
              {ledger.length === 0 ? (
                <tr>
                  <td colSpan={4} className="py-3 text-[var(--sd-muted)]">
                    {c.empty}
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>

        <div className="mt-4 flex justify-end">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-[var(--sd-border)] px-4 py-2 text-xs font-bold text-[var(--sd-muted)] hover:bg-[var(--sd-surface-2)]"
          >
            {c.close}
          </button>
        </div>
      </div>
    </div>
  );
}

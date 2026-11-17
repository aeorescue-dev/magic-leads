"use client";

import { useCallback, useEffect, useState } from "react";
import {
  AddonPack,
  Usage,
  createAddonCheckout,
  getBillingPlans,
  getSubscriptionUsage,
  mockAddonPay,
} from "@/lib/subscription-api";

const COPY = {
  pt: {
    title: "Mais telefones por 24h",
    subtitle: "A tua cota diária terminou. Escolhe um add-on para continuar agora.",
    remaining: "Telefones disponíveis",
    base: "Cota diária",
    addon: "Add-on ativo",
    buy: "Comprar",
    close: "Fechar",
    mock: "Adicionar unidades (teste)",
    mockNote: "Staging: injeção de teste, sem pagamento real.",
    error: "Não foi possível concluir a operação.",
    valid: "Válido 24h a partir da compra.",
  },
  en: {
    title: "More phones for 24h",
    subtitle: "Your daily quota is over. Choose an add-on to keep working now.",
    remaining: "Available phones",
    base: "Daily quota",
    addon: "Active add-on",
    buy: "Buy",
    close: "Close",
    mock: "Add units (test)",
    mockNote: "Staging: test injection, no real payment.",
    error: "Could not complete the operation.",
    valid: "Valid for 24h from purchase.",
  },
  es: {
    title: "Más teléfonos por 24h",
    subtitle: "Tu cuota diaria terminó. Elige un add-on para continuar ahora.",
    remaining: "Teléfonos disponibles",
    base: "Cuota diaria",
    addon: "Add-on activo",
    buy: "Comprar",
    close: "Cerrar",
    mock: "Añadir unidades (prueba)",
    mockNote: "Staging: inyección de prueba, sin pago real.",
    error: "No se pudo completar la operación.",
    valid: "Válido 24h desde la compra.",
  },
} as const;

function money(cents: number) {
  return `$${(Math.max(0, cents) / 100).toFixed(2)}`;
}

export default function AddonModal({
  open,
  onClose,
  lang,
  usage,
  onChanged,
}: {
  open: boolean;
  onClose: () => void;
  lang: string;
  usage: Usage | null;
  onChanged: () => void;
}) {
  const c = COPY[(lang as keyof typeof COPY) || "pt"] || COPY.pt;
  const [packs, setPacks] = useState<AddonPack[]>([]);
  const [billingMock, setBillingMock] = useState(false);
  const [current, setCurrent] = useState<Usage | null>(usage);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [p, u] = await Promise.all([getBillingPlans(), getSubscriptionUsage()]);
      setPacks(p.addons || []);
      setBillingMock(Boolean(p.billing_mock));
      setCurrent(u);
    } catch (err) {
      setMessage(err instanceof Error ? err.message : c.error);
    }
  }, [c.error]);

  useEffect(() => {
    if (!open) return;
    setMessage("");
    void load();
  }, [open, load]);

  useEffect(() => {
    if (usage) setCurrent(usage);
  }, [usage]);

  if (!open) return null;

  const buy = async (pack: AddonPack) => {
    setBusy(true);
    setMessage("");
    try {
      const res = await createAddonCheckout(pack.code, lang);
      if (res.mock) {
        if (billingMock) {
          await mockAddonPay(pack.code);
          await load();
          onChanged();
          setMessage(c.mockNote);
        } else {
          setMessage(c.error);
        }
        return;
      }
      if (res.checkout_url) window.location.href = res.checkout_url;
    } catch (err) {
      setMessage(err instanceof Error ? err.message : c.error);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      data-testid="addon-modal"
      className="fixed inset-0 z-[1200] flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="max-h-[92vh] w-full max-w-3xl overflow-y-auto rounded-2xl border border-[var(--sd-border)] bg-[var(--sd-surface)] p-5 shadow-2xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="text-[10px] font-black uppercase tracking-[0.16em] text-[var(--sd-accent)]">
              {c.title}
            </div>
            <h2 className="mt-1 text-xl font-black">{c.remaining}: {current?.phone_remaining ?? 0}</h2>
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

        <div className="mt-3 flex flex-wrap gap-3 rounded-xl border border-[var(--sd-border)] bg-[var(--sd-surface-2)] px-3 py-2 text-[11px] text-[var(--sd-muted)]">
          <span>{c.base}: <b className="text-[var(--sd-text)]">{Math.max(0, (current?.phone_limit ?? 0) - (current?.phone_used ?? 0))}</b></span>
          <span>{c.addon}: <b className="text-[var(--sd-text)]">{current?.addon_remaining ?? 0}</b></span>
          {current?.addon_expires_at ? <span>{new Date(current.addon_expires_at).toLocaleString()}</span> : null}
        </div>

        {message ? (
          <div className="mt-3 rounded-xl border border-[var(--sd-accent)]/30 bg-[var(--sd-accent-soft)] px-3 py-2 text-xs font-semibold text-[var(--sd-accent)]">
            {message}
          </div>
        ) : null}

        <div className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {packs.map((pack) => (
            <button
              key={pack.code}
              type="button"
              data-testid={`addon-${pack.code}`}
              disabled={busy}
              onClick={() => buy(pack)}
              className="rounded-xl border border-[var(--sd-border)] bg-[var(--sd-surface-2)] p-3 text-left transition hover:border-[var(--sd-accent)] disabled:opacity-50"
            >
              <div className="flex items-baseline justify-between gap-2">
                <span className="text-sm font-black">+{pack.phone_count}</span>
                <span className="text-sm font-black text-[var(--sd-accent)]">{money(pack.price_cents)}</span>
              </div>
              <div className="text-[10px] text-[var(--sd-muted)]">{c.valid}</div>
              <div className="mt-1 text-[9px] font-black uppercase tracking-[0.12em] text-[var(--sd-accent)]">
                {billingMock ? c.mock : c.buy}
              </div>
            </button>
          ))}
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

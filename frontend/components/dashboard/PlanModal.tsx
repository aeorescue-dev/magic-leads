"use client";

import { useCallback, useEffect, useState } from "react";
import {
  AddonPack,
  SubscriptionInfo,
  SubscriptionPlan,
  Usage,
  createBillingPortal,
  createPlanCheckout,
  getBillingPlans,
  getSubscriptionInfo,
  getSubscriptionUsage,
  mockPlanCheckout,
} from "@/lib/subscription-api";

const COPY = {
  pt: {
    title: "Planos semanais",
    subtitle: "Escolhe o plano. As cartas/visitas e os telefones têm contadores diários.",
    current: "Plano atual",
    choose: "Assinar",
    manage: "Gerir plano",
    phone: "telefones/dia",
    letters: "10 cartas/visitas/dia",
    week: "por semana",
    perWeek: "/ semana",
    close: "Fechar",
    mock: "Ativar plano de teste",
    mockNote: "Staging: ativação de teste, sem pagamento real.",
    error: "Não foi possível concluir a operação.",
  },
  en: {
    title: "Weekly plans",
    subtitle: "Choose a plan. Letters/visits and phones have daily counters.",
    current: "Current plan",
    choose: "Subscribe",
    manage: "Manage plan",
    phone: "phones/day",
    letters: "10 letters/visits/day",
    week: "per week",
    perWeek: "/ week",
    close: "Close",
    mock: "Activate test plan",
    mockNote: "Staging: test activation, no real payment.",
    error: "Could not complete the operation.",
  },
  es: {
    title: "Planes semanales",
    subtitle: "Elige un plan. Cartas/visitas y teléfonos tienen contadores diarios.",
    current: "Plan actual",
    choose: "Suscribirse",
    manage: "Gestionar plan",
    phone: "teléfonos/día",
    letters: "10 cartas/visitas/día",
    week: "por semana",
    perWeek: "/ semana",
    close: "Cerrar",
    mock: "Activar plan de prueba",
    mockNote: "Staging: activación de prueba, sin pago real.",
    error: "No se pudo completar la operación.",
  },
} as const;

function money(cents: number) {
  const value = Math.max(0, cents) / 100;
  return Number.isInteger(value) ? `$${value}` : `$${value.toFixed(2)}`;
}

export default function PlanModal({
  open,
  onClose,
  lang,
  onChanged,
}: {
  open: boolean;
  onClose: () => void;
  lang: string;
  onChanged: () => void;
}) {
  const c = COPY[(lang as keyof typeof COPY) || "pt"] || COPY.pt;
  const [plans, setPlans] = useState<SubscriptionPlan[]>([]);
  const [addons, setAddons] = useState<AddonPack[]>([]);
  const [usage, setUsage] = useState<Usage | null>(null);
  const [info, setInfo] = useState<SubscriptionInfo | null>(null);
  const [billingMock, setBillingMock] = useState(false);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [p, u, i] = await Promise.all([
        getBillingPlans(),
        getSubscriptionUsage(),
        getSubscriptionInfo(),
      ]);
      setPlans(p.plans || []);
      setAddons(p.addons || []);
      setBillingMock(Boolean(p.billing_mock));
      setUsage(u);
      setInfo(i);
    } catch (err) {
      setMessage(err instanceof Error ? err.message : c.error);
    }
  }, [c.error]);

  useEffect(() => {
    if (!open) return;
    setMessage("");
    void load();
  }, [open, load]);

  if (!open) return null;

  const currentPlan = info?.plan || usage?.plan || "";
  const currentPlanName =
    plans.find((p) => p.code === currentPlan)?.name || currentPlan;
  const canAccess = Boolean(info?.can_access);

  const subscribe = async (plan: SubscriptionPlan) => {
    setBusy(true);
    setMessage("");
    try {
      const res = await createPlanCheckout(plan.code, lang);
      if (res.mock) {
        if (billingMock) {
          await mockPlanCheckout(plan.code);
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

  const manage = async () => {
    setBusy(true);
    setMessage("");
    try {
      const res = await createBillingPortal(lang);
      if (res.url) window.location.href = res.url;
    } catch (err) {
      setMessage(err instanceof Error ? err.message : c.error);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      data-testid="plan-modal"
      className="fixed inset-0 z-[1200] flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="max-h-[92vh] w-full max-w-6xl overflow-y-auto rounded-2xl border border-[var(--sd-border)] bg-[var(--sd-surface)] p-5 shadow-2xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="text-[10px] font-black uppercase tracking-[0.16em] text-[var(--sd-accent)]">
              {c.title}
            </div>
            <h2 className="mt-1 text-2xl font-black">{canAccess ? `${currentPlanName}` : c.title}</h2>
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

        <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {plans.map((plan) => {
            const active = plan.code === currentPlan && canAccess;
            return (
              <div
                key={plan.code}
                data-testid={`plan-${plan.code}`}
                className={`rounded-2xl border p-4 ${
                  active
                    ? "border-[var(--sd-accent)] bg-[var(--sd-accent-soft)]"
                    : "border-[var(--sd-border)] bg-[var(--sd-surface-2)]"
                }`}
              >
                <div className="flex items-baseline justify-between gap-2">
                  <div className="text-sm font-black">{plan.name}</div>
                  <div className="text-lg font-black text-[var(--sd-accent)]">{money(plan.price_cents)}</div>
                </div>
                <div className="text-[10px] text-[var(--sd-muted)]">{c.week}</div>
                <div className="mt-3 space-y-1 text-[11px] text-[var(--sd-muted)]">
                  <div><b className="text-[var(--sd-text)]">{plan.daily_phone_limit}</b> {c.phone}</div>
                  <div><b className="text-[var(--sd-text)]">{plan.weekly_phone_total}</b> {c.perWeek}</div>
                  <div>{c.letters}</div>
                </div>
                <button
                  type="button"
                  disabled={busy || active}
                  onClick={() => subscribe(plan)}
                  className={`mt-4 w-full rounded-lg px-3 py-2 text-[11px] font-black transition ${
                    active
                      ? "bg-[var(--sd-surface)] text-[var(--sd-accent)]"
                      : "bg-[var(--sd-accent)] text-[var(--sd-accent-text)] hover:opacity-90"
                  } disabled:cursor-not-allowed disabled:opacity-60`}
                >
                  {active ? c.current : billingMock ? c.mock : c.choose}
                </button>
              </div>
            );
          })}
        </div>

        <div className="mt-5 flex flex-wrap items-center justify-between gap-3">
          <p className="text-[10px] text-[var(--sd-faint)]">
            {billingMock ? c.mockNote : ""}
            {addons.length ? ` · ${addons.length} add-ons 24h` : ""}
          </p>
          <div className="flex gap-2">
            {canAccess && info?.stripe_customer_id && !billingMock ? (
              <button
                type="button"
                disabled={busy}
                onClick={manage}
                className="rounded-lg border border-[var(--sd-border)] px-4 py-2 text-xs font-bold text-[var(--sd-muted)] hover:bg-[var(--sd-surface-2)]"
              >
                {c.manage}
              </button>
            ) : null}
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
    </div>
  );
}

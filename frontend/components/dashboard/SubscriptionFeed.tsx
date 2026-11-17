"use client";

import { useMemo, useState } from "react";
import type { LeadResponse } from "@/lib/api-client";
import {
  LetterPayload,
  PhonePayload,
  SubscriptionApiError,
  SubscriptionPlan,
  Usage,
  revealLetter,
  revealPhone,
} from "@/lib/subscription-api";

const COPY = {
  pt: {
    signals: "Sinais ativos",
    signalsSub: "Morada/carta é livre para assinantes. Telefones usam a cota diária.",
    plan: "Plano",
    today: "hoje",
    letter: "Morada / Carta",
    phone: "Revelar Telefone",
    remaining: "Restam {n} hoje",
    subscribe: "Assinar para desbloquear",
    addons: "Comprar mais telefones",
    noPhone: "Sem telefone elegível",
    loading: "A consultar…",
    empty: "Sem sinais nesta zona. Ajusta a cidade ou o ofício.",
    loadMore: "Carregar mais oportunidades",
    letterLimit: "Limite diário de 10 cartas/visitas atingido.",
    phoneUnavailable: "Telefone indisponível para este imóvel — a cota diária foi preservada.",
    phoneFound: "Telefone desbloqueado",
    letterFound: "Morada e proprietário",
    address: "Endereço",
    owner: "Proprietário",
    mailing: "Mailing",
    phoneLabel: "Telefone",
    close: "Fechar",
    error: "Não foi possível concluir.",
  },
  en: {
    signals: "Active signals",
    signalsSub: "Address/letter is free for subscribers. Phones use the daily quota.",
    plan: "Plan",
    today: "today",
    letter: "Address / Letter",
    phone: "Reveal Phone",
    remaining: "{n} left today",
    subscribe: "Subscribe to unlock",
    addons: "Buy more phones",
    noPhone: "No phone eligible",
    loading: "Checking…",
    empty: "No signals in this area. Adjust the city or trade.",
    loadMore: "Load more opportunities",
    letterLimit: "Daily limit of 10 letters/visits reached.",
    phoneUnavailable: "Phone unavailable for this property — your daily quota was preserved.",
    phoneFound: "Phone unlocked",
    letterFound: "Address and owner",
    address: "Address",
    owner: "Owner",
    mailing: "Mailing",
    phoneLabel: "Phone",
    close: "Close",
    error: "Could not complete.",
  },
  es: {
    signals: "Señales activas",
    signalsSub: "Dirección/carta es gratis para suscriptores. Los teléfonos usan la cuota diaria.",
    plan: "Plan",
    today: "hoy",
    letter: "Dirección / Carta",
    phone: "Revelar Teléfono",
    remaining: "Quedan {n} hoy",
    subscribe: "Suscribirse para desbloquear",
    addons: "Comprar más teléfonos",
    noPhone: "Sin teléfono elegible",
    loading: "Consultando…",
    empty: "Sin señales en esta zona. Ajusta la ciudad u oficio.",
    loadMore: "Cargar más oportunidades",
    letterLimit: "Límite diario de 10 cartas/visitas alcanzado.",
    phoneUnavailable: "Teléfono no disponible para este inmueble — la cuota diaria se conservó.",
    phoneFound: "Teléfono desbloqueado",
    letterFound: "Dirección y propietario",
    address: "Dirección",
    owner: "Propietario",
    mailing: "Mailing",
    phoneLabel: "Teléfono",
    close: "Cerrar",
    error: "No se pudo completar.",
  },
} as const;

function maskAddress(value: string | undefined) {
  const text = String(value || "").trim();
  if (!text) return "***";
  const first = text.split(",")[0].trim().split(/\s+/);
  return first.length > 1 ? `*** ${first.slice(1).join(" ")}` : "***";
}

export default function SubscriptionFeed({
  leads,
  loading,
  usage,
  plans,
  isActive,
  onOpenPlans,
  onOpenAddons,
  onRefresh,
  lang,
  readiness,
  hasMore = false,
  loadingMore = false,
  onLoadMore,
  onOpenLead,
}: {
  leads: LeadResponse[];
  loading: boolean;
  usage: Usage | null;
  plans: SubscriptionPlan[];
  isActive: boolean;
  onOpenPlans: () => void;
  onOpenAddons: () => void;
  onRefresh: () => void;
  lang: string;
  readiness: "all" | "letter" | "phone";
  hasMore?: boolean;
  loadingMore?: boolean;
  onLoadMore?: () => void;
  onOpenLead?: (lead: LeadResponse) => void;
}) {
  const c = COPY[(lang as keyof typeof COPY) || "pt"] || COPY.pt;
  const [letter, setLetter] = useState<LetterPayload | null>(null);
  const [phone, setPhone] = useState<PhonePayload | null>(null);
  const [revealedLetters, setRevealedLetters] = useState<Record<number, LetterPayload>>({});
  const [busyId, setBusyId] = useState<number | null>(null);
  const [message, setMessage] = useState("");

  const planName = useMemo(
    () => plans.find((p) => p.code === usage?.plan)?.name || usage?.plan || "",
    [plans, usage?.plan],
  );
  const phoneRemaining = usage?.phone_remaining ?? 0;

  const doLetter = async (lead: LeadResponse) => {
    if (!isActive) {
      onOpenPlans();
      return;
    }
    setBusyId(Number(lead.id));
    setMessage("");
    try {
      const res = await revealLetter(Number(lead.id));
      setLetter(res.payload);
      setRevealedLetters((prev) => ({ ...prev, [Number(lead.id)]: res.payload }));
      onRefresh();
    } catch (err) {
      if (err instanceof SubscriptionApiError && err.status === 429) {
        setMessage(c.letterLimit);
      } else {
        setMessage(err instanceof Error ? err.message : c.error);
      }
    } finally {
      setBusyId(null);
    }
  };

  const doPhone = async (lead: LeadResponse) => {
    if (!isActive) {
      onOpenPlans();
      return;
    }
    if (!lead.phone_eligible && !lead.phone_ready) {
      setMessage(c.noPhone);
      return;
    }
    if (phoneRemaining <= 0) {
      onOpenAddons();
      return;
    }
    setBusyId(Number(lead.id));
    setMessage("");
    try {
      const res = await revealPhone(Number(lead.id), crypto.randomUUID());
      if (!res.success) {
        setMessage(res.message || c.phoneUnavailable);
        onRefresh();
        return;
      }
      if (res.payload) setPhone(res.payload);
      onRefresh();
    } catch (err) {
      if (err instanceof SubscriptionApiError && err.status === 429) {
        onOpenAddons();
        setMessage(err.message);
      } else {
        setMessage(err instanceof Error ? err.message : c.phoneUnavailable);
      }
    } finally {
      setBusyId(null);
    }
  };

  return (
    <section
      data-testid="subscription-feed"
      data-readiness={readiness}
      className="flex flex-col overflow-hidden rounded-2xl border border-[var(--sd-border)] bg-[var(--sd-surface)]"
    >
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--sd-border)] px-5 py-4">
        <div>
          <h2 className="flex items-center gap-2 text-base font-bold">
            {c.signals}
            <span className="rounded-full bg-[var(--sd-accent-soft)] px-2 py-0.5 text-xs font-semibold text-[var(--sd-accent)]">
              {leads.length.toLocaleString()}
            </span>
          </h2>
          <p className="text-xs text-[var(--sd-muted)]">{c.signalsSub}</p>
        </div>
        <div className="text-right text-[11px] text-[var(--sd-muted)]">
          {isActive ? (
            <>
              <div className="font-bold text-[var(--sd-text)]">
                {c.plan} {planName} · {usage?.phone_used ?? 0}/{usage?.phone_limit ?? 0} {c.today}
              </div>
              <div>
                {usage?.letter_used ?? 0}/{usage?.letter_limit ?? 10} cartas ·{" "}
                {phoneRemaining} telefones
              </div>
            </>
          ) : (
            <button
              type="button"
              onClick={onOpenPlans}
              className="rounded-lg bg-[var(--sd-accent)] px-3 py-2 text-[11px] font-black text-[var(--sd-accent-text)]"
            >
              {c.subscribe}
            </button>
          )}
        </div>
      </div>

      {message ? (
        <div className="border-b border-[var(--sd-border)] bg-[var(--sd-soft)] px-5 py-2 text-[11px] font-semibold text-[var(--sd-muted)]">
          {message}
        </div>
      ) : null}

      {loading ? (
        <div className="p-5 text-sm text-[var(--sd-muted)]">{c.loading}</div>
      ) : leads.length === 0 ? (
        <div className="p-10 text-center text-sm text-[var(--sd-muted)]">{c.empty}</div>
      ) : (
        <div className="grid gap-3 p-4 md:grid-cols-2 xl:grid-cols-3">
          {leads.map((lead) => {
            const id = Number(lead.id);
            const revealed = revealedLetters[id];
            const busy = busyId === id;
            const phoneReady = Boolean(lead.phone_eligible || lead.phone_ready);
            return (
              <article
                key={lead.id}
                data-testid={`lead-card-${lead.id}`}
                className="rounded-xl border border-[var(--sd-border)] bg-[var(--sd-surface-2)] p-3"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="text-[9px] font-black uppercase tracking-[0.12em] text-[var(--sd-accent)]">
                      {lead.city} · {lead.issue_category}
                    </div>
                    <button
                      type="button"
                      onClick={() => onOpenLead?.(lead)}
                      className="mt-1 line-clamp-2 text-left text-xs font-black hover:underline"
                    >
                      {lead.case_title || lead.issue_description || "Oportunidade ativa"}
                    </button>
                  </div>
                  <span className="rounded-full bg-[var(--sd-accent-soft)] px-2 py-0.5 text-[8px] font-black text-[var(--sd-accent)]">
                    LIVE
                  </span>
                </div>
                <p className="mt-2 text-[11px] font-semibold text-[var(--sd-text)]">
                  {revealed?.address || maskAddress(lead.address)}
                </p>
                <p className="text-[10px] text-[var(--sd-muted)]">
                  {revealed?.owner_name || lead.owner_name || "Proprietário mascarado"} ·{" "}
                  {lead.neighborhood || lead.zip_code || lead.city}
                </p>
                <div className="mt-2 flex flex-wrap gap-1 text-[9px]">
                  {revealed ? (
                    <span className="rounded bg-[var(--sd-accent-soft)] px-1.5 py-0.5 font-bold text-[var(--sd-accent)]">
                      {c.letterFound}
                    </span>
                  ) : null}
                  {lead.phone_ready ? (
                    <span className="rounded bg-[var(--sd-info-soft)] px-1.5 py-0.5 font-bold text-[var(--sd-info)]">
                      {c.phoneFound}
                    </span>
                  ) : lead.phone_eligible ? (
                    <span className="rounded bg-[var(--sd-info-soft)] px-1.5 py-0.5 font-bold text-[var(--sd-info)]">
                      Telefone sob consulta
                    </span>
                  ) : (
                    <span className="rounded bg-[var(--sd-surface)] px-1.5 py-0.5 font-bold text-[var(--sd-muted)]">
                      {c.noPhone}
                    </span>
                  )}
                </div>
                <button
                  type="button"
                  data-testid={`reveal-letter-${lead.id}`}
                  disabled={busy}
                  onClick={() => doLetter(lead)}
                  className="mt-3 w-full rounded-lg border border-[var(--sd-border)] px-3 py-2 text-[10px] font-black text-[var(--sd-text)] disabled:opacity-40"
                >
                  {busy ? c.loading : isActive ? c.letter : c.subscribe}
                </button>
                <button
                  type="button"
                  data-testid={`reveal-phone-${lead.id}`}
                  disabled={busy || (isActive && !phoneReady)}
                  onClick={() => doPhone(lead)}
                  className="mt-1.5 w-full rounded-lg bg-[var(--sd-accent)] px-3 py-2 text-[10px] font-black text-[var(--sd-accent-text)] disabled:cursor-not-allowed disabled:opacity-40"
                >
                  {!isActive
                    ? c.subscribe
                    : !phoneReady
                      ? c.noPhone
                      : phoneRemaining <= 0
                        ? c.addons
                        : `${c.phone} · ${c.remaining.replace("{n}", String(phoneRemaining))}`}
                </button>
              </article>
            );
          })}
        </div>
      )}

      {hasMore && !loading && onLoadMore ? (
        <div className="border-t border-[var(--sd-border)] p-4">
          <button
            type="button"
            onClick={onLoadMore}
            disabled={loadingMore}
            className="w-full rounded-xl border border-[var(--sd-border)] px-4 py-2.5 text-[11px] font-black text-[var(--sd-text)] transition hover:bg-[var(--sd-surface-2)] disabled:opacity-50"
          >
            {loadingMore ? c.loading : c.loadMore}
          </button>
        </div>
      ) : null}

      {letter ? (
        <div className="fixed inset-0 z-[1050] flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm" onClick={() => setLetter(null)}>
          <div className="w-full max-w-lg rounded-2xl border border-[var(--sd-border)] bg-[var(--sd-surface)] p-5 shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between">
              <div className="text-[10px] font-black uppercase tracking-[0.16em] text-[var(--sd-accent)]">
                {c.letterFound}
              </div>
              <button onClick={() => setLetter(null)} className="text-[var(--sd-faint)]">✕</button>
            </div>
            <h2 className="mt-2 text-lg font-black">{letter.owner_name}</h2>
            <div className="mt-3 space-y-1.5 text-sm">
              <p><b>{c.address}:</b> {letter.address}, {letter.city} {letter.zip_code || ""}</p>
              <p><b>{c.owner}:</b> {letter.owner_name}</p>
              <p><b>{c.mailing}:</b> {letter.mailing_address || "—"}</p>
            </div>
            <button onClick={() => setLetter(null)} className="mt-4 w-full rounded-lg bg-[var(--sd-text)] px-4 py-2.5 text-sm font-black text-[var(--sd-surface)]">
              {c.close}
            </button>
          </div>
        </div>
      ) : null}

      {phone ? (
        <div className="fixed inset-0 z-[1050] flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm" onClick={() => setPhone(null)}>
          <div className="w-full max-w-lg rounded-2xl border border-[var(--sd-border)] bg-[var(--sd-surface)] p-5 shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between">
              <div className="text-[10px] font-black uppercase tracking-[0.16em] text-[var(--sd-info)]">
                {c.phoneFound}
              </div>
              <button onClick={() => setPhone(null)} className="text-[var(--sd-faint)]">✕</button>
            </div>
            <h2 className="mt-2 text-lg font-black">{phone.owner_name}</h2>
            <div className="mt-3 space-y-1.5 text-sm">
              <p><b>{c.phoneLabel}:</b> <a className="font-black text-[var(--sd-info)] underline" href={`tel:${phone.phone}`}>{phone.phone}</a></p>
              <p><b>{c.address}:</b> {phone.address}, {phone.city} {phone.zip_code || ""}</p>
              <p><b>{c.owner}:</b> {phone.owner_name}</p>
            </div>
            <button onClick={() => setPhone(null)} className="mt-4 w-full rounded-lg bg-[var(--sd-text)] px-4 py-2.5 text-sm font-black text-[var(--sd-surface)]">
              {c.close}
            </button>
          </div>
        </div>
      ) : null}
    </section>
  );
}

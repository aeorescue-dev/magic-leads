"use client";

import { useEffect } from "react";
import type { ReactNode } from "react";
import { ArrowRight, Clock, Lock, MapPin, ShieldCheck, UserRound, X } from "lucide-react";
import { useI18n } from "@/lib/i18n";
import type { Opportunity } from "@/lib/api-client";
import {
  categoryLabelKey,
  deadlineLabel,
  inspectionStatusLabel,
  ownerTypeLabel,
  severityColor,
  severityKey,
  sourceLabel,
  tagLabel,
} from "@/lib/opportunity-format";

export function OpportunityDrawer({
  opportunity,
  onClose,
  onReveal,
}: {
  opportunity: Opportunity;
  onClose: () => void;
  onReveal: () => void;
}) {
  const { t, lang } = useI18n();
  const accent = severityColor(opportunity.severity);
  const labelKey = categoryLabelKey(opportunity.category);
  const category = labelKey ? t(labelKey) : opportunity.category || opportunity.address;
  const money = (value?: number | null) =>
    value == null
      ? "—"
      : new Intl.NumberFormat(lang === "pt" ? "pt-BR" : lang === "es" ? "es-MX" : "en-US", {
          style: "currency",
          currency: "USD",
          maximumFractionDigits: 0,
        }).format(value);
  const numberValue = (value?: string | number | null) => {
    if (value == null || value === "") return null;
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  };
  const property = opportunity.property ?? {};
  const history = opportunity.history ?? [];
  const fineBalance = Math.max(
    0,
    Number(opportunity.fine_balance) ||
      (Number(opportunity.fine_imposed) || 0) - (Number(opportunity.fine_paid) || 0),
  );
  const hasFine = fineBalance > 0;
  const currentStep =
    hasFine
      ? 3
      : opportunity.status === "contacted" || opportunity.status === "in_negotiation"
        ? 3
        : opportunity.status === "reserved"
          ? 2
          : 1;
  const valueSourceKey =
    opportunity.value_source === "permit"
      ? "dashboard.value_source.permit"
      : opportunity.value_source === "estimate"
        ? "dashboard.value_source.estimate"
        : "dashboard.value_source.none";
  const dossierRows = [
    { key: "units", value: numberValue(property.units_total ?? property.units_residential) },
    { key: "year_built", value: numberValue(property.year_built) },
    { key: "floors", value: numberValue(property.floors) },
    { key: "lot_area", value: numberValue(property.lot_area) },
  ].filter((row) => row.value != null);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const baseSteps = [
    { id: "complaint", key: "dashboard.preinspection.timeline.complaint", state: "done" },
    {
      id: "inspection",
      key: "dashboard.preinspection.timeline.inspection",
      state: currentStep === 2 ? "current" : currentStep > 2 ? "done" : "future",
    },
    {
      id: "violation",
      key: hasFine ? "dashboard.preinspection.fine_open" : "dashboard.preinspection.timeline.violation",
      state: hasFine ? "done" : currentStep >= 3 ? "done" : "future",
    },
  ];
  const timelineMeta = new Map(
    (opportunity.timeline ?? []).map((entry) => [String(entry.key || ""), entry]),
  );
  const steps = baseSteps.map((step) => {
    const meta = timelineMeta.get(step.id);
    return {
      ...step,
      label: typeof meta?.label === "string" && meta.label ? meta.label : null,
      date: typeof meta?.date === "string" && meta.date ? meta.date.slice(0, 10) : null,
    };
  });
  const statusLabel =
    opportunity.status === "reserved" ||
    opportunity.status === "contacted" ||
    opportunity.status === "in_negotiation"
      ? t("dashboard.status.selected")
      : t("dashboard.status.awaiting_inspection");
  const tags = opportunity.tags ?? [];

  return (
    <div className="fixed inset-0 z-[85] bg-black/50 backdrop-blur-sm" onClick={onClose}>
      <aside
        className="absolute right-0 top-0 flex h-full w-full max-w-[540px] flex-col overflow-hidden border-l border-[var(--sd-border)] bg-[var(--sd-surface)] shadow-2xl"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="opportunity-drawer-title"
      >
        <header className="flex items-start gap-3 border-b border-[var(--sd-border)] px-5 py-4">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className="inline-flex items-center gap-1.5 rounded-full bg-[var(--sd-accent-soft)] px-2 py-1 text-[10px] font-bold uppercase tracking-wide text-[var(--sd-accent)]">
                <ShieldCheck className="h-3 w-3" />
                {t("dashboard.preinspection.badge")}
              </span>
              <span
                className="rounded-full px-2 py-1 text-[10px] font-bold uppercase tracking-wide"
                style={{ color: accent, background: `${accent}14`, border: `1px solid ${accent}40` }}
              >
                {t(severityKey(opportunity.severity))}
              </span>
            </div>
            <h2 id="opportunity-drawer-title" className="mt-2 text-xl font-black tracking-[-0.03em] text-[var(--sd-text)]">
              {category}
            </h2>
            <p className="mt-1 flex items-center gap-1 text-xs text-[var(--sd-muted)]">
              <MapPin className="h-3.5 w-3.5" />
              {opportunity.address}
              {opportunity.city ? ` · ${opportunity.city}` : ""}
              {opportunity.zip_code ? ` ${opportunity.zip_code}` : ""}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label={t("dashboard.preinspection.close")}
            className="grid h-8 w-8 place-items-center rounded-lg border border-[var(--sd-border)] text-[var(--sd-muted)] hover:text-[var(--sd-text)]"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="flex-1 overflow-y-auto px-5 py-4">
          {hasFine ? (
            <div className="rounded-xl border border-[color-mix(in_srgb,var(--sd-urgent)_35%,transparent)] bg-[var(--sd-urgent-soft)] p-3">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-xs font-bold text-[var(--sd-urgent)]">
                    {t("dashboard.preinspection.fine_open")}
                  </p>
                  <p className="mt-1 text-2xl font-black tracking-[-0.03em] text-[var(--sd-urgent)]">
                    {money(fineBalance)}
                  </p>
                </div>
                <span className="rounded-full border border-[color-mix(in_srgb,var(--sd-urgent)_35%,transparent)] px-2 py-1 text-[9px] font-bold uppercase tracking-wide text-[var(--sd-urgent)]">
                  {t("dashboard.preinspection.fine_balance")}
                </span>
              </div>
              <div className="mt-3 grid grid-cols-3 gap-2 border-t border-[color-mix(in_srgb,var(--sd-urgent)_22%,transparent)] pt-3 text-[10px]">
                <div>
                  <p className="font-bold uppercase tracking-[0.08em] text-[var(--sd-faint)]">
                    {t("dashboard.preinspection.fine_imposed")}
                  </p>
                  <p className="mt-0.5 font-semibold text-[var(--sd-text)]">
                    {money(opportunity.fine_imposed)}
                  </p>
                </div>
                <div>
                  <p className="font-bold uppercase tracking-[0.08em] text-[var(--sd-faint)]">
                    {t("dashboard.preinspection.fine_paid")}
                  </p>
                  <p className="mt-0.5 font-semibold text-[var(--sd-text)]">
                    {money(opportunity.fine_paid)}
                  </p>
                </div>
                <div>
                  <p className="font-bold uppercase tracking-[0.08em] text-[var(--sd-faint)]">
                    {t("dashboard.preinspection.hearing_date")}
                  </p>
                  <p className="mt-0.5 font-semibold text-[var(--sd-text)]">
                    {opportunity.hearing_date || "—"}
                  </p>
                </div>
              </div>
              {opportunity.hearing_status ? (
                <p className="mt-2 text-[10px] text-[var(--sd-muted)]">
                  {t("dashboard.preinspection.hearing_status")}: {opportunity.hearing_status}
                </p>
              ) : null}
            </div>
          ) : (
            <div
              className="rounded-xl border bg-[var(--sd-accent-soft)] p-3"
              style={{ borderColor: "color-mix(in srgb, var(--sd-accent) 25%, transparent)" }}
            >
              <p className="text-xs font-bold text-[var(--sd-accent)]">{t("dashboard.preinspection.no_fine")}</p>
              <p className="mt-1 text-[11px] leading-relaxed text-[var(--sd-muted)]">
                {t("dashboard.preinspection.risk")}
              </p>
            </div>
          )}

          <section className="mt-5">
            <h3 className="text-[10px] font-bold uppercase tracking-[0.12em] text-[var(--sd-faint)]">
              {t("dashboard.preinspection.timeline")}
            </h3>
            <div className="mt-3 space-y-0">
              {steps.map((step, index) => (
                <div key={step.key} className="relative flex gap-3 pb-4 last:pb-0">
                  {index < steps.length - 1 ? (
                    <span className="absolute left-[6px] top-3 h-full w-px bg-[var(--sd-border)]" />
                  ) : null}
                  <span
                    className={`relative z-10 mt-0.5 h-3 w-3 shrink-0 rounded-full ${
                      step.state === "done"
                        ? "bg-[var(--sd-accent)]"
                        : step.state === "current"
                          ? "border-2 border-[var(--sd-accent)] bg-[var(--sd-surface)]"
                          : "bg-[var(--sd-border-strong)]"
                    }`}
                  />
                  <div>
                    <p
                      className={`text-xs font-bold ${
                        step.state === "future" ? "text-[var(--sd-faint)]" : "text-[var(--sd-text)]"
                      }`}
                    >
                      {step.label || t(step.key)}
                    </p>
                    <p className="mt-0.5 text-[10px] text-[var(--sd-muted)]">
                      {step.date
                        ? step.date
                        : index === 0
                          ? opportunity.received_at
                            ? opportunity.received_at.slice(0, 10)
                            : t("dashboard.preinspection.received")
                          : step.state === "current"
                            ? inspectionStatusLabel(t, opportunity.inspection_status)
                            : step.state === "done"
                              ? index === steps.length - 1
                                ? opportunity.hearing_date || t("dashboard.preinspection.fine_open")
                                : t("dashboard.preinspection.possible")
                              : t(
                                  index === steps.length - 1
                                    ? "dashboard.preinspection.no_fine"
                                    : "dashboard.preinspection.awaiting",
                                )}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          </section>

          <section className="mt-5 grid grid-cols-2 gap-2">
            <Fact
              label={t("dashboard.preinspection.property")}
              value={`${opportunity.city}${opportunity.state ? `, ${opportunity.state}` : ""} ${opportunity.zip_code || ""}`.trim()}
            />
            <Fact label={t("dashboard.preinspection.owner")} value={opportunity.owner_name || "—"} />
            <Fact
              label={t("dashboard.preinspection.inspection")}
              value={inspectionStatusLabel(t, opportunity.inspection_status)}
            />
            <Fact
              label={t("dashboard.preinspection.source")}
              value={sourceLabel(t, opportunity.source_type)}
            />
            <Fact label={t("dashboard.preinspection.received")} value={opportunity.received_at ? opportunity.received_at.slice(0, 10) : "—"} />
            <Fact label={t("dashboard.preinspection.status")} value={statusLabel} />
            <Fact
              label={t("dashboard.preinspection.value")}
              value={money(opportunity.job_value)}
              hint={t(valueSourceKey)}
            />
            <Fact
              label={t("dashboard.preinspection.owner_type")}
              value={ownerTypeLabel(t, opportunity.owner_type)}
            />
          </section>

          {dossierRows.length > 0 || property.building_class || property.assessed_total ? (
            <section className="mt-5">
              <h3 className="text-[10px] font-bold uppercase tracking-[0.12em] text-[var(--sd-faint)]">
                {t("dashboard.preinspection.property_dossier")}
              </h3>
              <div className="mt-3 grid grid-cols-2 gap-2">
                {property.building_class ? (
                  <Fact
                    label={t("dashboard.preinspection.building_class")}
                    value={String(property.building_class)}
                  />
                ) : null}
                {numberValue(property.assessed_total) != null ? (
                  <Fact
                    label={t("dashboard.preinspection.assessed_value")}
                    value={money(numberValue(property.assessed_total))}
                  />
                ) : null}
                {dossierRows.map((row) => (
                  <Fact
                    key={row.key}
                    label={t(`dashboard.preinspection.${row.key}`)}
                    value={String(row.value)}
                  />
                ))}
              </div>
            </section>
          ) : null}

          <section className="mt-5">
            <h3 className="text-[10px] font-bold uppercase tracking-[0.12em] text-[var(--sd-faint)]">
              {t("dashboard.preinspection.signal_description")}
            </h3>
            <p className="mt-2 rounded-xl border border-[var(--sd-border)] bg-[var(--sd-surface-2)] p-3 text-xs leading-relaxed text-[var(--sd-muted)]">
              {opportunity.description || "—"}
            </p>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {tags.length > 0 ? (
                tags.map((tag) => <Tag key={tag}>{tagLabel(t, tag)}</Tag>)
              ) : (
                <>
                  <Tag>{t(severityKey(opportunity.severity))}</Tag>
                  <Tag>{deadlineLabel(t, opportunity.compliance_deadline)}</Tag>
                  <Tag>{t("dashboard.preinspection.possible")}</Tag>
                </>
              )}
            </div>
          </section>

          {history.length > 0 ? (
            <section className="mt-5">
              <h3 className="text-[10px] font-bold uppercase tracking-[0.12em] text-[var(--sd-faint)]">
                {t("dashboard.preinspection.history")}
              </h3>
              <div className="mt-2 space-y-2">
                {history.slice(0, 8).map((entry, index) => (
                  <article
                    key={`${entry.kind || "event"}-${entry.date || ""}-${index}`}
                    className="rounded-lg border border-[var(--sd-border)] bg-[var(--sd-surface-2)] p-2.5"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <p className="text-[11px] font-semibold leading-snug text-[var(--sd-text)]">
                        {entry.label || "—"}
                      </p>
                      {entry.amount ? (
                        <span className="shrink-0 text-[11px] font-bold text-[var(--sd-urgent)]">
                          {money(Number(entry.amount))}
                        </span>
                      ) : null}
                    </div>
                    <p className="mt-1 text-[9px] uppercase tracking-[0.08em] text-[var(--sd-faint)]">
                      {[entry.date, entry.status].filter(Boolean).join(" · ") || "—"}
                    </p>
                  </article>
                ))}
              </div>
            </section>
          ) : null}

          <section className="mt-5 rounded-xl border border-[var(--sd-border)] p-3">
            <div className="flex items-center gap-2">
              <span className="grid h-9 w-9 place-items-center rounded-lg bg-[var(--sd-accent-soft)] text-[var(--sd-accent)]">
                <UserRound className="h-4 w-4" />
              </span>
              <div className="min-w-0">
                <p className="truncate text-xs font-bold text-[var(--sd-text)]">{opportunity.owner_name || "—"}</p>
                <p className="text-[10px] text-[var(--sd-muted)]">
                  {ownerTypeLabel(t, opportunity.owner_type) !== "—"
                    ? ownerTypeLabel(t, opportunity.owner_type)
                    : t("dashboard.preinspection.owner")}
                </p>
              </div>
            </div>
            <div className="mt-3 flex items-center justify-between gap-2 border-t border-[var(--sd-border)] pt-3">
              <span className="inline-flex items-center gap-1 text-xs font-bold tracking-widest text-[var(--sd-faint)]">
                <Lock className="h-3.5 w-3.5" /> ••• ••• •••
              </span>
              <span className="text-[9px] text-[var(--sd-faint)]">{t("dashboard.reveal.title")}</span>
            </div>
          </section>

          <div className="mt-5 flex items-center gap-2 text-[10px] text-[var(--sd-faint)]">
            <Clock className="h-3.5 w-3.5" />
            {deadlineLabel(t, opportunity.compliance_deadline)}
          </div>
        </div>

        <footer className="flex items-center gap-2 border-t border-[var(--sd-border)] px-5 py-3">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-[var(--sd-border)] px-3 py-2 text-xs font-bold text-[var(--sd-muted)]"
          >
            {t("dashboard.preinspection.close")}
          </button>
          <button
            type="button"
            onClick={onReveal}
            className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-[var(--sd-accent)] px-3 py-2 text-xs font-bold text-[var(--sd-accent-text)]"
          >
            {t("dashboard.reveal.title")}
            <ArrowRight className="h-3.5 w-3.5" />
          </button>
        </footer>
      </aside>
    </div>
  );
}

function Fact({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-lg border border-[var(--sd-border)] bg-[var(--sd-surface-2)] p-2">
      <p className="text-[8px] font-bold uppercase tracking-[0.08em] text-[var(--sd-faint)]">{label}</p>
      <p className="mt-1 truncate text-[11px] font-semibold text-[var(--sd-text)]">{value}</p>
      {hint ? <p className="mt-0.5 truncate text-[9px] text-[var(--sd-faint)]">{hint}</p> : null}
    </div>
  );
}

function Tag({ children }: { children: ReactNode }) {
  return (
    <span className="rounded-full border border-[var(--sd-border)] bg-[var(--sd-surface)] px-2 py-1 text-[9px] font-bold uppercase tracking-wide text-[var(--sd-muted)]">
      {children}
    </span>
  );
}

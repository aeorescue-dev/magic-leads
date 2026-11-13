"use client";

import { ArrowRight, Clock, MapPin, ShieldCheck, UserRound } from "lucide-react";
import { useI18n } from "@/lib/i18n";
import type { Opportunity } from "@/lib/api-client";
import {
  categoryLabelKey,
  deadlineLabel,
  severityColor,
  severityKey,
} from "@/lib/opportunity-format";

const TIMELINE_KEYS = [
  "dashboard.preinspection.timeline.complaint",
  "dashboard.preinspection.timeline.inspection",
  "dashboard.preinspection.timeline.violation",
];

export function PreventiveCard({
  opportunity,
  onOpen,
}: {
  opportunity: Opportunity;
  onOpen: () => void;
}) {
  const { t } = useI18n();
  const accent = severityColor(opportunity.severity);
  const labelKey = categoryLabelKey(opportunity.category);
  const category = labelKey ? t(labelKey) : opportunity.category || opportunity.address;
  const currentStep =
    opportunity.status === "contacted" || opportunity.status === "in_negotiation"
      ? 3
      : opportunity.status === "reserved"
        ? 2
        : 1;

  return (
    <article
      role="button"
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onOpen();
        }
      }}
      className="group relative cursor-pointer overflow-hidden rounded-2xl border border-[var(--sd-border)] bg-[var(--sd-surface)] p-4 text-left transition hover:-translate-y-0.5 hover:shadow-[0_20px_50px_-35px_rgba(15,23,42,0.55)]"
      style={{ borderLeft: `3px solid ${accent}` }}
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
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

      <h3 className="mt-3 truncate text-[15px] font-bold tracking-[-0.02em] text-[var(--sd-text)]">
        {category}
      </h3>
      <p className="mt-1 flex items-center gap-1 truncate text-xs text-[var(--sd-muted)]">
        <MapPin className="h-3 w-3 shrink-0" />
        {opportunity.address}
        {opportunity.city ? ` · ${opportunity.city}` : ""}
        {opportunity.zip_code ? ` ${opportunity.zip_code}` : ""}
      </p>

      <p className="mt-2 line-clamp-2 min-h-[32px] text-xs leading-relaxed text-[var(--sd-muted)]">
        {opportunity.description || t("dashboard.preinspection.signal_description")}
      </p>

      <div className="mt-3 flex items-start gap-1.5">
        {TIMELINE_KEYS.map((key, index) => {
          const step = index + 1;
          const done = step < currentStep;
          const current = step === currentStep;
          return (
            <div key={key} className="flex min-w-0 flex-1 flex-col items-center gap-1">
              <div className="flex w-full items-center">
                {index > 0 ? (
                  <span className={`h-px flex-1 ${done || current ? "bg-[var(--sd-accent)] opacity-50" : "bg-[var(--sd-border)]"}`} />
                ) : null}
                <span
                  className={`h-2 w-2 shrink-0 rounded-full ${
                    done
                      ? "bg-[var(--sd-accent)]"
                      : current
                        ? "border-2 border-[var(--sd-accent)] bg-[var(--sd-surface)]"
                        : "bg-[var(--sd-border-strong)]"
                  }`}
                />
                {index < TIMELINE_KEYS.length - 1 ? (
                  <span className={`h-px flex-1 ${done ? "bg-[var(--sd-accent)] opacity-50" : "bg-[var(--sd-border)]"}`} />
                ) : null}
              </div>
              <span className={`truncate text-[9px] font-semibold ${current ? "text-[var(--sd-accent)]" : "text-[var(--sd-faint)]"}`}>
                {t(key)}
              </span>
            </div>
          );
        })}
      </div>

      <div className="mt-3 flex items-center justify-between gap-2 border-t border-[var(--sd-border)] pt-3">
        <span className="inline-flex items-center gap-1 rounded-full border border-[var(--sd-border)] px-2 py-1 text-[9px] font-bold text-[var(--sd-muted)]">
          <Clock className="h-3 w-3" />
          {deadlineLabel(t, opportunity.compliance_deadline)}
        </span>
        <span className="inline-flex min-w-0 items-center gap-1 text-[10px] font-semibold text-[var(--sd-muted)]">
          <UserRound className="h-3 w-3 shrink-0" />
          <span className="truncate">{opportunity.owner_name || t("dashboard.preinspection.owner")}</span>
        </span>
        <span className="inline-flex items-center gap-0.5 text-[10px] font-bold text-[var(--sd-accent)]">
          {t("dashboard.feed.view_details")}
          <ArrowRight className="h-3 w-3 transition group-hover:translate-x-0.5" />
        </span>
      </div>
    </article>
  );
}

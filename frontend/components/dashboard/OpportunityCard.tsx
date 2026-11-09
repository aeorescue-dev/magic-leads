"use client";

import {
  AlertTriangle,
  ArrowUpRight,
  BadgeCheck,
  Building2,
  CheckCircle2,
  Clock,
  Copy,
  FolderOpen,
  HardHat,
  Landmark,
  Lock,
  Mail,
  MapPin,
  MessageSquare,
  Navigation,
  Phone,
  RefreshCcw,
  Smartphone,
  Star,
} from "lucide-react";
import type { LeadResponse } from "@/lib/api-client";
import { LeadLocationMap } from "@/components/LeadLocationMap";
import { StageBadge } from "@/components/ui/StageBadge";
import { SignalBadge, SignalButton } from "@/components/ui/signal";

export interface OpportunityCategory {
  key: string;
  labelKey: string;
  icon: any;
  color: string;
}

export interface OpportunityCardContext {
  t: (key: string, params?: Record<string, any>) => string;
  isDark: boolean;
  T: any;
  openLeadDetail: (lead: LeadResponse) => void;
  handleQuickReserve: (lead: LeadResponse) => void;
  revealPhoneForLead: (lead: LeadResponse) => void;
  handleToggleFav: (lead: LeadResponse, event: any) => void;
  openReleaseModal: (lead: LeadResponse) => void;
  openMaps: (address: string) => void;
  copyToClipboard: (text: string, kind: string) => void;
  recordContact: (id: string, channel: string) => unknown;
  waHref: (phone: string, message: any) => string;
  smsHref: (phone: string, message: any) => string;
  buildMsgs: (lead: LeadResponse) => any;
  countdownLabel: (iso: string) => string;
  relativeTime: (date: string) => string;
  isClosedCase: (status?: string | null) => boolean;
  isCorporateLead: (lead: LeadResponse) => boolean;
  shouldShowAddressWarning: (lead: LeadResponse) => boolean;
  isFreeLead: (lead: LeadResponse) => boolean;
  isBlockedByQuota: (lead: LeadResponse, remaining?: number) => boolean;
  subscription: any;
  dailyStats: any;
  busyAction: boolean;
  phoneRevealing: any;
}

function ownerTone(lead: LeadResponse, ctx: OpportunityCardContext) {
  if (lead.institutional) return { label: ctx.t("dashboard.badge.institutional"), icon: Landmark, tone: "info" as const };
  if (ctx.isCorporateLead(lead)) return { label: ctx.t("dashboard.badge.private_corporate"), icon: Building2, tone: "accent" as const };
  if (lead.owner_name) return { label: ctx.t("dashboard.badge.private_person"), icon: CheckCircle2, tone: "success" as const };
  return null;
}

export function OpportunityCard({
  lead,
  category,
  ctx,
}: {
  lead: LeadResponse;
  category: OpportunityCategory;
  ctx: OpportunityCardContext;
}) {
  const { t, isDark, T } = ctx;
  const CatIcon = category.icon;
  const vis =
    lead.visibility_status ||
    (lead.status === "reserved" ? "reserved_by_other" : "available");
  const isMine = vis === "reserved_by_me";
  const isReservedByOther = vis === "reserved_by_other";
  const isClosed = lead.signal_status === "closed" || ctx.isClosedCase(lead.case_status);
  const reservedUntil =
    lead.reserved_by_me?.expires_at || lead.reserved_by_other?.expires_at;
  const owner = ownerTone(lead, ctx);
  const OwnerIcon = owner?.icon;
  const messages = ctx.buildMsgs(lead);
  const primaryLabel = isMine
    ? t("dashboard.action.revealed")
    : isClosed
      ? t("dashboard.badge.closed")
      : ctx.isFreeLead(lead)
        ? t("dashboard.action.reserve_corporate")
        : t("dashboard.action.reserve_1h");

  const cardSurface = isDark
    ? "border-[var(--sd-border)] bg-[var(--sd-surface)] hover:border-[var(--sd-border-strong)]"
    : "border-[var(--sd-border)] bg-[var(--sd-surface)] hover:border-[var(--sd-border-strong)] shadow-sm";

  return (
    <article
      data-testid="lead-card"
      data-lead-id={lead.id}
      role="button"
      tabIndex={0}
      onKeyDown={(event) => {
        if (event.target !== event.currentTarget) return;
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          ctx.openLeadDetail(lead);
        }
      }}
      className={`sd-focus group relative cursor-pointer rounded-2xl border p-4 transition-all duration-200 ${cardSurface} ${
        isReservedByOther ? "opacity-65" : ""
      }`}
      aria-label={`${lead.address}, ${lead.city}`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 flex-wrap items-center gap-1.5">
          <SignalBadge tone="accent" icon={CatIcon}>
            {t(category.labelKey)}
          </SignalBadge>

          {lead.signal_type === "legal_obligation" ? (
            <SignalBadge tone="warn" icon={AlertTriangle}>
              {t("dashboard.lead_type.obligation")}
            </SignalBadge>
          ) : lead.signal_type === "authorized_work" ? (
            <SignalBadge tone="info" icon={HardHat}>
              {t("dashboard.lead_type.permit")}
            </SignalBadge>
          ) : (
            <SignalBadge tone="neutral" icon={FolderOpen}>
              {t("dashboard.lead_type.open")}
            </SignalBadge>
          )}

          {isMine ? (
            <SignalBadge tone="success" icon={Lock}>
              {t("dashboard.badge.yours").replace(
                "{time}",
                reservedUntil ? ctx.countdownLabel(reservedUntil) : "1h"
              )}
            </SignalBadge>
          ) : isReservedByOther ? (
            <SignalBadge tone="neutral" icon={Lock}>
              {t("dashboard.status.reserved_by_other") || "Reservado"}
            </SignalBadge>
          ) : isClosed ? (
            <SignalBadge tone="neutral" icon={Clock}>
              {t("dashboard.badge.closed")}
            </SignalBadge>
          ) : null}
        </div>

        <button
          type="button"
          onClick={(event) => ctx.handleToggleFav(lead, event)}
          className={`sd-focus rounded-lg p-1.5 transition ${
            lead.favorited
              ? "text-[var(--sd-warn)]"
              : "text-[var(--sd-faint)] hover:text-[var(--sd-warn)]"
          }`}
          aria-label={t("dashboard.fav.title")}
          title={t("dashboard.fav.title")}
        >
          <Star className={`h-4 w-4 ${lead.favorited ? "fill-current" : ""}`} />
        </button>
      </div>

      <button
        type="button"
        onClick={() => ctx.openLeadDetail(lead)}
        className="sd-focus mt-3 block w-full text-left"
      >
        <h3 className="truncate text-[15px] font-semibold leading-snug text-[var(--sd-text)]">
          {lead.address}
        </h3>
        <p className="mt-1 line-clamp-2 text-xs leading-relaxed text-[var(--sd-muted)]">
          {lead.issue_description ||
            lead.case_title ||
            t("dashboard.feed.address_fallback")}
        </p>
      </button>

      <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-[11px] text-[var(--sd-muted)]">
        <span className="inline-flex items-center gap-1">
          <MapPin className="h-3.5 w-3.5" /> {lead.city}
        </span>
        {owner && OwnerIcon ? (
          <SignalBadge tone={owner.tone} icon={OwnerIcon}>
            {owner.label}
          </SignalBadge>
        ) : null}
        {lead.owner_name ? (
          <span className="max-w-[220px] truncate font-medium text-[var(--sd-text)]">
            {lead.owner_name}
          </span>
        ) : null}
        <span className="inline-flex items-center gap-1">
          <Clock className="h-3.5 w-3.5" />
          {t("dashboard.freshness.reported")}: {ctx.relativeTime(lead.date_reported)}
        </span>
        {lead.phone_confidence === "verified" ? (
          <span className="inline-flex items-center gap-1 text-[var(--sd-success)]">
            <Phone className="h-3.5 w-3.5" />
            {t("dashboard.phone.verified")}
          </span>
        ) : lead.phone_confidence === "high" ? (
          <span className="inline-flex items-center gap-1 text-[var(--sd-info)]">
            <Phone className="h-3.5 w-3.5" />
            {t("dashboard.phone.high")}
            {lead.phone_success_pct != null ? ` · ${lead.phone_success_pct}%` : ""}
          </span>
        ) : null}
        {ctx.shouldShowAddressWarning(lead) ? (
          <span className="inline-flex items-center gap-1 text-[var(--sd-warn)]">
            <AlertTriangle className="h-3 w-3" />
            {t("dashboard.badge.address_unresolvable")}
          </span>
        ) : null}
      </div>

      {isMine ? (
        <>
          {lead.stage ? (
            <div className="mt-3">
              <StageBadge
                stage={lead.stage}
                stageExpiresAt={lead.stage_expires_at}
                serverNow={lead.server_now}
              />
            </div>
          ) : null}
          <div className="mt-3 flex flex-wrap items-center gap-2">
            {lead.owner_phone ? (
              <a
                href={ctx.waHref(lead.owner_phone, messages)}
                target="_blank"
                rel="noopener noreferrer"
                onClick={() => ctx.recordContact(lead.id, "whatsapp")}
                className="sd-focus inline-flex h-8 items-center gap-1.5 rounded-lg bg-[var(--sd-success)]/10 px-3 text-[11px] font-semibold text-[var(--sd-success)]"
              >
                <MessageSquare className="h-3.5 w-3.5" /> {t("dashboard.detail.whatsapp")}
              </a>
            ) : null}
            {lead.owner_phone ? (
              <a
                href={ctx.smsHref(lead.owner_phone, messages)}
                onClick={() => ctx.recordContact(lead.id, "sms")}
                className="sd-focus inline-flex h-8 items-center gap-1.5 rounded-lg bg-[var(--sd-success)]/10 px-3 text-[11px] font-semibold text-[var(--sd-success)]"
              >
                <MessageSquare className="h-3.5 w-3.5" /> {t("dashboard.detail.sms")}
              </a>
            ) : null}
            {lead.owner_email ? (
              <a
                href={`mailto:${lead.owner_email}?subject=${encodeURIComponent(messages.emailSubject)}&body=${encodeURIComponent(messages.emailBody)}`}
                className="sd-focus inline-flex h-8 items-center gap-1.5 rounded-lg bg-[var(--sd-info-soft)] px-3 text-[11px] font-semibold text-[var(--sd-info)]"
              >
                <Mail className="h-3.5 w-3.5" /> {t("dashboard.detail.email")}
              </a>
            ) : null}
            <SignalButton
              type="button"
              variant="secondary"
              size="sm"
              icon={Navigation}
              onClick={() => ctx.openMaps(lead.address)}
            >
              {t("dashboard.action.map")}
            </SignalButton>
            <SignalButton
              type="button"
              variant="ghost"
              size="sm"
              icon={Copy}
              onClick={() => ctx.copyToClipboard(lead.owner_phone || "", "phone")}
            >
              {t("dashboard.detail.copy_phone")}
            </SignalButton>
            <SignalButton
              type="button"
              variant="ghost"
              size="sm"
              icon={RefreshCcw}
              onClick={() => ctx.openReleaseModal(lead)}
              disabled={ctx.busyAction}
            >
              {t("dashboard.action.drop")}
            </SignalButton>
          </div>
          {lead.address ? (
            <div className="mt-3">
              <LeadLocationMap
                address={lead.address}
                city={lead.city}
                compact
                isDark={isDark}
                mapLabel={t("dashboard.action.map") || "Mapa"}
                googleLabel={t("dashboard.map.google") || "Google Maps"}
                appleLabel={t("dashboard.map.apple") || "Apple Maps"}
              />
            </div>
          ) : null}
        </>
      ) : (
        <div className="mt-4 flex flex-wrap items-center gap-2">
          {!isClosed && !isReservedByOther ? (
            <SignalButton
              type="button"
              size="sm"
              icon={Lock}
              onClick={() => ctx.handleQuickReserve(lead)}
              disabled={
                ctx.busyAction ||
                (ctx.subscription && !ctx.subscription.can_access) ||
                ctx.isBlockedByQuota(lead, ctx.dailyStats?.remaining)
              }
            >
              {primaryLabel}
            </SignalButton>
          ) : null}
          {!isMine && lead.owner_name && !lead.owner_phone && !isClosed ? (
            <SignalButton
              type="button"
              variant="secondary"
              size="sm"
              icon={Smartphone}
              onClick={() => ctx.revealPhoneForLead(lead)}
              disabled={
                ctx.busyAction ||
                ctx.phoneRevealing?.loading ||
                ctx.phoneRevealing?.leadId === lead.id
              }
            >
              {t("dashboard.action.reveal_phone")}
            </SignalButton>
          ) : null}
          <SignalButton
            type="button"
            variant="ghost"
            size="sm"
            icon={ArrowUpRight}
            onClick={() => ctx.openLeadDetail(lead)}
          >
            {t("dashboard.feed.view_details") || "Ver detalhes"}
          </SignalButton>
          <span className="ml-auto inline-flex items-center gap-1 text-[10px] text-[var(--sd-faint)]">
            <BadgeCheck className="h-3 w-3" /> {t("dashboard.data_protected")}
          </span>
        </div>
      )}
    </article>
  );
}

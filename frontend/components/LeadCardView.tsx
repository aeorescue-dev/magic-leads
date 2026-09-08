'use client';

import { useState } from "react";
import { Building2, CalendarClock, Copy, Landmark, MapPin, PhoneCall, Star, StickyNote, Tag, Radio } from "lucide-react";
import { LeadResponse, toggleFavorite } from "@/lib/api-client";
import { useI18n } from "@/lib/i18n";
import { StatusBadge } from "./ui/StatusBadge";
import { CategoryBadge } from "./ui/CategoryBadge";
import { ContactModal } from "./ContactModal";
import { NotesPanel } from "./NotesPanel";

interface Props {
  leads: LeadResponse[];
  onLeadUpdated: (lead: LeadResponse) => void;
}

function OccurrenceStatus({ status }: { status?: string }) {
  const s = (status || "").toLowerCase();
  const style =
    s.includes("closed") || s.includes("resolved")
      ? "bg-slate-500/10 text-slate-600 ring-slate-400/30"
      : s.includes("in progress") || s.includes("open") || s.includes("new")
      ? "bg-emerald-500/10 text-emerald-700 ring-emerald-500/30"
      : s.includes("pending")
      ? "bg-amber-500/10 text-amber-700 ring-amber-500/30"
      : "bg-muted text-muted-foreground ring-border";
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ring-1 ${style}`}>
      <Radio className="h-2.5 w-2.5" />
      {status || "—"}
    </span>
  );
}

function InfoRow({ label, value }: { label: React.ReactNode; value?: string | null }) {
  if (!value) return null;
  return (
    <div className="flex items-center justify-between gap-2 text-sm">
      <span className="text-muted-foreground text-xs shrink-0">{label}</span>
      <span className="font-medium text-foreground truncate text-xs">{value}</span>
    </div>
  );
}

export function LeadCardView({ leads, onLeadUpdated }: Props) {
  const { t } = useI18n();
  const [contactLead, setContactLead] = useState<LeadResponse | null>(null);
  const [notesLead, setNotesLead] = useState<LeadResponse | null>(null);

  const handleFavorite = async (lead: LeadResponse) => {
    try {
      onLeadUpdated(await toggleFavorite(lead.id));
    } catch (e) {
      console.error(e);
    }
  };

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
      {leads.map((lead) => (
        <div
          key={lead.id}
          className="card card-hover p-5 group flex flex-col gap-3"
        >
          <div className="flex items-start justify-between gap-2">
            <CategoryBadge category={lead.issue_category} />
            <StatusBadge status={lead.status} />
          </div>

          <div>
            <h3 className="font-semibold leading-snug flex items-start gap-1.5">
              <MapPin className="h-4 w-4 mt-0.5 shrink-0 text-muted-foreground" />
              <span>{lead.address}</span>
            </h3>
            {(lead.issue_description && lead.issue_description !== lead.issue_category) && (
              <p className="text-sm text-muted-foreground mt-1 line-clamp-2">{lead.issue_description}</p>
            )}
          </div>

          {/* Informações da ocorrência / chamado real */}
          <div className="rounded-lg border bg-muted/40 p-3 space-y-1.5">
            <div className="flex items-center justify-between gap-2">
              <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-foreground">
                <Building2 className="h-3.5 w-3.5 text-primary" />
                <span className="truncate">{lead.department || "Departamento não informado"}</span>
              </span>
              <OccurrenceStatus status={lead.case_status} />
            </div>
            {lead.descriptor && (
              <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <Tag className="h-3 w-3 shrink-0" />
                <span className="truncate">{lead.descriptor}</span>
              </div>
            )}
            {(lead.neighborhood || lead.ward || lead.precinct) && (
              <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <Landmark className="h-3 w-3 shrink-0" />
                <span className="truncate">
                  {[lead.neighborhood, lead.ward && lead.ward.replace(/^\d+\s*/, ""), lead.precinct && lead.precinct.replace("Precinct ", "Pct ")]
                    .filter(Boolean)
                    .join(" · ")}
                </span>
              </div>
            )}
            {lead.source && (
              <InfoRow label="Origem" value={lead.source} />
            )}
          </div>

          <div className="text-sm space-y-1 mt-auto">
            <div className="flex items-center justify-between">
              <span className="text-muted-foreground text-xs">{t("db.col.owner")}</span>
              <span className="font-medium truncate">{lead.owner_name || "—"}</span>
            </div>
            {lead.owner_phone && (
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground text-xs">{t("db.col.phone")}</span>
                <span className="font-mono text-xs">{lead.owner_phone}</span>
              </div>
            )}
            <div className="flex items-center justify-between">
              <span className="text-muted-foreground text-xs">{t("db.col.date")}</span>
              <span className="text-xs" suppressHydrationWarning>{new Date(lead.date_reported).toLocaleDateString("pt-BR")}</span>
            </div>
          </div>

          <div className="flex items-center gap-1.5 pt-3 border-t opacity-70 group-hover:opacity-100 transition-opacity">
            <button
              onClick={() => handleFavorite(lead)}
              className={`rounded-lg p-2 hover:bg-secondary transition-colors ${lead.favorited ? "text-amber-500" : "text-muted-foreground hover:text-amber-500"}`}
              title={lead.favorited ? t("db.unfavorite") : t("db.favorite")}
            >
              <Star className={`h-4 w-4 ${lead.favorited ? "fill-amber-400" : ""}`} />
            </button>
            <button
              onClick={() => setNotesLead(lead)}
              className="rounded-lg p-2 text-muted-foreground hover:bg-secondary hover:text-foreground transition-colors"
              title={t("db.notes")}
            >
              <StickyNote className="h-4 w-4" />
            </button>
            {lead.owner_phone && (
              <button
                onClick={() => navigator.clipboard.writeText(lead.owner_phone!)}
                className="rounded-lg p-2 text-muted-foreground hover:bg-secondary hover:text-foreground transition-colors"
                title={t("db.copy")}
              >
                <Copy className="h-4 w-4" />
              </button>
            )}
            <button
              onClick={() => setContactLead(lead)}
              className="ml-auto inline-flex items-center gap-1.5 rounded-lg bg-primary px-3 py-2 text-xs font-medium text-primary-foreground hover:bg-primary/90 transition-colors"
            >
              <PhoneCall className="h-3.5 w-3.5" />
              {t("db.contact")}
            </button>
          </div>
        </div>
      ))}

      {contactLead && (
        <ContactModal
          lead={contactLead}
          onClose={() => setContactLead(null)}
          onContacted={(l) => { onLeadUpdated(l); setContactLead(null); }}
        />
      )}
      {notesLead && <NotesPanel lead={notesLead} onClose={() => setNotesLead(null)} />}
    </div>
  );
}

'use client';

import { Fragment, memo, useState } from "react";
import {
  CheckCircle2, ChevronRight, Copy, PhoneCall, Star, StickyNote, X,
} from "lucide-react";
import { ContactModal } from "./ContactModal";
import { NotesPanel } from "./NotesPanel";
import { LeadResponse, toggleFavorite, updateOwnerPhone } from "@/lib/api-client";
import { useI18n } from "@/lib/i18n";
import { StatusBadge } from "./ui/StatusBadge";
import { CategoryBadge } from "./ui/CategoryBadge";

interface LeadsTableProps {
  leads: LeadResponse[];
  onLeadUpdated: (lead: LeadResponse) => void;
  onEmpty?: () => void;
}

const OwnerCell = memo(function OwnerCell({
  lead,
  onPhoneSave,
}: {
  lead: LeadResponse;
  onPhoneSave: (id: string, phone: string) => void;
}) {
  const { t } = useI18n();
  const [editing, setEditing] = useState(false);
  const [phone, setPhone] = useState("");

  if (editing) {
    return (
      <div className="flex items-center gap-1.5">
        <input
          type="tel"
          autoFocus
          value={phone}
          onChange={(e) => setPhone(e.target.value)}
          placeholder={t("db.phone_placeholder")}
          onKeyDown={(e) => e.key === "Enter" && phone && onPhoneSave(lead.id, phone) && setEditing(false)}
          className="w-32 rounded-md border bg-background px-2 py-1 text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        />
        <button onClick={() => { if (phone) { onPhoneSave(lead.id, phone); setEditing(false); } }} className="text-primary hover:text-primary/80">
          <CheckCircle2 className="h-4 w-4" />
        </button>
        <button onClick={() => setEditing(false)} className="text-muted-foreground hover:text-foreground">
          <X className="h-4 w-4" />
        </button>
      </div>
    );
  }

  if (lead.owner_phone) {
    return (
      <span className="inline-flex items-center gap-1 font-mono text-sm">
        {lead.owner_phone}
        <Copy className="h-3 w-3 text-muted-foreground cursor-pointer hover:text-primary" />
      </span>
    );
  }

  return (
    <button
      onClick={() => setEditing(true)}
      className="text-xs text-muted-foreground hover:text-primary underline decoration-dotted underline-offset-2"
    >
      + {t("db.add_phone")}
    </button>
  );
});

function LeadDetails({ lead }: { lead: LeadResponse }) {
  const rows: Array<[string, string | null | undefined]> = [
    ["Case Title", lead.case_title],
    ["Subject", lead.subject],
    ["Reason", lead.reason],
    ["Type", lead.type],
    ["Queue", lead.queue],
    ["Department", lead.department],
    ["Closure Reason", lead.closure_reason],
    ["Case Status", lead.case_status],
    ["On Time", lead.on_time],
    ["SLA Target", lead.sla_target_dt],
    ["Closed", lead.closed_dt],
    ["Source", lead.source],
    ["Neighborhood", lead.neighborhood],
    ["Ward", lead.ward],
    ["Precinct", lead.precinct],
    ["Descriptor", lead.descriptor],
    ["Resolution", lead.resolution_description],
    ["Resolution Updated", lead.resolution_action_updated_date],
    ["Submitted Photo", lead.submitted_photo],
    ["Closed Photo", lead.closed_photo],
  ];
  const visible = rows.filter(([, v]) => v);
  if (visible.length === 0) return null;
  return (
    <div className="grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-3 md:grid-cols-4">
      {visible.map(([label, value]) => (
        <div key={label} className="flex flex-col">
          <span className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</span>
          <span className="text-sm text-foreground break-words">{value}</span>
        </div>
      ))}
    </div>
  );
}

export function LeadsTable({ leads, onLeadUpdated }: LeadsTableProps) {
  const { t } = useI18n();
  const [selectedLead, setSelectedLead] = useState<LeadResponse | null>(null);
  const [notesLead, setNotesLead] = useState<LeadResponse | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);

  const handleFavorite = async (lead: LeadResponse) => {
    try {
      const updated = await toggleFavorite(lead.id);
      onLeadUpdated(updated);
    } catch (e) {
      console.error(e);
    }
  };

  const handlePhoneSave = (id: string, phone: string) => {
    updateOwnerPhone(id, phone).then((updated) => onLeadUpdated(updated));
  };

  const toggleRow = (id: string) => setExpanded((cur) => (cur === id ? null : id));

  return (
    <div className="space-y-4">
      <div className="overflow-hidden rounded-xl border">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b bg-muted/50 text-left">
                {[
                  t("db.col.address"),
                  t("db.col.problem"),
                  t("db.col.owner"),
                  t("db.col.phone"),
                  t("db.col.date"),
                  t("db.col.status"),
                  t("db.col.actions"),
                ].map((h) => (
                  <th key={h} className="px-4 py-3 text-xs font-semibold text-muted-foreground uppercase tracking-wide">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {leads.map((lead) => (
                <Fragment key={lead.id}>
                  <tr
                    className={`group border-b transition-colors cursor-pointer hover:bg-accent/40 ${
                      expanded === lead.id ? "bg-accent/60" : ""
                    }`}
                  >
                    <td className="px-4 py-3" onClick={() => toggleRow(lead.id)}>
                      <div className="font-medium flex items-center gap-2">
                        <ChevronRight
                          className={`h-4 w-4 text-muted-foreground transition-transform ${
                            expanded === lead.id ? "rotate-90" : ""
                          }`}
                        />
                        {lead.favorited && <Star className="h-3.5 w-3.5 fill-amber-400 text-amber-400" />}
                        <span>{lead.address}</span>
                      </div>
                      <div className="text-xs text-muted-foreground mt-0.5 pl-6">{lead.city}</div>
                    </td>
                    <td className="px-4 py-3" onClick={() => toggleRow(lead.id)}>
                      <CategoryBadge category={lead.issue_category} />
                    </td>
                    <td className="px-4 py-3 text-sm">{lead.owner_name || "—"}</td>
                    <td className="px-4 py-3">
                      <OwnerCell lead={lead} onPhoneSave={handlePhoneSave} />
                    </td>
                    <td className="px-4 py-3 text-sm text-muted-foreground" onClick={() => toggleRow(lead.id)} suppressHydrationWarning>
                      <div>{new Date(lead.date_reported).toLocaleDateString("pt-BR")}</div>
                      {lead.last_synced && (
                        <div className="text-[10px] mt-0.5 opacity-70">
                          {t("dashboard.freshness.synced")}: {new Date(lead.last_synced).toLocaleDateString("pt-BR")}
                        </div>
                      )}
                    </td>
                    <td className="px-4 py-3" onClick={() => toggleRow(lead.id)}>
                      <StatusBadge status={lead.status} />
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-0.5 opacity-70 group-hover:opacity-100 transition-opacity">
                        <button
                          onClick={() => handleFavorite(lead)}
                          className={`rounded-lg p-1.5 hover:bg-secondary transition-colors ${
                            lead.favorited ? "text-amber-500" : "text-muted-foreground hover:text-amber-500"
                          }`}
                          title={lead.favorited ? t("db.unfavorite") : t("db.favorite")}
                        >
                          <Star className={`h-4 w-4 ${lead.favorited ? "fill-amber-400" : ""}`} />
                        </button>
                        <button
                          onClick={() => setNotesLead(lead)}
                          className="rounded-lg p-1.5 text-muted-foreground hover:bg-secondary hover:text-foreground transition-colors"
                          title={t("db.notes")}
                        >
                          <StickyNote className="h-4 w-4" />
                        </button>
                        <button
                          onClick={() => setSelectedLead(lead)}
                          className="rounded-lg p-1.5 text-muted-foreground hover:bg-secondary hover:text-primary transition-colors"
                          title={t("db.contact")}
                        >
                          <PhoneCall className="h-4 w-4" />
                        </button>
                      </div>
                    </td>
                  </tr>
                  {expanded === lead.id && (
                    <tr className="border-b bg-muted/30 animate-fade-in">
                      <td colSpan={7} className="px-4 py-4">
                        <LeadDetails lead={lead} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {selectedLead && (
        <ContactModal
          lead={selectedLead}
          onClose={() => setSelectedLead(null)}
          onContacted={(l) => {
            onLeadUpdated(l);
            setSelectedLead(null);
          }}
        />
      )}
      {notesLead && <NotesPanel lead={notesLead} onClose={() => setNotesLead(null)} />}
    </div>
  );
}

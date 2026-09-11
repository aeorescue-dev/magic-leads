'use client';

import { useState } from "react";
import { X, Copy, PhoneCall, MessageSquare, Mail, Phone } from "lucide-react";
import { LeadResponse, recordContact } from "@/lib/api-client";
import { useAuth } from "@/lib/auth";
import { useI18n } from "@/lib/i18n";
import { buildOutreachMessage, OutreachMessage } from "@/lib/outreach";

interface ContactModalProps {
  lead: LeadResponse;
  onClose: () => void;
  onContacted?: (lead: LeadResponse) => void;
}

const CHANNEL_ICONS = { whatsapp: MessageSquare, sms: MessageSquare, call: Phone, email: Mail } as const;

export function ContactModal({ lead, onClose, onContacted }: ContactModalProps) {
  const { t } = useI18n();
  const { user } = useAuth();
  const [channel, setChannel] = useState<"whatsapp" | "sms" | "call" | "email">("whatsapp");
  const [sent, setSent] = useState(false);

  const msgs = buildOutreachMessage({
    owner: lead.owner_name || "—",
    company: user?.company_name || "—",
    city: lead.city || "",
    category: lead.issue_category || "Other",
  });

  const textFor = (c: typeof channel, m: OutreachMessage): string => {
    if (c === "sms") return m.sms;
    if (c === "email") return `${m.emailSubject}\n\n${m.emailBody}`;
    return m.whatsapp;
  };

  const message = textFor(channel, msgs);

  const linkFor = (c: typeof channel): string => {
    const phone = (lead.owner_phone || "").replace(/\D/g, "");
    switch (c) {
      case "whatsapp": return `https://wa.me/${phone}?text=${encodeURIComponent(msgs.whatsapp)}`;
      case "sms": return `sms:${phone}?body=${encodeURIComponent(msgs.sms)}`;
      case "call": return `tel:${phone}`;
      case "email":
        return `mailto:${lead.owner_email || ""}?subject=${encodeURIComponent(msgs.emailSubject)}&body=${encodeURIComponent(msgs.emailBody)}`;
    }
  };

  const handleGo = () => {
    const href = linkFor(channel);
    try {
      recordContact(lead.id, channel);
      onContacted?.(lead);
    } catch {
      /* não bloqueia */
    }
    if (channel === "whatsapp" || channel === "email") window.open(href, "_blank");
    else window.location.href = href;
    setSent(true);
  };

  const channels: { key: typeof channel; label: string }[] = [
    { key: "whatsapp", label: "WhatsApp" },
    { key: "sms", label: t("db.contact.sms") },
    { key: "call", label: t("db.contact.call") },
    { key: "email", label: t("db.contact.email") },
  ];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm" onClick={onClose}>
      <div
        className="card w-full max-w-md p-6 animate-scale-in shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex justify-between items-start mb-5">
          <div>
            <h2 className="text-lg font-bold">{t("db.contact")}</h2>
            <p className="text-sm text-muted-foreground mt-0.5">
              {lead.owner_name || "—"} · <span className="font-mono">{lead.owner_phone || "—"}</span>
            </p>
          </div>
          <button onClick={onClose} className="rounded-lg p-1.5 text-muted-foreground hover:bg-secondary transition-colors">
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="grid grid-cols-4 gap-2 mb-5">
          {channels.map((c) => {
            const Icon = CHANNEL_ICONS[c.key];
            return (
              <button
                key={c.key}
                onClick={() => { setChannel(c.key); setSent(false); }}
                className={`flex flex-col items-center gap-1 rounded-xl border py-2.5 text-xs font-medium transition ${
                  channel === c.key
                    ? "bg-primary text-primary-foreground border-primary"
                    : "bg-background text-muted-foreground border-border hover:bg-secondary"
                }`}
              >
                <Icon className="h-4 w-4" />
                {c.label}
              </button>
            );
          })}
        </div>

        <div className="rounded-xl bg-muted p-4 mb-4">
          <p className="text-xs text-muted-foreground uppercase tracking-wide mb-2">{t("price.f3")}</p>
          <p className="text-sm">{message}</p>
        </div>

        <div className="flex gap-3">
          <button
            onClick={handleGo}
            className="inline-flex flex-1 items-center justify-center gap-2 rounded-lg bg-primary hover:bg-primary/90 text-primary-foreground py-2.5 font-medium transition"
          >
            <PhoneCall className="h-4 w-4" />
            {channel === "call" ? t("db.contact.call") : t("db.contact")}
          </button>
          <button
            onClick={() => navigator.clipboard.writeText(message)}
            className="inline-flex flex-1 items-center justify-center gap-2 rounded-lg border hover:bg-secondary py-2.5 font-medium transition"
          >
            <Copy className="h-4 w-4" />
            {t("db.copy")}
          </button>
        </div>

        {sent && (
          <p className="text-sm text-emerald-600 mt-3 text-center font-medium">
            {t("db.contacted")}! {t("db.sms.body")}
          </p>
        )}
      </div>
    </div>
  );
}

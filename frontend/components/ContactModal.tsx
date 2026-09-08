'use client';

import { useState } from "react";
import { X, Copy, PhoneCall, MessageSquare, Mail, Phone } from "lucide-react";
import { LeadResponse, recordContact } from "@/lib/api-client";
import { useI18n, Lang } from "@/lib/i18n";

interface ContactModalProps {
  lead: LeadResponse;
  onClose: () => void;
  onContacted?: (lead: LeadResponse) => void;
}

const MSG_TEMPLATES: Record<Lang, (owner: string, address: string) => string> = {
  pt: (owner, address) =>
    `Oi ${owner}! Tudo bem? Vi que você reportou um problema no imóvel em ${address}. Sou profissional em reformas e posso ajudar. Qual o melhor horário para falarmos?`,
  en: (owner, address) =>
    `Hi ${owner}! Hope you're well. I saw the issue you reported at ${address}. I'm a licensed contractor and can help. What's the best time to talk?`,
  es: (owner, address) =>
    `¡Hola ${owner}! ¿Cómo estás? Vi que reportaste un problema en la propiedad en ${address}. Soy contratista y puedo ayudarte. ¿Cuál es el mejor horario para hablar?`,
};

const CHANNEL_ICONS = { whatsapp: MessageSquare, sms: MessageSquare, call: Phone, email: Mail } as const;

export function ContactModal({ lead, onClose, onContacted }: ContactModalProps) {
  const { t, lang } = useI18n();
  const [channel, setChannel] = useState<"whatsapp" | "sms" | "call" | "email">("whatsapp");
  const [sent, setSent] = useState(false);

  const owner = lead.owner_name || "proprietário";
  const message = MSG_TEMPLATES[lang](owner, lead.address);

  const linkFor = (c: typeof channel): string => {
    const phone = (lead.owner_phone || "").replace(/\D/g, "");
    const url = encodeURIComponent(message);
    switch (c) {
      case "whatsapp": return `https://wa.me/${phone}?text=${url}`;
      case "sms": return `sms:${phone}?body=${url}`;
      case "call": return `tel:${phone}`;
      case "email": return `mailto:?subject=${encodeURIComponent("Orçamento de reforma")}&body=${url}`;
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

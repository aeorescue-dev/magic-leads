'use client';

import { useEffect, useState } from "react";
import { MapPin, Building2, TrendingUp, Clock, AlertCircle, CheckCircle2, Shield, Radio, Wifi, ExternalLink, Smartphone, Home, Wrench, Trees, PaintBucket, Sparkles, MessageSquare, Navigation, Lock } from "lucide-react";
import { useI18n } from "@/lib/i18n";
import { DemoLoginButton } from "@/components/DemoLoginButton";
import { LeadResponse } from "@/lib/api-client";
import { maskAddress } from "@/lib/mask";

const API_BASE = (process.env.NEXT_PUBLIC_API_URL || "").replace(/\/$/, "");

function getLocationTag(city: string): string {
  const normalized = city.toLowerCase().trim();
  if (normalized === "nyc" || normalized === "new york" || normalized === "new york city") return "NEW YORK, NY";
  if (normalized === "boston") return "BOSTON, MA";
  if (normalized === "dallas" || normalized === "dallasopendata") return "DALLAS, TX";
  if (normalized === "norfolk") return "NORFOLK, VA";
  return city.toUpperCase();
}

function isSanitationLead(lead: LeadResponse): boolean {
  const desc = (lead.issue_description || "").toLowerCase();
  const title = (lead.case_title || "").toLowerCase();
  const dept = (lead.department || "").toLowerCase();
  const sanitationKeywords = ["sanitation", "missed garbage", "garbage", "trash", "litter", "debris", "spillage", "street cleaning", "street sweeping"];
  return sanitationKeywords.some(kw => desc.includes(kw) || title.includes(kw) || dept.includes(kw));
}

function getUrgencyConfig(lead: LeadResponse) {
  const category = lead.issue_category?.toLowerCase() || "";
  const hoursAgo = Math.floor((Date.now() - new Date(lead.date_reported).getTime()) / (1000 * 60 * 60));
  if (category === "structure" || category === "plumbing" || hoursAgo < 2) return { level: "high", label: "URGENTE", icon: AlertCircle, color: "red", bg: "bg-red-500/15", border: "border-red-500/30", text: "text-red-400" };
  if (category === "roof" || hoursAgo < 6) return { level: "medium", label: "ALTA", icon: TrendingUp, color: "amber", bg: "bg-amber-500/15", border: "border-amber-500/30", text: "text-amber-400" };
  return { level: "low", label: "NORMAL", icon: Clock, color: "slate", bg: "bg-slate-500/15", border: "border-slate-500/30", text: "text-slate-400" };
}

const getOwnerStatus = (lead: LeadResponse) => {
  if (lead.owner_name && lead.owner_phone) return { label: "COMPLETO", bg: "bg-emerald-500/15", border: "border-emerald-500/30", text: "text-emerald-400", icon: CheckCircle2 };
  if (lead.owner_name) return { label: "IDENTIFICADO", bg: "bg-amber-500/15", border: "border-amber-500/30", text: "text-amber-400", icon: Shield };
  return { label: "ENRIQUECENDO", bg: "bg-slate-500/15", border: "border-slate-500/30", text: "text-slate-400", icon: Radio };
};

const categoryIcons: Record<string, any> = { roof: Home, plumbing: Wrench, grass: Trees, structure: Building2, paint: PaintBucket };
const defaultCategoryIcon = Sparkles;
const categoryKeys: Record<string, string> = { roof: "live.cat.roof", plumbing: "live.cat.plumbing", grass: "live.cat.grass", structure: "live.cat.structure", paint: "live.cat.paint" };

export function LiveLeadsSection() {
  const { t } = useI18n();
  const [recentLeads, setRecentLeads] = useState<LeadResponse[]>([]);

  // Handlers mockup para página pública (redirecionam para login)
  const showLoginPrompt = (feature: string) => {
    alert(`${feature} disponível apenas para assinantes. Faça login no dashboard para acessar.`);
  };

  const handleMapsClick = () => showLoginPrompt("Mapas e rota");
  const handleSMSClick = () => showLoginPrompt("Envio de SMS");
  const handleWhatsAppClick = () => showLoginPrompt("WhatsApp");

  useEffect(() => {
    fetch(`${API_BASE}/api/leads/recent?limit=20`)
      .then((r) => r.json())
      .then((data) => {
        const leads = data.leads || [];
        const filtered = leads.filter((lead: LeadResponse) => !isSanitationLead(lead));
        setRecentLeads(filtered);
      })
      .catch(() => setRecentLeads([]));
  }, []);

  if (recentLeads.length === 0) {
    // Example leads for empty state (masked for privacy)
    const exampleLeads = [
      { city: "NEW YORK, NY", category: "Telhado", urgency: "URGENTE", address: "•••• Broadway, NYC", time: "Há 3 min" },
      { city: "BOSTON, MA", category: "Encanamento", urgency: "ALTA", address: "•••• Oak St, Boston", time: "Há 12 min" },
      { city: "DALLAS, TX", category: "Mato Alto", urgency: "NORMAL", address: "•••• Elm Ave, Dallas", time: "Há 42 min" },
    ];

    return (
      <section className="section bg-slate-950/50" aria-labelledby="live-title">
        <div className="container-custom text-center">
          <div className="flex items-center gap-2 justify-center mb-2">
            <div className="relative flex h-2.5 w-2.5">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
              <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-emerald-500" />
            </div>
            <h2 id="live-title" className="section-title">{t("live.title")}</h2>
          </div>
          <p className="section-subtitle">{t("live.sub")}</p>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 max-w-xl mx-auto">
            {exampleLeads.map((lead, idx) => (
              <div key={idx} className="card p-6 text-center">
                <MapPin className="h-8 w-8 mx-auto text-emerald-400 mb-3" />
                <h3 className="font-bold text-lg">{lead.city}</h3>
                <div className="mt-2 space-y-1">
                  <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-[11px] font-semibold uppercase tracking-wider bg-red-500/20 text-red-400 border border-red-500/20">
                    {lead.urgency}
                  </span>
                  <p className="text-sm text-slate-400 mt-1">{lead.address}</p>
                  <p className="text-xs text-slate-500 mt-1">{lead.time}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>
    );
  }

  return (
    <section className="section bg-slate-950/50" aria-labelledby="live-title">
      <div className="container-custom">
        <div className="flex items-center gap-2 justify-center mb-2">
          <div className="relative flex h-2.5 w-2.5">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
            <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-emerald-500" />
            <Wifi className="absolute inset-0 h-2.5 w-2.5 text-emerald-400 animate-spin-slow" />
          </div>
          <h2 id="live-title" className="section-title">{t("live.title")}</h2>
        </div>
        <p className="section-subtitle">{t("live.sub")}</p>

        <div className="flex flex-wrap items-center justify-center gap-6 mb-10">
          <div className="flex items-center gap-2 px-4 py-2 rounded-xl bg-slate-800/50 border border-slate-700/50 backdrop-blur-sm">
            <div className="w-2 h-2 bg-emerald-400 rounded-full animate-pulse" />
            <span className="text-xs font-semibold text-emerald-400 uppercase tracking-wider">{t("live.stats.live")}</span>
          </div>
          <div className="flex items-center gap-2 px-4 py-2 rounded-xl bg-slate-800/50 border border-slate-700/50 backdrop-blur-sm">
            <Radio className="h-4 w-4 text-emerald-400" />
            <span className="text-sm font-medium text-slate-300">{recentLeads.length} {t("live.stats.active")}</span>
          </div>
          <div className="flex items-center gap-2 px-4 py-2 rounded-xl bg-slate-800/50 border border-slate-700/50 backdrop-blur-sm">
            <TrendingUp className="h-4 w-4 text-emerald-400" />
            <span className="text-sm font-medium text-slate-300" suppressHydrationWarning>{t("live.stats.updated")} {new Date().toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}</span>
          </div>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {recentLeads.slice(0, 9).map((lead) => {
            const urgency = getUrgencyConfig(lead);
            const ownerStatus = getOwnerStatus(lead);
            const locationTag = getLocationTag(lead.city);
            const catKey = (lead.issue_category || "").toLowerCase();
            const CategoryIcon = categoryIcons[catKey] || defaultCategoryIcon;
            const catLabel = t(categoryKeys[catKey] || "live.cat.other");
            const UrgencyIcon = urgency.icon;

            return (
              <article key={lead.id} className="card card-hover group relative overflow-hidden">
                {urgency.level === "high" && <div className="absolute inset-0 border-2 border-red-500/50 rounded-2xl animate-pulse-slow pointer-events-none" />}
                <div className="absolute top-3 right-3 z-10">
                  <div className={`w-2 h-2 rounded-full animate-pulse ${urgency.level === "high" ? "bg-red-400" : urgency.level === "medium" ? "bg-amber-400" : "bg-emerald-400"}`} />
                </div>

                <div className="p-5 space-y-4 relative z-10">
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex items-center gap-2">
                      <MapPin className="h-4 w-4 text-emerald-400" />
                      <span className="px-3 py-1 rounded-full text-[11px] font-semibold uppercase tracking-wider bg-emerald-500/15 text-emerald-400 border border-emerald-500/20">{locationTag}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <UrgencyIcon className={`h-4 w-4 ${urgency.text}`} />
                      <span className={`px-2.5 py-1 rounded-full text-[10px] font-bold uppercase tracking-wider ${urgency.bg} ${urgency.border} ${urgency.text}`}>{urgency.label}</span>
                    </div>
                  </div>

                  <div className="space-y-3">
                    <div className="flex items-start gap-3">
                      <div className="w-14 h-14 rounded-xl bg-gradient-to-br from-emerald-500/20 to-cyan-500/20 flex items-center justify-center flex-shrink-0">
                        <CategoryIcon className="h-6 w-6 text-emerald-400" />
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="font-semibold text-white truncate">{maskAddress(lead.address, true)}</p>
                        <p className="text-xs text-slate-400 truncate mt-1">{lead.case_title || lead.department || lead.issue_description || "\u2014"}</p>
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="px-3 py-1 rounded-full text-xs font-bold uppercase tracking-wider bg-emerald-500/15 text-emerald-400 border border-emerald-500/20">{catLabel}</span>
                    </div>
                  </div>

                  <div className="pt-2 border-t border-slate-800/50 space-y-3">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <ownerStatus.icon className={`h-4 w-4 ${ownerStatus.text}`} />
                        <span className={`px-2.5 py-1 rounded-full text-[10px] font-medium uppercase tracking-wider ${ownerStatus.bg} ${ownerStatus.border} ${ownerStatus.text}`}>{ownerStatus.label}</span>
                      </div>
                      <time className="text-[11px] text-slate-500" dateTime={lead.date_reported} suppressHydrationWarning>{new Date(lead.date_reported).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}</time>
                    </div>
                    <div className="flex items-center gap-2">
                      <button
                        onClick={handleSMSClick}
                        className="flex-1 group btn-primary text-sm py-2.5 flex items-center justify-center gap-2"
                      >
                        <Smartphone className="h-4 w-4 group-hover:scale-110 transition-transform" />
                        <span>{t("live.cta.send_sms")}</span>
                      </button>
                      <button
                        onClick={handleWhatsAppClick}
                        className="flex-1 group btn-primary text-sm py-2.5 flex items-center justify-center gap-2 bg-green-600 hover:bg-green-700 border-green-600"
                      >
                        <MessageSquare className="h-4 w-4 group-hover:scale-110 transition-transform" />
                        <span className="hidden sm:inline">WhatsApp</span>
                      </button>
                      <button
                        onClick={handleMapsClick}
                        className="btn-secondary px-4 py-2.5 flex items-center justify-center gap-2"
                      >
                        <Navigation className="h-4 w-4" />
                        <span className="hidden sm:inline">{t("live.cta.view_map")}</span>
                      </button>
                    </div>
                  </div>
                </div>
              </article>
            );
          })}
        </div>

        <div className="text-center mt-10">
          <DemoLoginButton>{t("live.cta")}</DemoLoginButton>
        </div>
      </div>
    </section>
  );
}
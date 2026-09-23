'use client';

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { Bell, Building2, MapPin, Radio } from "lucide-react";
import { useI18n } from "@/lib/i18n";
import { LeadResponse, fetchTodayLeads } from "@/lib/api-client";

export function NotificationCenter() {
  const { lang, t } = useI18n();
  const router = useRouter();
  const [leads, setLeads] = useState<LeadResponse[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);

  const localePath = (href: string) => `/${lang}${href}`;

  const load = async () => {
    setLoading(true);
    try {
      const data = await fetchTodayLeads(20);
      setLeads(data.leads || []);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const status = (s?: string) => {
    const v = (s || "").toLowerCase();
    if (v.includes("closed") || v.includes("resolved")) return "bg-slate-500/10 text-slate-600";
    if (v.includes("in progress") || v.includes("open") || v.includes("new")) return "bg-emerald-500/10 text-emerald-700";
    if (v.includes("pending")) return "bg-amber-500/10 text-amber-700";
    return "bg-muted text-muted-foreground";
  };

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(!open)}
        className={`relative p-2 rounded-lg transition ${open ? "bg-primary/10" : "hover:bg-secondary"}`}
        aria-label={t("notifications.title")}
      >
        <Bell className="h-5 w-5 text-muted-foreground" />
        {leads.length > 0 && (
          <span className="absolute -top-0.5 -right-0.5 flex h-4 w-4 items-center justify-center rounded-full bg-primary text-[9px] font-bold text-primary-foreground">
            {leads.length}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-2 w-80 md:w-96 bg-popover border rounded-xl shadow-2xl z-[100] overflow-hidden">
          <div className="flex items-center justify-between px-4 py-3 border-b bg-muted/40">
            <h3 className="font-semibold text-foreground text-sm">{t("notifications.recent_title") || "Ocorrências recentes"}</h3>
            <button onClick={() => setOpen(false)} className="text-muted-foreground hover:text-foreground">✕</button>
          </div>

          <div className="max-h-96 overflow-y-auto divide-y">
            {loading ? (
              <div className="px-4 py-8 text-center text-muted-foreground text-sm">{t("notifications.loading") || "Carregando…"}</div>
            ) : leads.length === 0 ? (
              <div className="px-4 py-8 text-center text-muted-foreground text-sm">{t("notifications.empty_real") || "Sem ocorrências reais."}</div>
            ) : (
              leads.map((lead) => (
                <button
                  key={lead.id}
                  onClick={() => { setOpen(false); router.push(localePath("/dashboard")); }}
                  className="w-full text-left px-4 py-3 hover:bg-muted/40 transition"
                >
                  <div className="flex items-start gap-3">
                    <MapPin className="h-4 w-4 mt-0.5 shrink-0 text-primary" />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-xs font-semibold text-muted-foreground capitalize">{lead.city}</span>
                        <span className={`text-[10px] font-semibold rounded-full px-2 py-0.5 uppercase ${status(lead.case_status)}`}>
                          {lead.case_status || "—"}
                        </span>
                      </div>
                      <p className="font-medium text-sm text-foreground truncate">{lead.address}</p>
                      <div className="flex items-center gap-1.5 text-xs text-muted-foreground mt-0.5">
                        <Building2 className="h-3 w-3 shrink-0" />
                        <span className="truncate">{lead.department || lead.case_title || lead.issue_description || "—"}</span>
                      </div>
                      <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground mt-0.5 capitalize">
                        <Radio className="h-3 w-3 shrink-0" />
                        {lead.issue_category?.toLowerCase()}
                      </div>
                    </div>
                  </div>
                </button>
              ))
            )}
          </div>

          <div className="px-4 py-3 border-t bg-muted/40">
            <button
              onClick={() => { setOpen(false); router.push(localePath("/dashboard/notifications")); }}
              className="text-sm font-medium text-primary hover:underline"
            >
              {t("notifications.view_today") || "Ver todas as demandas do dia →"}
            </button>
          </div>
        </div>
      )}

      {open && <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} aria-hidden="true" />}
    </div>
  );
}
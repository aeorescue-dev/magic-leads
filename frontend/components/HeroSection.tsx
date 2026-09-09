'use client';

import { useEffect, useState } from "react";
import { ArrowRight, CheckCircle2, Shield, Zap, Users, TrendingUp, Sparkles, Target, Radio, Smartphone, Globe, CheckCircle, Radio as RadioIcon } from "lucide-react";
import { useI18n } from "@/lib/i18n";
import { DemoLoginButton } from "@/components/DemoLoginButton";
import { useStats } from "@/lib/hooks/useStats";
import { fetchDashboardSummary, fetchScraperStatus } from "@/lib/api-client";

function formatUpdatedSince(dateStr: string, t: (k: string) => string): string {
  const iso = dateStr.replace(" ", "T");
  const withZ = /[Zz]|[+-]\d{2}:?\d{2}$/.test(iso) ? iso : iso + "Z";
  const d = new Date(withZ);
  if (isNaN(d.getTime())) return "";
  const diffMin = Math.max(0, Math.floor((Date.now() - d.getTime()) / 60000));
  return diffMin < 1 ? t("hero.live.just_now") : `${diffMin} ${t("hero.live.min")}`;
}

export function HeroSection() {
  const { t } = useI18n();
  const { stats } = useStats();
  const [new24h, setNew24h] = useState<number | null>(null);
  const [lastUpdate, setLastUpdate] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    const refresh = async () => {
      try {
        const [s, st] = await Promise.all([
          fetchDashboardSummary().catch(() => null),
          fetchScraperStatus().catch(() => null),
        ]);
        if (!active) return;
        if (s && typeof s.new_24h === "number") setNew24h(s.new_24h);
        if (st?.last_run?.finished_at) setLastUpdate(st.last_run.finished_at);
      } catch { /* ignore */ }
    };
    refresh();
    const id = setInterval(refresh, 5 * 60 * 1000);
    return () => { active = false; clearInterval(id); };
  }, []);

  const fmt = (n?: number) => (n !== undefined ? `${n.toLocaleString("en-US")}+` : "…");
  const fmtCities = (n?: number) => (n !== undefined ? `${n}+` : "…");

  return (
    <section className="relative overflow-hidden min-h-screen flex items-center bg-gradient-to-b from-slate-950 via-slate-900 to-slate-950">
      {/* Background Effects */}
      <div className="absolute inset-0 overflow-hidden pointer-events-none">
        {/* Radial gradients */}
        <div className="absolute top-1/4 left-1/4 w-[600px] h-[600px] bg-emerald-500/10 rounded-full blur-3xl animate-pulse-slow" />
        <div className="absolute bottom-1/4 right-1/4 w-[600px] h-[600px] bg-cyan-500/10 rounded-full blur-3xl animate-pulse-slow delay-1000" />
        <div className="absolute top-1/2 left-1/2 w-[400px] h-[400px] bg-emerald-500/5 rounded-full blur-3xl animate-pulse-slow delay-500" />
        
        {/* Grid pattern */}
        <div className="absolute inset-0 opacity-5" style={{ 
          backgroundImage: "radial-gradient(circle at 1px 1px, rgba(255,255,255,0.1) 1px, transparent 0)",
          backgroundSize: "40px 40px"
        }} />
        
        {/* Floating orbs */}
        <div className="absolute top-20 left-10 w-32 h-32 bg-emerald-500/10 rounded-full blur-3xl animate-float" />
        <div className="absolute bottom-20 right-10 w-24 h-24 bg-cyan-500/10 rounded-full blur-3xl animate-float delay-500" />
        <div className="absolute top-1/3 right-20 w-16 h-16 bg-emerald-500/5 rounded-full blur-3xl animate-float delay-1000" />
      </div>

      <div className="container-custom relative py-20 md:py-28 lg:py-32">
        <div className="grid lg:grid-cols-2 gap-12 lg:gap-16 items-center">
          {/* LEFT COLUMN - Copy & CTA */}
          <div className="lg:order-2 relative z-10 animate-fade-in-up delay-100">
            {/* Live Status Badge */}
            <div className="inline-flex flex-col items-start gap-2 mb-6 animate-fade-in">
              <div className="inline-flex items-center gap-2.5 px-4 py-2 rounded-full bg-emerald-500/10 border border-emerald-500/20 backdrop-blur-sm">
                <span className="relative flex h-2 w-2">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
                  <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500" />
                </span>
                {new24h !== null ? (
                  <span className="text-xs font-semibold text-emerald-400">
                    <span className="text-sm font-extrabold">{new24h.toLocaleString("en-US")}</span>{" "}
                    {t("hero.live.new_24h")}
                  </span>
                ) : (
                  <span className="text-xs font-semibold text-emerald-400">{t("hero.badge_live")}</span>
                )}
              </div>
              {lastUpdate ? (
                <span className="text-[11px] text-slate-500 pl-1">
                  {t("hero.live.updated")} {formatUpdatedSince(lastUpdate, t)}
                </span>
              ) : null}
            </div>

            {/* Main headline */}
            <h1 className="text-4xl md:text-6xl lg:text-7xl font-extrabold leading-[1.05] tracking-tight mb-6">
              <span className="block text-white">{t("hero.title.1")}</span>
              <span className="block bg-gradient-to-r from-emerald-400 via-emerald-300 to-cyan-400 bg-clip-text text-transparent">
                {t("hero.title.2")}
              </span>
            </h1>

            {/* Subheadline */}
            <p className="text-lg md:text-xl lg:text-2xl text-slate-400 max-w-xl lg:max-w-2xl leading-relaxed mb-10 animate-fade-in-up delay-200">
              {t("hero.sub")}
            </p>

            {/* Trust Indicators */}
            <div className="flex flex-wrap items-center gap-4 mb-10 animate-fade-in-up delay-300">
              <div className="flex items-center gap-2 px-4 py-2 rounded-xl bg-slate-800/50 border border-slate-700/50 backdrop-blur-sm">
                <Shield className="h-4 w-4 text-emerald-400" />
                <span className="text-sm font-medium text-slate-300">{t("hero.trust.verified")}</span>
              </div>
              <div className="flex items-center gap-2 px-4 py-2 rounded-xl bg-slate-800/50 border border-slate-700/50 backdrop-blur-sm">
                <Zap className="h-4 w-4 text-blue-400" />
                <span className="text-sm font-medium text-slate-300">{t("hero.trust.real_time")}</span>
              </div>
              <div className="flex items-center gap-2 px-4 py-2 rounded-xl bg-slate-800/50 border border-slate-700/50 backdrop-blur-sm">
                <CheckCircle className="h-4 w-4 text-amber-400" />
                <span className="text-sm font-medium text-slate-300">{t("hero.trust.no_contract")}</span>
              </div>
            </div>

            {/* CTA Buttons */}
            <div className="flex flex-col sm:flex-row gap-4 mb-10 animate-fade-in-up delay-400">
              <DemoLoginButton className="btn-primary w-full sm:w-auto group">
                <Zap className="h-5 w-5 group-hover:animate-bounce" />
                {t("hero.cta.demo")}
              </DemoLoginButton>
              <a
                href="#preco"
                className="btn-secondary w-full sm:w-auto"
              >
                {t("hero.cta.price")} <ArrowRight className="h-5 w-5 group-hover:translate-x-1 transition-transform" />
              </a>
            </div>

            {/* Trust note */}
            <p className="text-slate-500 text-sm animate-fade-in-up delay-500">{t("hero.note")}</p>

            {/* Social Proof Stats */}
            <div className="mt-12 pt-8 border-t border-slate-800/50 flex flex-wrap items-center justify-center lg:justify-start gap-8 animate-fade-in-up delay-600">
              <div className="text-center">
                <div className="text-3xl md:text-4xl font-extrabold text-emerald-400">{fmt(stats?.total_leads)}</div>
                <div className="text-xs text-slate-500 mt-1">{t("hero.stats.leads")}</div>
              </div>
              <div className="w-px h-8 bg-slate-700/50 mx-4 hidden sm:block" />
              <div className="text-center">
                <div className="text-3xl md:text-4xl font-extrabold text-emerald-400">{fmt(stats?.leads_with_owner)}</div>
                <div className="text-xs text-slate-500 mt-1">{t("hero.stats.with_owner")}</div>
              </div>
              <div className="w-px h-8 bg-slate-700/50 mx-4 hidden sm:block" />
              <div className="text-center">
                <div className="text-3xl md:text-4xl font-extrabold text-emerald-400">{fmtCities(stats?.cities?.length)}</div>
                <div className="text-xs text-slate-500 mt-1">{t("hero.stats.cities")}</div>
              </div>
              <div className="w-px h-8 bg-slate-700/50 mx-4 hidden sm:block" />
              <div className="text-center">
                <div className="text-3xl md:text-4xl font-extrabold text-emerald-400">{new24h !== null ? `${new24h.toLocaleString("en-US")}+` : "…"}</div>
                <div className="text-xs text-slate-500 mt-1">{t("hero.stats.new_24h")}</div>
              </div>
            </div>
          </div>

          {/* RIGHT COLUMN - App Mockup */}
          <div className="lg:order-1 relative animate-fade-in-up delay-200">
            <div className="relative mx-auto max-w-md lg:max-w-lg">
              {/* Floating glow behind phone */}
              <div className="absolute -inset-8 bg-gradient-to-r from-emerald-500/20 to-cyan-500/20 rounded-[60px] blur-3xl animate-pulse-slow" />
              
              {/* Phone Frame */}
              <div className="relative bg-slate-950 rounded-[50px] p-1.5 border border-slate-700/50 shadow-2xl shadow-emerald-500/10">
                <div className="bg-slate-900 rounded-[48px] overflow-hidden border border-slate-700/30">
                  {/* Status Bar */}
                  <div className="flex items-center justify-between px-6 py-4 text-xs text-slate-500 border-b border-slate-800">
                    <span className="font-medium text-slate-400">9:41</span>
                    <div className="flex items-center gap-2">
                      <div className="w-8 h-4 bg-green-500 rounded-full" />
                      <div className="w-14 h-6 bg-slate-800 rounded-full flex items-center justify-end px-1.5">
                        <div className="w-4 h-4 bg-white rounded-full" />
                      </div>
                    </div>
                  </div>

                  {/* App Content */}
                  <div className="p-6 space-y-4">
                    {/* Search Bar with live indicator */}
                    <div className="relative bg-slate-800/50 rounded-xl p-4 border border-slate-700/50">
                      <div className="flex items-center gap-3 mb-3">
                        <div className="flex items-center gap-2 text-slate-400">
                          <RadioIcon className="h-4 w-4 text-emerald-400" />
                          <span className="text-sm font-medium text-slate-300">{t("hero.mockup.search_placeholder")}</span>
                        </div>
                        <div className="ml-auto flex items-center gap-1.5 text-xs">
                          <span className="w-1.5 h-1.5 bg-emerald-400 rounded-full animate-pulse" />
                          <span className="text-emerald-400 font-medium">{t("hero.mockup.live")}</span>
                        </div>
                      </div>
                      <div className="bg-slate-900/50 rounded-lg p-3 text-slate-500 text-sm">
                        🔍 {t("hero.mockup.search_placeholder")}
                      </div>
                    </div>

                    {/* Live Lead Cards */}
                    <div className="space-y-3">
                      {[
                        { type: "ROOF", icon: "🏠", label: t("hero.mockup.lead_types.roof"), address: "•••• Broadway, NYC", urgency: "URGENTE", urgencyColor: "red", time: "Há 3 min" },
                        { type: "PLUMBING", icon: "🔧", label: t("hero.mockup.lead_types.plumbing"), address: "•••• Oak St, Boston", urgency: "ALTA", urgencyColor: "amber", time: "Há 12 min" },
                        { type: "GRASS", icon: "🌿", label: t("hero.mockup.lead_types.grass"), address: "•••• Elm Ave, Dallas", urgency: "NORMAL", urgencyColor: "emerald", time: "Há 42 min" },
                      ].map((lead, i) => (
                        <div key={i} className="group bg-slate-800/50 rounded-xl p-4 border border-slate-700/50 hover:border-emerald-500/30 hover:bg-slate-800/30 transition-all duration-300">
                          <div className="flex items-start justify-between gap-3 mb-3">
                            <span className={`px-3 py-1 rounded-full text-xs font-bold uppercase tracking-wider bg-${lead.urgencyColor}-500/20 text-${lead.urgencyColor}-400`}>
                              {lead.urgency}
                            </span>
                            <span className="text-[10px] text-slate-500">{lead.time}</span>
                          </div>
                          <div className="flex items-center gap-3 mb-3">
                            <div className="w-14 h-14 rounded-xl bg-gradient-to-br from-emerald-500/30 to-cyan-500/30 flex items-center justify-center flex-shrink-0">
                              <span className="text-2xl">{lead.icon}</span>
                            </div>
                            <div className="flex-1 min-w-0">
                              <p className="font-semibold text-white truncate">{lead.label}</p>
                              <p className="text-xs text-slate-400 truncate">{lead.address}</p>
                            </div>
                          </div>
                          <button className="w-full group bg-gradient-to-r from-emerald-500 to-emerald-600 hover:from-emerald-600 hover:to-emerald-700 text-white font-semibold py-3 rounded-xl transition-all duration-200 hover:shadow-lg hover:shadow-emerald-500/30 flex items-center justify-center gap-2">
                            <Smartphone className="h-5 w-5 group-hover:scale-110 transition-transform" />
                            <span>{t("hero.mockup.send_sms")}</span>
                            <ArrowRight className="h-4 w-4 group-hover:translate-x-1 transition-transform" />
                          </button>
                        </div>
                      ))}
                    </div>

                    {/* Bottom Nav */}
                    <div className="flex items-center justify-around pt-4 border-t border-slate-800/50">
                      {[
                        { icon: "📋", label: t("hero.mockup.nav.leads"), active: true },
                        { icon: "🗺️", label: t("hero.mockup.nav.map"), active: false },
                        { icon: "⭐", label: t("hero.mockup.nav.favorites"), active: false },
                        { icon: "👤", label: t("hero.mockup.nav.profile"), active: false },
                      ].map((nav, i) => (
                        <button key={i} className={`flex flex-col items-center gap-1 px-4 py-2 rounded-xl transition-all duration-200 ${i === 0 ? "text-emerald-400 bg-emerald-500/10" : "text-slate-500 hover:text-slate-300"}`}>
                          <span className="text-xl">{nav.icon}</span>
                          <span className="text-[10px] font-medium">{nav.label}</span>
                          {i === 0 && <div className="w-1.5 h-1.5 bg-emerald-400 rounded-full mt-1 animate-pulse" />}
                        </button>
                      ))}
                    </div>
                  </div>
                </div>
              </div>

              {/* Floating Trust Badges */}
              <div className="absolute -top-6 -right-6 hidden lg:block animate-float delay-300">
                <div className="bg-slate-900/80 backdrop-blur-xl border border-emerald-500/30 rounded-2xl p-4 shadow-2xl shadow-emerald-500/10">
                  <div className="flex items-center gap-3 text-white">
                    <div className="p-3 rounded-xl bg-emerald-500/20">
                      <CheckCircle2 className="h-6 w-6 text-emerald-400" />
                    </div>
                    <div>
                      <p className="font-semibold text-sm">{t("hero.mockup.badge_verified")}</p>
                      <p className="text-xs text-slate-400">{t("hero.mockup.badge_verified_desc")}</p>
                    </div>
                  </div>
                </div>
              </div>

              <div className="absolute -bottom-6 -left-6 hidden lg:block animate-float delay-500">
                <div className="bg-slate-900/80 backdrop-blur-xl border border-blue-500/30 rounded-2xl p-4 shadow-2xl shadow-blue-500/10">
                  <div className="flex items-center gap-3 text-white">
                    <div className="p-3 rounded-xl bg-blue-500/20">
                      <Zap className="h-6 w-6 text-blue-400" />
                    </div>
                    <div>
                      <p className="font-semibold text-sm">{t("hero.mockup.badge_realtime")}</p>
                      <p className="text-xs text-slate-400">{t("hero.mockup.badge_realtime_desc")}</p>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
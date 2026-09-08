'use client';

import { Satellite, ShieldCheck, MessageSquare, TrendingUp, Target, DollarSign, Users, BarChart3, SlidersHorizontal, ChevronDown } from "lucide-react";
import { useI18n } from "@/lib/i18n";
import { useStats } from "@/lib/hooks/useStats";
import { useState } from "react";

const ANNUAL_COST = 4108;

export function HowItWorks() {
  const { t } = useI18n();
  const { stats, loading } = useStats();
  const [jobValue, setJobValue] = useState(2500);
  const [conversionRate, setConversionRate] = useState(20);
  const [showCalc, setShowCalc] = useState(false);

  const steps = [
    {
      icon: Satellite,
      title: t("how.step1.title"),
      desc: t("how.step1.desc"),
      detail: t("how.step1.detail"),
    },
    {
      icon: ShieldCheck,
      title: t("how.step2.title"),
      desc: t("how.step2.desc"),
      detail: t("how.step2.detail"),
    },
    {
      icon: MessageSquare,
      title: t("how.step3.title"),
      desc: t("how.step3.desc"),
      detail: t("how.step3.detail"),
    },
  ];

  const fmt = (n?: number) => (n !== undefined ? n.toLocaleString("en-US") : "…");

  // Real base metrics
  const getLeadsTotal = () => {
    if (!stats || !stats.total_leads) return undefined;
    return stats.total_leads;
  };

  const getLeadsWeek = () => {
    const total = getLeadsTotal();
    if (total === undefined) return undefined;
    return Math.floor(total / 8);
  };

  const getResponsesWeek = () => {
    const week = getLeadsWeek();
    if (week === undefined) return undefined;
    return Math.floor(week * (conversionRate / 100));
  };

  // Honest annual anchor: 1 closed job per month
  const getOneJobAnnual = () => jobValue * 12;

  const getROI = () => {
    const roi = Math.floor(((getOneJobAnnual() - ANNUAL_COST) / ANNUAL_COST) * 100);
    return roi > 0 ? `${fmt(roi)}%` : "0%";
  };

  const roiStats = [
    { icon: Target, label: t("roi.base_leads"), value: fmt(getLeadsTotal()), desc: t("roi.base_leads_desc"), color: "text-cyan-400" },
    { icon: Users, label: t("roi.leads_week"), value: fmt(getLeadsWeek()) !== "…" ? `${fmt(getLeadsWeek())}+` : "…", desc: t("roi.leads_week_desc"), color: "text-blue-400" },
    { icon: SlidersHorizontal, label: t("roi.conversion"), value: `${conversionRate}%`, desc: t("roi.conversion_desc"), color: "text-violet-400" },
    { icon: BarChart3, label: t("roi.responses_week"), value: fmt(getResponsesWeek()) !== "…" ? `${fmt(getResponsesWeek())}+` : "…", desc: t("roi.responses_week_desc"), color: "text-emerald-400" },
    { icon: DollarSign, label: t("roi.cost_annual"), value: "$79/semana", desc: t("roi.cost_annual_desc"), color: "text-amber-400" },
    { icon: TrendingUp, label: t("roi.roi"), value: getROI(), desc: t("roi.roi_desc"), color: "text-emerald-400" },
  ];

  return (
    <section className="section bg-slate-950/30" aria-labelledby="how-title">
      <div className="container-custom">
        <div className="text-center mb-12">
          <h2 id="how-title" className="section-title">
            {t("how.title.1")}<span className="text-emerald-400"> {t("how.title.2")}</span>
          </h2>
          <p className="section-subtitle">{t("how.sub")}</p>
        </div>

        {/* 3 Steps */}
        <div className="grid md:grid-cols-3 gap-6 mb-12">
          {steps.map((step, i) => (
            <div key={step.title} className="card p-6 relative overflow-hidden group">
              <div className="absolute top-4 right-4 text-6xl font-extrabold text-emerald-500/10 group-hover:text-emerald-500/20 transition-colors">{i + 1}</div>
              <div className="relative z-10">
                <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-emerald-500 to-emerald-600 text-white flex items-center justify-center mb-4">
                  <step.icon className="h-6 w-6" />
                </div>
                <h3 className="font-bold text-lg text-white mb-2">{step.title}</h3>
                <p className="text-muted-foreground text-sm mb-3">{step.desc}</p>
                <p className="text-xs text-primary/80 font-medium">{step.detail}</p>
              </div>
            </div>
          ))}
        </div>

        {/* ROI Calculator Section */}
        <div className="rounded-2xl bg-gradient-to-br from-emerald-500/5 via-slate-900/50 to-slate-950 border border-emerald-500/20 p-6 md:p-8">
          <div className="text-center mb-8">
            <h3 className="text-2xl md:text-3xl font-extrabold mb-2">{t("roi.title")}</h3>
            <p className="text-slate-400 max-w-2xl mx-auto">{t("roi.sub")}</p>
            <p className="mt-3 text-lg md:text-xl font-bold text-emerald-300">{t("roi.hook")}</p>
          </div>

          {/* ROI Calculator Controls (collapsible) */}
          <div className="flex justify-center mb-6">
            <button
              type="button"
              onClick={() => setShowCalc(!showCalc)}
              aria-expanded={showCalc}
              className="inline-flex items-center gap-2 rounded-full border border-emerald-500/40 bg-emerald-500/10 px-5 py-2.5 text-sm font-medium text-emerald-300 hover:bg-emerald-500/20 transition-colors"
            >
              <SlidersHorizontal className="h-4 w-4" />
              {t("roi.calculator.toggle")}
              <span className="text-xs text-slate-400 hidden sm:inline">· ${jobValue.toLocaleString("en-US")} · {conversionRate}%</span>
              <ChevronDown className={`h-4 w-4 transition-transform ${showCalc ? "rotate-180" : ""}`} />
            </button>
          </div>

          {showCalc && (
          <div className="grid md:grid-cols-2 gap-6 mb-8 p-6 rounded-2xl bg-slate-900/50 border border-slate-800/50">
            {/* Job Value Slider */}
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-3">
                {t("roi.calculator.job_value_label")}: <span className="text-emerald-400 font-bold">${jobValue.toLocaleString("en-US")}</span>
              </label>
              <input
                type="range"
                min="2000"
                max="20000"
                step="500"
                value={jobValue}
                onChange={(e) => setJobValue(Number(e.target.value))}
                className="w-full h-2 bg-slate-700 rounded-lg appearance-none cursor-pointer accent-emerald-500"
              />
              <p className="text-xs text-slate-500 mt-2">{t("roi.calculator.job_value_help")}</p>
            </div>

            {/* Conversion Rate Slider */}
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-3">
                {t("roi.calculator.conversion_label")}: <span className="text-emerald-400 font-bold">{conversionRate}%</span>
              </label>
              <input
                type="range"
                min="5"
                max="35"
                step="1"
                value={conversionRate}
                onChange={(e) => setConversionRate(Number(e.target.value))}
                className="w-full h-2 bg-slate-700 rounded-lg appearance-none cursor-pointer accent-emerald-500"
              />
              <p className="text-xs text-slate-500 mt-2">{t("roi.calculator.conversion_help")}</p>
            </div>
          </div>
          )}

          {/* ROI Results Grid */}
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 mb-8">
            {roiStats.map((stat) => (
              <div key={stat.label} className="bg-slate-900/50 rounded-2xl p-4 border border-slate-800/50 hover:border-emerald-500/30 transition-colors group min-w-0">
                <div className="flex items-center justify-center w-10 h-10 rounded-xl bg-emerald-500/15 mx-auto mb-2.5 group-hover:bg-emerald-500/25 transition-colors">
                  <stat.icon className={`h-4 w-4 ${stat.color}`} />
                </div>
                <div className="text-base sm:text-xl lg:text-2xl font-extrabold text-white text-center whitespace-nowrap mb-1 group-hover:text-emerald-400 transition-colors">{stat.value}</div>
                <div className="text-[11px] leading-tight text-slate-500 uppercase tracking-wide text-center mb-1">{stat.label}</div>
                <p className="text-[11px] leading-snug text-slate-500 text-center">{stat.desc}</p>
              </div>
            ))}
          </div>

          {/* Annual Projection — honest floor: 1 job/month */}
          <div className="rounded-2xl bg-gradient-to-r from-emerald-500/10 to-emerald-600/10 border border-emerald-500/20 p-6">
            <div className="flex items-center justify-center gap-3 mb-3">
              <div className="p-3 rounded-xl bg-emerald-500/20">
                <TrendingUp className="h-6 w-6 text-emerald-400" />
              </div>
            </div>
            <h3 className="text-xl font-bold text-white mb-2">{t("roi.annual_projection")}</h3>
            <div className="grid md:grid-cols-3 gap-4 text-center">
              <div>
                <div className="text-3xl font-extrabold bg-gradient-to-r from-emerald-400 to-emerald-600 bg-clip-text text-transparent">${(getOneJobAnnual() / 1000).toFixed(0)}K/ano</div>
                <div className="text-xs text-slate-400">{t("roi.one_job_annual")}</div>
              </div>
              <div className="border-l border-slate-700/50 mx-4 my-2 hidden md:block" />
              <div>
                <div className="text-3xl font-extrabold text-amber-400">$4.108/ano</div>
                <div className="text-xs text-slate-400">{t("roi.cost_annual")}</div>
              </div>
              <div className="border-l border-slate-700/50 mx-4 my-2 hidden md:block" />
              <div>
                <div className="text-3xl font-extrabold text-emerald-400">{getROI()}</div>
                <div className="text-xs text-slate-400">{t("roi.roi_label")}</div>
              </div>
            </div>
            <p className="text-xs text-slate-500 mt-4 text-center">{t("roi.projection_disclaimer")}</p>
          </div>

          <p className="mt-6 text-center text-slate-400 text-sm border-t border-slate-800/50 pt-6 flex items-center justify-center gap-2">
            <TrendingUp className="h-4 w-4 text-emerald-400" />
            {t("roi.note")}
          </p>
        </div>
      </div>
    </section>
  );
}
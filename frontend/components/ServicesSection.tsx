"use client";

import { useI18n } from "@/lib/i18n";
import { Home, Building2, Droplets, Paintbrush, Zap, Flame } from "lucide-react";

export function ServicesSection() {
  const { t } = useI18n();

  const services = [
    { icon: Home, labelKey: "lp.services.roof", descKey: "lp.services.roof_desc" },
    { icon: Building2, labelKey: "lp.services.structure", descKey: "lp.services.structure_desc" },
    { icon: Droplets, labelKey: "lp.services.plumbing", descKey: "lp.services.plumbing_desc" },
    { icon: Paintbrush, labelKey: "lp.services.painting", descKey: "lp.services.painting_desc" },
    { icon: Zap, labelKey: "lp.services.electrical", descKey: "lp.services.electrical_desc" },
    { icon: Flame, labelKey: "lp.services.heating", descKey: "lp.services.heating_desc" },
  ];

  return (
    <section className="py-16 md:py-24 bg-gradient-to-b from-slate-50 to-white dark:from-slate-900 dark:to-slate-950" aria-labelledby="services-title">
      <div className="container-custom">
        <div className="text-center max-w-3xl mx-auto mb-12 md:mb-16">
          <h2 id="services-title" className="text-3xl md:text-4xl font-extrabold tracking-tight text-slate-900 dark:text-white mb-4">
            {t("lp.services.title")}
          </h2>
          <p className="text-lg text-slate-600 dark:text-slate-300 max-w-2xl mx-auto">
            {t("lp.services.sub")}
          </p>
        </div>

        <div className="flex gap-3 md:gap-4 overflow-x-auto pb-6 snap-x snap-mandatory -mx-4 px-4" style={{ scrollbarWidth: "none", msOverflowStyle: "none" }}>
          {services.map((s, i) => (
            <div key={i} className="min-w-[280px] max-w-sm flex-shrink-0 snap-center">
              <div className="h-full bg-white dark:bg-slate-800 rounded-2xl border border-slate-200/50 dark:border-slate-700/50 shadow-sm hover:shadow-lg transition-shadow duration-300 p-6 flex flex-col">
                <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-indigo-500 via-indigo-600 to-fuchsia-600 flex items-center justify-center mb-4 text-white shadow-md shadow-indigo-500/20">
                  <s.icon className="h-6 w-6" />
                </div>
                <h3 className="text-lg font-bold text-slate-900 dark:text-white mb-2">
                  {t(s.labelKey)}
                </h3>
                <p className="text-slate-600 dark:text-slate-300 text-sm leading-relaxed flex-1">
                  {t(s.descKey)}
                </p>
              </div>
            </div>
          ))}
        </div>

        <div className="mt-10 text-center">
          <p className="text-slate-600 dark:text-slate-400 text-sm mb-6 max-w-2xl mx-auto">
            {t("lp.services.note")}
          </p>
          <div className="flex flex-wrap justify-center gap-3 text-sm">
            <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-amber-500/10 text-amber-600 dark:text-amber-400 dark:bg-amber-500/10">
              <span className="w-2 h-2 rounded-full bg-amber-500" /> {t("lp.services.signal.obligation")}
            </span>
            <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-sky-500/10 text-sky-600 dark:text-sky-400 dark:bg-sky-500/10">
              <span className="w-2 h-2 rounded-full bg-sky-500" /> {t("lp.services.signal.permit")}
            </span>
            <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-slate-500/10 text-slate-600 dark:text-slate-400 dark:bg-slate-500/10">
              <span className="w-2 h-2 rounded-full bg-slate-500" /> {t("lp.services.signal.open")}
            </span>
          </div>
          <p className="mt-4 text-slate-500 dark:text-slate-500 text-xs max-w-2xl mx-auto">
            {t("lp.services.note_full")}
          </p>
        </div>
      </div>
    </section>
  );
}
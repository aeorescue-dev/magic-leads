'use client';

import { CheckCircle2, XCircle, TrendingUp, Star, Crown, Info } from "lucide-react";
import { useI18n } from "@/lib/i18n";

type RowVal = string | boolean;

export function ComparisonTable() {
  const { t } = useI18n();

  const rows: Array<{
    key: string;
    label: string;
    google: RowVal;
    homeadvisor: RowVal;
    meta: RowVal;
    magic: RowVal;
    type?: "boolean";
    highlight?: boolean;
  }> = [
    {
      key: "cost",
      label: t("compare.row.cost"),
      google: t("compare.values.google.cost"),
      homeadvisor: t("compare.values.homeadvisor.cost"),
      meta: t("compare.values.meta.cost"),
      magic: t("compare.values.magic.cost"),
      highlight: true,
    },
    {
      key: "shared",
      label: t("compare.row.shared"),
      google: t("compare.values.google.shared"),
      homeadvisor: t("compare.values.homeadvisor.shared"),
      meta: t("compare.values.meta.shared"),
      magic: t("compare.values.magic.shared"),
      highlight: false,
    },
    {
      key: "roi",
      label: t("compare.row.roi"),
      google: t("compare.values.google.roi"),
      homeadvisor: t("compare.values.homeadvisor.roi"),
      meta: t("compare.values.meta.roi"),
      magic: t("compare.values.magic.roi"),
      highlight: false,
    },
    {
      key: "booked",
      label: t("compare.row.booked"),
      google: t("compare.values.google.booked"),
      homeadvisor: t("compare.values.homeadvisor.booked"),
      meta: t("compare.values.meta.booked"),
      magic: t("compare.values.magic.booked"),
      highlight: true,
    },
    {
      key: "volume",
      label: t("compare.row.volume"),
      google: t("compare.values.google.volume"),
      homeadvisor: t("compare.values.homeadvisor.volume"),
      meta: t("compare.values.meta.volume"),
      magic: t("compare.values.magic.volume"),
      highlight: false,
    },
    {
      key: "no_contract",
      label: t("compare.row.no_contract"),
      google: true,
      homeadvisor: false,
      meta: true,
      magic: true,
      type: "boolean",
      highlight: false,
    },
    {
      key: "own_data",
      label: t("compare.row.own_data"),
      google: false,
      homeadvisor: false,
      meta: false,
      magic: true,
      type: "boolean",
      highlight: false,
    },
    {
      key: "support",
      label: t("compare.row.support"),
      google: t("compare.values.google.support"),
      homeadvisor: t("compare.values.homeadvisor.support"),
      meta: t("compare.values.meta.support"),
      magic: t("compare.values.magic.support"),
      highlight: false,
    },
  ];

  const boolCell = (v: RowVal) =>
    v ? (
      <CheckCircle2 className="h-5 w-5 text-emerald-500" />
    ) : (
      <XCircle className="h-5 w-5 text-slate-700" />
    );

  const bullet = (row: (typeof rows)[number], col: "google" | "homeadvisor" | "meta" | "magic") => {
    if (row.type === "boolean") {
      return boolCell(row[col]);
    }
    return <span className="font-medium text-slate-300 text-right">{String(row[col])}</span>;
  };

  return (
    <section className="section bg-slate-950/30" aria-labelledby="compare-title">
      <div className="container-custom">
        <div className="text-center mb-12">
          <h2 id="compare-title" className="section-title">
            {t("compare.title.1")}<span className="text-emerald-400"> {t("compare.title.2")}</span>
          </h2>
          <p className="section-subtitle">{t("compare.sub")}</p>
        </div>

        {/* Plain-language summary */}
        <div className="mb-12 rounded-2xl bg-slate-900/60 border border-emerald-500/25 p-5 md:p-6 flex items-start gap-3">
          <Info className="h-5 w-5 text-emerald-400 mt-1 shrink-0" />
          <p className="text-slate-300 text-sm md:text-base leading-relaxed">{t("compare.summary")}</p>
        </div>

        {/* Comparison Cards - Visual Card Layout */}
        <div className="grid md:grid-cols-2 xl:grid-cols-4 gap-6 mb-12">
          {/* Google Local Services */}
          <div className="card p-6 relative">
            <div className="flex items-center gap-3 mb-4">
              <div className="p-3 rounded-xl bg-blue-500/20">
                <span className="text-2xl">🔵</span>
              </div>
              <div>
                <h3 className="font-bold text-lg text-white">{t("compare.header.google")}</h3>
                <p className="text-xs text-slate-500">{t("compare.lead_model.lead_gen")}</p>
              </div>
            </div>
            <ul className="space-y-3 text-sm">
              {rows.map((row) => (
                <li key={row.key} className="flex justify-between items-center gap-3 py-2 border-b border-slate-800/50 last:border-0">
                  <span className="text-slate-400">{row.label}</span>
                  <span className="text-right">{bullet(row, "google")}</span>
                </li>
              ))}
            </ul>
          </div>

          {/* HomeAdvisor */}
          <div className="card p-6 relative">
            <div className="flex items-center gap-3 mb-4">
              <div className="p-3 rounded-xl bg-orange-500/20">
                <span className="text-2xl">🟠</span>
              </div>
              <div>
                <h3 className="font-bold text-lg text-white">{t("compare.header.homeadvisor")}</h3>
                <p className="text-xs text-slate-500">{t("compare.lead_model.lead_gen")}</p>
              </div>
            </div>
            <ul className="space-y-3 text-sm">
              {rows.map((row) => (
                <li key={row.key} className="flex justify-between items-center gap-3 py-2 border-b border-slate-800/50 last:border-0">
                  <span className="text-slate-400">{row.label}</span>
                  <span className="text-right">{bullet(row, "homeadvisor")}</span>
                </li>
              ))}
            </ul>
          </div>

          {/* Meta Ads */}
          <div className="card p-6 relative">
            <div className="flex items-center gap-3 mb-4">
              <div className="p-3 rounded-xl bg-sky-500/20">
                <span className="text-2xl">🔷</span>
              </div>
              <div>
                <h3 className="font-bold text-lg text-white">{t("compare.header.meta")}</h3>
                <p className="text-xs text-slate-500">{t("compare.lead_model.lead_gen")}</p>
              </div>
            </div>
            <ul className="space-y-3 text-sm">
              {rows.map((row) => (
                <li key={row.key} className="flex justify-between items-center gap-3 py-2 border-b border-slate-800/50 last:border-0">
                  <span className="text-slate-400">{row.label}</span>
                  <span className="text-right">{bullet(row, "meta")}</span>
                </li>
              ))}
            </ul>
          </div>

          {/* Magic Leads - HIGHLIGHTED */}
          <div className="card relative border-2 border-emerald-500/50 bg-gradient-to-br from-emerald-500/5 via-slate-900/80 to-slate-950 shadow-2xl shadow-emerald-500/10">
            {/* Recommended Badge */}
            <div className="absolute -top-3 left-1/2 -translate-x-1/2">
              <span className="inline-flex items-center gap-1.5 px-4 py-1.5 rounded-full bg-gradient-to-r from-emerald-500 to-emerald-600 text-white text-sm font-bold uppercase tracking-wider shadow-lg shadow-emerald-500/40">
                <Star className="h-4 w-4" />
                {t("compare.badge_recommended")}
              </span>
            </div>

            <div className="pt-6">
              <div className="flex items-center gap-3 mb-4">
                <div className="p-3 rounded-xl bg-gradient-to-r from-emerald-500 to-emerald-600 shadow-lg shadow-emerald-500/30">
                  <Crown className="h-5 w-5 text-white" />
                </div>
                <div>
                  <h3 className="font-bold text-lg text-white">{t("compare.header.magic")}</h3>
                  <p className="text-xs text-emerald-300">{t("compare.lead_model.flat_fee")}</p>
                </div>
              </div>
              <ul className="space-y-3 text-sm">
                {rows.map((row) => (
                  <li key={row.key} className="flex justify-between items-center gap-3 py-2 border-b border-slate-800/50 last:border-0">
                    <span className="text-slate-400">{row.label}</span>
                    {row.type === "boolean" ? (
                      <span>{boolCell(row.magic)}</span>
                    ) : (
                      <span className={row.highlight ? "text-lg font-bold text-emerald-400" : "font-medium text-emerald-300"}>
                        {row.magic}
                      </span>
                    )}
                  </li>
                ))}
              </ul>

              {/* CTA Button */}
              <div className="mt-6 pt-4 border-t border-emerald-500/20">
                <a href="#preco" className="btn-primary w-full text-center">
                  <Crown className="h-4 w-4" />
                  {t("compare.cta")}
                </a>
              </div>
            </div>
          </div>
        </div>

        {/* Fontes dos dados */}
        <p className="text-xs text-slate-500 mt-6 text-center max-w-4xl mx-auto leading-relaxed">
          <Info className="inline h-3.5 w-3.5 mr-1 -mt-0.5" />
          {t("compare.note")}
        </p>

        {/* ROI Highlight Section */}
        <div className="mt-12 rounded-2xl bg-gradient-to-r from-emerald-500/10 via-slate-900/50 to-emerald-500/10 border border-emerald-500/20 p-8 md:p-12 text-center">
          <div className="flex items-center justify-center gap-3 mb-4">
            <div className="p-3 rounded-xl bg-emerald-500/20">
              <TrendingUp className="h-8 w-8 text-emerald-400" />
            </div>
          </div>
          <p className="text-3xl md:text-4xl font-extrabold bg-gradient-to-r from-emerald-400 via-emerald-300 to-cyan-400 bg-clip-text text-transparent mb-3">
            {t("compare.roi_highlight")}
          </p>
          <p className="text-slate-400 text-lg max-w-2xl mx-auto">{t("compare.roi_note")}</p>
        </div>
      </div>
    </section>
  );
}
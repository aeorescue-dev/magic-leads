'use client';

import { CheckCircle2, Shield, Clock, RotateCcw, ArrowRight } from "lucide-react";
import { useI18n } from "@/lib/i18n";
import { DemoLoginButton } from "@/components/DemoLoginButton";

export function PricingSection() {
  const { t } = useI18n();

  return (
    <section id="preco" className="py-20 bg-background" aria-labelledby="pricing-title">
      <div className="container mx-auto px-4 max-w-4xl">
        <div className="text-center mb-12">
          <h2 id="pricing-title" className="text-3xl md:text-4xl font-extrabold text-foreground tracking-tight">
            {t("pricing.title.1")}<span className="text-primary"> {t("pricing.title.2")}</span>
          </h2>
          <p className="text-center text-muted-foreground max-w-2xl mx-auto mt-3">{t("pricing.sub")}</p>
        </div>

        <div className="card p-8 md:p-10 ring-1 ring-primary/20 max-w-2xl mx-auto">
          <div className="text-center mb-8">
            <div className="inline-flex items-center gap-2 rounded-full bg-emerald-500/10 px-4 py-1.5 text-sm font-semibold text-emerald-700 mb-4">
              <Shield className="h-4 w-4" />
              {t("pricing.badge")}
            </div>
            <div className="text-6xl md:text-7xl font-extrabold text-primary">
              $79<span className="text-xl font-normal text-muted-foreground">{t("pricing.week")}</span>
            </div>
            <p className="text-muted-foreground mt-2">{t("pricing.all_included")}</p>
          </div>

          <ul className="space-y-3 mb-8">
            {[
              "pricing.f1",
              "pricing.f2",
              "pricing.f3",
              "pricing.f4",
              "pricing.f5",
              "pricing.f6",
              "pricing.f7",
              "pricing.f8",
            ].map((key) => (
              <li key={key} className="flex items-start gap-3">
                <CheckCircle2 className="h-5 w-5 text-emerald-500 mt-0.5 shrink-0" />
                <span className="text-muted-foreground">{t(key)}</span>
              </li>
            ))}
          </ul>

          <DemoLoginButton className="w-full">{t("pricing.cta")}</DemoLoginButton>

          <p className="text-center text-muted-foreground text-sm mt-4">{t("pricing.note")}</p>
        </div>

        {/* How billing works */}
        <div className="mt-10 rounded-2xl border border-slate-800 bg-[#0F172A]/80 backdrop-blur p-6">
          <h4 className="font-bold text-white mb-4 flex items-center gap-2">
            <RotateCcw className="h-4 w-4 text-[#10B981]" /> {t("pricing.cycle.title")}
          </h4>
          <ul className="space-y-2 text-sm text-slate-300">
            <li className="flex items-center gap-2"><Clock className="h-4 w-4 text-[#10B981]" /> {t("pricing.cycle.1")}</li>
            <li className="flex items-center gap-2"><Clock className="h-4 w-4 text-[#10B981]" /> {t("pricing.cycle.2")}</li>
            <li className="flex items-center gap-2"><Clock className="h-4 w-4 text-[#10B981]" /> {t("pricing.cycle.3")}</li>
            <li className="flex items-center gap-2"><Clock className="h-4 w-4 text-[#10B981]" /> {t("pricing.cycle.4")}</li>
          </ul>
        </div>

        {/* Limits transparency */}
        <div className="mt-6 rounded-2xl border border-slate-800 bg-[#0F172A]/80 backdrop-blur p-6">
          <h4 className="font-bold text-white mb-3">{t("pricing.limits.title")}</h4>
          <ul className="grid grid-cols-1 md:grid-cols-2 gap-2 text-sm text-slate-300">
            <li className="flex items-center gap-2"><Shield className="h-4 w-4 text-[#10B981]" /> {t("pricing.limit.1")}</li>
            <li className="flex items-center gap-2"><Shield className="h-4 w-4 text-[#10B981]" /> {t("pricing.limit.2")}</li>
            <li className="flex items-center gap-2"><Shield className="h-4 w-4 text-[#10B981]" /> {t("pricing.limit.3")}</li>
            <li className="flex items-center gap-2"><Shield className="h-4 w-4 text-[#10B981]" /> {t("pricing.limit.4")}</li>
          </ul>
        </div>
      </div>
    </section>
  );
}
'use client';

import { CheckCircle2, Shield, Clock, RotateCcw, Phone, Mail, Zap } from "lucide-react";
import { useI18n } from "@/lib/i18n";
import { DemoLoginButton } from "@/components/DemoLoginButton";

const PLANS = [
  { code: "starter", name: "Starter", price: "$25.90", phones: 2 },
  { code: "essential", name: "Essential", price: "$50.20", phones: 4 },
  { code: "growth", name: "Growth", price: "$74.34", phones: 6 },
  { code: "pro", name: "Pro", price: "$100.90", phones: 8, popular: true },
  { code: "business", name: "Business", price: "$126", phones: 10 },
  { code: "scale", name: "Scale", price: "$178.50", phones: 15 },
  { code: "agency", name: "Agency", price: "$231", phones: 20 },
] as const;

const COPY = {
  pt: {
    week: "/semana",
    phone: "telefones/dia",
    letters: "10 cartas/visitas/dia",
    popular: "Mais popular",
    cta: "Assinar",
    included: "Todos os planos incluem",
    includedItems: [
      "Endereço validado + proprietário identificado",
      "10 cartas/visitas por dia, todos os dias",
      "Cota diária de telefones (reinicia à meia-noite de Nova Iorque)",
      "Add-ons de 24h quando a cota termina",
    ],
    addonsTitle: "Add-ons de telefones (24h)",
    addons: "+2 $2,50 · +4 $4,80 · +6 $7,20 · +8 $9,60 · +10 $12 · +15 $18 · +20 $24",
  },
  en: {
    week: "/week",
    phone: "phones/day",
    letters: "10 letters/visits/day",
    popular: "Most popular",
    cta: "Subscribe",
    included: "Every plan includes",
    includedItems: [
      "Validated address + identified owner",
      "10 letters/visits every day",
      "Daily phone quota (resets at midnight New York time)",
      "24h add-ons when the quota runs out",
    ],
    addonsTitle: "Phone add-ons (24h)",
    addons: "+2 $2.50 · +4 $4.80 · +6 $7.20 · +8 $9.60 · +10 $12 · +15 $18 · +20 $24",
  },
  es: {
    week: "/semana",
    phone: "teléfonos/día",
    letters: "10 cartas/visitas/día",
    popular: "Más popular",
    cta: "Suscribirse",
    included: "Todos los planes incluyen",
    includedItems: [
      "Dirección validada + propietario identificado",
      "10 cartas/visitas cada día",
      "Cuota diaria de teléfonos (reinicia a medianoche de Nueva York)",
      "Add-ons de 24h cuando se termina la cuota",
    ],
    addonsTitle: "Add-ons de teléfonos (24h)",
    addons: "+2 $2,50 · +4 $4,80 · +6 $7,20 · +8 $9,60 · +10 $12 · +15 $18 · +20 $24",
  },
} as const;

export function PricingSection() {
  const { t, lang } = useI18n();
  const c = COPY[(lang as keyof typeof COPY) || "pt"] || COPY.pt;

  return (
    <section id="preco" className="py-20 bg-background" aria-labelledby="pricing-title">
      <div className="container mx-auto px-4 max-w-6xl">
        <div className="text-center mb-12">
          <h2 id="pricing-title" className="text-3xl md:text-4xl font-extrabold text-foreground tracking-tight">
            {t("pricing.title.1")}<span className="text-primary"> {t("pricing.title.2")}</span>
          </h2>
          <p className="text-center text-muted-foreground max-w-2xl mx-auto mt-3">{t("pricing.sub")}</p>
        </div>

        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {PLANS.map((plan) => (
            <div
              key={plan.code}
              className={`card flex flex-col p-5 ${
                "popular" in plan && plan.popular
                  ? "ring-2 ring-primary shadow-lg shadow-primary/10"
                  : "ring-1 ring-slate-800"
              }`}
            >
              <div className="flex items-center justify-between gap-2">
                <h3 className="text-base font-extrabold text-foreground">{plan.name}</h3>
                {"popular" in plan && plan.popular ? (
                  <span className="rounded-full bg-primary/15 px-2 py-0.5 text-[9px] font-black uppercase tracking-wide text-primary">
                    {c.popular}
                  </span>
                ) : null}
              </div>

              <div className="mt-3 flex items-baseline gap-1">
                <span className="text-3xl font-extrabold text-foreground">{plan.price}</span>
                <span className="text-xs font-medium text-muted-foreground">{c.week}</span>
              </div>

              <div className="mt-4 space-y-2 text-xs text-muted-foreground">
                <div className="flex items-center gap-2">
                  <Phone className="h-3.5 w-3.5 text-emerald-500 shrink-0" />
                  <span>
                    <b className="text-foreground">{plan.phones}</b> {c.phone}
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <Mail className="h-3.5 w-3.5 text-emerald-500 shrink-0" />
                  <span>{c.letters}</span>
                </div>
                <div className="flex items-center gap-2">
                  <Zap className="h-3.5 w-3.5 text-emerald-500 shrink-0" />
                  <span>Add-ons 24h</span>
                </div>
              </div>

              <div className="mt-5 flex-1" />
              <DemoLoginButton className="w-full">{c.cta}</DemoLoginButton>
            </div>
          ))}
        </div>

        <div className="mt-8 rounded-2xl border border-slate-800 bg-[#0F172A]/80 backdrop-blur p-6">
          <h4 className="font-bold text-white mb-4 flex items-center gap-2">
            <CheckCircle2 className="h-4 w-4 text-[#10B981]" /> {c.included}
          </h4>
          <ul className="grid grid-cols-1 md:grid-cols-2 gap-2 text-sm text-slate-300">
            {c.includedItems.map((item) => (
              <li key={item} className="flex items-start gap-2">
                <CheckCircle2 className="h-4 w-4 text-[#10B981] mt-0.5 shrink-0" />
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </div>

        {/* How billing works */}
        <div className="mt-6 rounded-2xl border border-slate-800 bg-[#0F172A]/80 backdrop-blur p-6">
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

        {/* Add-ons transparency */}
        <div className="mt-6 rounded-2xl border border-slate-800 bg-[#0F172A]/80 backdrop-blur p-6">
          <h4 className="font-bold text-white mb-3 flex items-center gap-2">
            <Zap className="h-4 w-4 text-[#10B981]" /> {c.addonsTitle}
          </h4>
          <p className="text-sm text-slate-300">{c.addons}</p>
        </div>

        {/* Limits transparency */}
        <div className="mt-6 rounded-2xl border border-slate-800 bg-[#0F172A]/80 backdrop-blur p-6">
          <h4 className="font-bold text-white mb-3 flex items-center gap-2">
            <Shield className="h-4 w-4 text-[#10B981]" /> {t("pricing.limits.title")}
          </h4>
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
